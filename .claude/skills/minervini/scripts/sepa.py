#!/usr/bin/env python3
"""Deterministic SEPA verdicts after Mark Minervini's "Trade Like a Stock Market Wizard".

The model fetches raw data (daily bars for the stock and the S&P 500, three quarters of
income-statement figures, the last earnings surprise) and writes it to one JSON file in
the shape of example_input.json. This script applies every rule:

    Can I buy?           BUY / BUY ON BREAKOUT / WAIT / AVOID
    Should I sell?       SELL / SELL INTO STRENGTH / HOLD, TIGHTEN STOP / HOLD
    Should I buy more?   ADD / ADD ON BREAKOUT / DON'T ADD

Same input -> same output. Bars dated after the last completed US session are dropped
before anything is computed, so asking twice during a trading day (when the live bar keeps
changing) gives the same answer. Every result carries a fingerprint of the data it used:
two runs with the same fingerprint have the same verdicts. Stdlib only.

Usage:
    python3 sepa.py input.json            # or pipe the JSON on stdin
"""
from __future__ import annotations

import bisect
import csv
import hashlib
import json
import math
import os
import sys
from datetime import date, datetime, timedelta, timezone

RULES_VERSION = "2026-11-08"

# ------------------------------------------------------------------- the book's rules
TT_LOW_PCT = 30.0         # TT6: at least 30% above the 52-week low
TT_HIGH_PCT = 25.0        # TT7: within 25% of the 52-week high
RS_MIN = 70               # TT8: RS ranking no less than 70
MONTH = 21                # sessions; TT3 needs the 200-day rising for >= 1 month
YEAR = 252                # sessions in the 52-week window
MAX_STOP_PCT = 10.0       # never risk more than 10% on a position
RISK_PCT = 1.25           # account risk per position: 1.25% normally ...
RISK_PCT_HIGH = 2.5       # ... up to 2.5% when trading well
BASE_MIN_SESSIONS = 15    # a base lasts 3 ...
BASE_MAX_SESSIONS = 325   # ... to 65 weeks

# ------------------------------------------- this skill's mechanical reading of the book
# Where the book describes a pattern instead of a number, these fix the number. Change
# them here and in references/methodology.md together, and update the tests on purpose.
RS_WEIGHTS = ((63, 0.4), (126, 0.2), (189, 0.2), (252, 0.2))   # IBD-style 3/6/9/12-month
# Weighted performance vs the S&P 500 (pp) -> RS-rating proxy. +10pp ~ 70, +20pp ~ 80.
RS_PTS = [(-40, 5), (-20, 20), (-10, 35), (0, 50), (10, 70), (20, 80), (35, 90), (60, 97), (100, 99)]
SWING_PCT = 2.0           # a new contraction needs a >=2% rally into its high and a >=2% pullback
TIGHTEN_TOL_PP = 1.0      # a contraction may be at most 1pp deeper than the one before it
FINAL_MAX_PCT = 10.0      # the last contraction must be 10% or less
DEPTH_MAX_PCT = 50.0      # deeper bases are not constructive
DEPTH_IDEAL_PCT = 35.0    # deeper than this is flagged
DRYUP_RATIO = 0.75        # quietest 5 sessions of the last 15 <= 75% of the base's average volume
BREAKOUT_VOL = 1.4        # breakout volume >= 1.4x the 50-day average
BUY_RANGE_PCT = 5.0       # buy no more than 5% above the pivot
BREAKOUT_WINDOW = 10      # a breakout older than 10 sessions is no longer a fresh entry
MAX_POSITION_PCT = 25.0   # cap on a single position, % of the account
BREAKEVEN_R = 2.0         # once up 2x the initial risk, the stop goes to breakeven
EPS_MIN_PCT = 20.0        # latest-quarter EPS growth needed
GAAP_GAP_PP = 25.0        # EPS vs operating-income growth gap that flags a GAAP distortion
HEAVY_VOL = 1.5           # "heavy volume" = 1.5x the 50-day average
CLIMAX_RUN_PCT = 25.0     # +25% within ...
CLIMAX_RUN_SESSIONS = 15  # ... 3 weeks
CLIMAX_UP_DAYS = 7        # 7+ up closes in the last 10 sessions
CLIMAX_EXT_200 = 70.0     # 70%+ above the 200-day
EARNINGS_NEAR_DAYS = 7    # flag a new buy this close to a report
SESSION_CUTOFF_ET = 18    # a bar dated today counts only after 18:00 New York time
MIN_BARS = 200 + MONTH    # 221 sessions to evaluate TT3
# Longest lookback any rule uses: the 65-week base window as of 10 sessions ago. Older bars
# are dropped before anything is computed, so fetching more history never changes a result.
KEEP_BARS = BASE_MAX_SESSIONS + BREAKOUT_WINDOW   # 335

BUY_VERDICTS = ("BUY", "BUY ON BREAKOUT", "WAIT", "AVOID")
HOLD_VERDICTS = ("SELL", "SELL INTO STRENGTH", "HOLD, TIGHTEN STOP", "HOLD")
ADD_VERDICTS = ("ADD", "ADD ON BREAKOUT", "DON'T ADD")
QUESTIONS = {"buy": "can I buy?", "sell": "should I sell?", "add": "should I buy more?"}


# ------------------------------------------------------------------------- helpers
def interp(x, pts):
    if x is None:
        return None
    if x <= pts[0][0]:
        return float(pts[0][1])
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return float(pts[-1][1])


def half_up(x):
    return int(math.floor(x + 0.5))


def yoy(new, old):
    if new is None or old is None or old <= 0:
        return None
    return (new / old - 1) * 100


def ratio(a, b):
    return None if a is None or not b else a / b


def money(x):
    return "n/a" if x is None else f"${x:,.2f}"


def vol_txt(v):
    if v is None:
        return "n/a"
    if v >= 1e9:
        return f"{v / 1e9:.2f}B"
    if v >= 1e6:
        return f"{v / 1e6:.1f}M"
    if v >= 1e3:
        return f"{v / 1e3:.0f}K"
    return f"{v:.0f}"


def pct_txt(x, digits=1):
    return "n/a" if x is None else f"{x:+.{digits}f}%"


def r2(x):
    return None if x is None else round(x, 2)


def cap(s):
    return s[:1].upper() + s[1:] if s else s


# ------------------------------------------------------------------------ data in
def _read_file(path):
    with open(path) as f:
        if path.lower().endswith(".csv"):
            return list(csv.DictReader(f))
        return json.load(f)


def parse_bars(raw, label):
    """Rows (date, open, high, low, close, volume), oldest first, plus data-quality flags.

    Accepts FMP objects ({date, open, high, low, close, volume}; `price` for the light
    endpoint), compact arrays [date, open, high, low, close, volume] or [date, close], or a
    path to a CSV/JSON file holding either.
    """
    if isinstance(raw, str):
        raw = _read_file(raw)
    flags, rows = [], {}
    for r in raw or []:
        if isinstance(r, dict):
            d = r.get("date")
            c = r.get("close", r.get("price"))
            o, h, lo, v = r.get("open", c), r.get("high", c), r.get("low", c), r.get("volume", 0)
        elif isinstance(r, (list, tuple)) and len(r) >= 6:
            d, o, h, lo, c, v = r[:6]
        elif isinstance(r, (list, tuple)) and len(r) >= 2:
            d, c = r[0], r[1]
            o = h = lo = c
            v = r[2] if len(r) > 2 else 0
        else:
            raise ValueError(f"{label}: can't read row {r!r}")
        if d is None or c is None:
            raise ValueError(f"{label}: row without date or close: {r!r}")
        d = str(d)[:10]
        date.fromisoformat(d)  # raises on a malformed date
        row = (d, float(o), float(h), float(lo), float(c), float(v or 0))
        if d in rows and rows[d] != row:
            flags.append(f"{label}: two different rows for {d}, kept the first")
            continue
        rows.setdefault(d, row)
    out = []
    for d in sorted(rows):
        d_, o, h, lo, c, v = rows[d]
        if h < max(o, c, lo) or lo > min(o, c):
            flags.append(f"{label}: {d} high/low inconsistent with open/close, widened to fit")
            h, lo = max(o, h, c, lo), min(o, h, c, lo)
        out.append((d, o, h, lo, c, v))
    for a, b in zip(out, out[1:]):
        gap = (date.fromisoformat(b[0]) - date.fromisoformat(a[0])).days
        if gap > 7:
            flags.append(f"{label}: {gap}-day gap between {a[0]} and {b[0]}, bars missing?")
    return out, flags


def new_york_now(now_utc=None):
    now_utc = now_utc or datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return now_utc.astimezone(ZoneInfo("America/New_York"))
    except Exception:  # no tz database: US DST rule (2nd Sun of Mar to 1st Sun of Nov)
        y = now_utc.year

        def sunday(month, nth):
            d = date(y, month, 1)
            return d + timedelta(days=(6 - d.weekday()) % 7 + 7 * (nth - 1))

        start = datetime.combine(sunday(3, 2), datetime.min.time(), timezone.utc) + timedelta(hours=7)
        end = datetime.combine(sunday(11, 1), datetime.min.time(), timezone.utc) + timedelta(hours=6)
        off = -4 if start <= now_utc < end else -5
        return now_utc.astimezone(timezone(timedelta(hours=off)))


def session_cutoff(data, now_utc=None):
    """Last date whose daily bar counts. `as_of_close` pins it (replays and tests)."""
    if data.get("as_of_close"):
        return date.fromisoformat(data["as_of_close"]).isoformat(), "pinned by as_of_close"
    now = new_york_now(now_utc)
    d = now.date()
    if now.hour < SESSION_CUTOFF_ET:
        d -= timedelta(days=1)
    return d.isoformat(), f"New York time {now:%Y-%m-%d %H:%M}"


class Series:
    def __init__(self, rows):
        self.d = [r[0] for r in rows]
        self.o = [r[1] for r in rows]
        self.h = [r[2] for r in rows]
        self.l = [r[3] for r in rows]
        self.c = [r[4] for r in rows]
        self.v = [r[5] for r in rows]
        self.n = len(rows)
        self._pc, self._pv = [0.0], [0.0]
        for c, v in zip(self.c, self.v):
            self._pc.append(self._pc[-1] + c)
            self._pv.append(self._pv[-1] + v)

    def sma(self, n, i):
        if i < n - 1 or i >= self.n:
            return None
        return (self._pc[i + 1] - self._pc[i + 1 - n]) / n

    def avg_vol(self, n, i):
        if i < n - 1 or i >= self.n:
            return None
        return (self._pv[i + 1] - self._pv[i + 1 - n]) / n

    def close_on_or_before(self, d):
        i = bisect.bisect_right(self.d, d) - 1
        return None if i < 0 else self.c[i]

    def index_on_or_before(self, d):
        i = bisect.bisect_right(self.d, d) - 1
        return None if i < 0 else i


# ------------------------------------------------------------------ trend template
def rs_read(s, t, idx):
    """IBD-style weighted 3/6/9/12-month performance, stock minus S&P 500, -> RS proxy."""
    if idx is None:
        return None
    parts = []
    for n, w in RS_WEIGHTS:
        if t - n < 0:
            continue
        i0, i1 = idx.close_on_or_before(s.d[t - n]), idx.close_on_or_before(s.d[t])
        if not i0 or not i1:
            continue
        parts.append((w, (s.c[t] / s.c[t - n] - 1) * 100, (i1 / i0 - 1) * 100))
    if not parts:
        return None
    tw = sum(w for w, _, _ in parts)
    stock = sum(w * a for w, a, _ in parts) / tw
    bench = sum(w * b for w, _, b in parts) / tw
    rel = stock - bench
    line = []
    for i in range(max(0, t - YEAR + 1), t + 1):
        ic = idx.close_on_or_before(s.d[i])
        if ic:
            line.append(s.c[i] / ic)
    near_high = bool(line) and line[-1] >= 0.95 * max(line)
    new_high = bool(line) and line[-1] >= max(line)
    return {"stock_pct": stock, "sp500_pct": bench, "rel_pp": rel,
            "rating": half_up(interp(rel, RS_PTS)), "horizons": len(parts),
            "rs_line_near_high": near_high, "rs_line_new_high": new_high}


def trend_template(s, t, rs):
    c = s.c[t]
    s50, s150, s200 = s.sma(50, t), s.sma(150, t), s.sma(200, t)
    s200_1m = s.sma(200, t - MONTH) if t - MONTH >= 0 else None
    w0 = max(0, t - YEAR + 1)
    lo52, hi52 = min(s.l[w0:t + 1]), max(s.h[w0:t + 1])
    months_up = 0
    if s200 is not None:
        k = 0
        while k < 5:
            a, b = s.sma(200, t - MONTH * k), s.sma(200, t - MONTH * (k + 1))
            if a is None or b is None or a <= b:
                break
            k += 1
        months_up = k

    def both(x, y):
        return None if x is None or y is None else (x and y)

    def gt(a, b):
        return None if a is None or b is None else a > b

    above_lo = (c / lo52 - 1) * 100
    off_hi = (1 - c / hi52) * 100
    rating = rs["rating"] if rs else None
    crit = [
        (1, "Price above the 150-day and 200-day MA", both(gt(c, s150), gt(c, s200)),
         f"{money(c)} vs {money(s150)} / {money(s200)}"),
        (2, "150-day MA above the 200-day MA", gt(s150, s200), f"{money(s150)} vs {money(s200)}"),
        (3, "200-day MA rising for at least 1 month", gt(s200, s200_1m),
         "n/a" if s200_1m is None else
         f"{pct_txt((s200 / s200_1m - 1) * 100)} over 1 month; rising {months_up} of the last 5 months"),
        (4, "50-day MA above the 150-day and 200-day MA", both(gt(s50, s150), gt(s50, s200)),
         f"{money(s50)}"),
        (5, "Price above the 50-day MA", gt(c, s50),
         "n/a" if s50 is None else f"{pct_txt((c / s50 - 1) * 100)} vs {money(s50)}"),
        (6, f"At least {TT_LOW_PCT:.0f}% above the 52-week low", above_lo >= TT_LOW_PCT,
         f"{pct_txt(above_lo, 0)} (low {money(lo52)})"),
        (7, f"Within {TT_HIGH_PCT:.0f}% of the 52-week high", off_hi <= TT_HIGH_PCT,
         f"{pct_txt(-off_hi, 1)} (high {money(hi52)})"),
        (8, f"RS rating {RS_MIN}+ (proxy)", None if rating is None else rating >= RS_MIN,
         "n/a (no S&P 500 data)" if rs is None else
         f"≈{rating} ({rs['rel_pp']:+.0f}pp vs S&P 500, weighted 12 mo)"),
    ]
    items = [{"n": n, "rule": rule, "pass": ok, "value": val} for n, rule, ok, val in crit]
    if s.n < YEAR:
        for it in items[5:7]:
            it["value"] += f" [only {s.n} sessions]"
    return {
        "items": items, "passed": sum(1 for it in items if it["pass"]),
        "known": sum(1 for it in items if it["pass"] is not None),
        "sma50": s50, "sma150": s150, "sma200": s200, "sma200_1m": s200_1m,
        "low52": lo52, "high52": hi52, "pct_above_low": above_lo, "pct_off_high": off_hi,
        "months_200_rising": months_up,
    }


def stage_of(s, t, tt):
    """Stage 1-4 from the moving averages (the book's Stage Analysis)."""
    c, s200, s200m = s.c[t], tt["sma200"], tt["sma200_1m"]
    ok = [it["pass"] for it in tt["items"][:3]]
    if None in ok:
        return None, "not enough history for Stage Analysis"
    if all(ok):
        return 2, "Stage 2 uptrend"
    rising = s200 > s200m
    if c < s200 and not rising:
        return 4, "Stage 4 downtrend (below a falling 200-day)"
    if not rising:
        return 1, "Stage 1 base (200-day flat or falling)"
    if c < s200:
        return 3, "Stage 3 top or breakdown (below a rising 200-day)"
    return 2.5, "not yet Stage 2 (150-day still below the 200-day or price below the 150-day)"


# --------------------------------------------------------------------------- the VCP
def analyze_base(s, end):
    """Base and volatility contraction pattern as of bar `end` (uses bars up to `end` only).

    Base high: the highest high of the last 65 weeks. Contraction highs are bars no later
    bar has exceeded (so they step down left to right). A new contraction starts at such a
    high when price rallied >= SWING_PCT into it from the current contraction's low and
    then pulled back >= SWING_PCT without undercutting that low. Anything else (a lower
    low, a small wiggle) belongs to the current contraction. The pivot is the high of the
    last contraction.
    """
    start = max(0, end - BASE_MAX_SESSIONS + 1)
    if end - start < BASE_MIN_SESSIONS:
        return None
    a = start
    for i in range(start, end + 1):
        if s.h[i] > s.h[a]:
            a = i
    if end - a < BASE_MIN_SESSIONS:
        return None  # new high within the last 3 weeks: no base yet
    rsm, run = [], -math.inf
    for i in range(end, a - 1, -1):
        if s.h[i] >= run:
            rsm.append(i)
            run = s.h[i]
    rsm.reverse()
    bounds = rsm[1:] + [end + 1]
    cons, cur = [], None

    def low_in(i0, i1):
        return min(range(i0, i1), key=lambda k: (s.l[k], k))

    for r, nxt in zip(rsm, bounds):
        lo_i = low_in(r, nxt)
        lo = s.l[lo_i]
        if cur is None:
            cur = {"hi_i": r, "hi": s.h[r], "lo_i": lo_i, "lo": lo}
            continue
        if lo < cur["lo"]:  # a lower low: still the same (deepening) contraction
            cur["lo"], cur["lo_i"] = lo, lo_i
            continue
        rally = (s.h[r] / cur["lo"] - 1) * 100
        # the pullback must happen after the high bar (a bar's own range is not a contraction)
        drop = (1 - s.l[low_in(r + 1, nxt)] / s.h[r]) * 100 if nxt - r >= 2 else 0.0
        if rally >= SWING_PCT and drop >= SWING_PCT:
            cons.append(cur)
            cur = {"hi_i": r, "hi": s.h[r], "lo_i": lo_i, "lo": lo}
    cons.append(cur)
    for k in cons:
        k["depth"] = (1 - k["lo"] / k["hi"]) * 100
    depths = [k["depth"] for k in cons]
    base_low = min(s.l[a:end + 1])
    depth = (1 - base_low / s.h[a]) * 100
    weeks = (end - a) / 5
    # Volume dry-up: the quietest 5 sessions of the last 3 weeks vs the base's average volume
    # (not the 50-day, which a long quiet stretch drags down with it).
    vbase = (s._pv[end + 1] - s._pv[a]) / (end + 1 - a)
    quiet = [s.avg_vol(5, i) for i in range(max(4, end - 10), end + 1)]
    quiet = [q for q in quiet if q is not None]
    dry = (min(quiet) / vbase) if quiet and vbase else None
    widen = [(x, y) for x, y in zip(depths, depths[1:]) if y > x + TIGHTEN_TOL_PP]
    checks = [
        ("contractions", len(cons) >= 2,
         f"{len(cons)} contraction{'s' if len(cons) != 1 else ''}"
         + ("" if len(cons) >= 2 else " (a VCP needs at least 2)")),
        ("tightening", not widen,
         "each contraction shallower than the last" if not widen else
         "contractions widen (" + ", ".join(f"{x:.1f}% → {y:.1f}%" for x, y in widen) + ")"),
        ("final_tight", depths[-1] <= FINAL_MAX_PCT,
         f"last contraction {depths[-1]:.1f}%" + ("" if depths[-1] <= FINAL_MAX_PCT
                                                 else f" is not tight (needs ≤{FINAL_MAX_PCT:.0f}%)")),
        ("depth", depth <= DEPTH_MAX_PCT,
         f"base depth {depth:.1f}%" + ("" if depth <= DEPTH_MAX_PCT
                                       else f" is too deep (max {DEPTH_MAX_PCT:.0f}%)")),
        ("volume_dryup", dry is not None and dry <= DRYUP_RATIO,
         "volume n/a" if dry is None else
         f"quietest week {dry:.2f}× the base's average volume" + ("" if dry <= DRYUP_RATIO
                                                          else f", hasn't dried up (needs ≤{DRYUP_RATIO})")),
    ]
    return {
        "end_i": end, "high_i": a, "base_high": s.h[a], "base_low": base_low, "depth_pct": depth,
        "weeks": weeks, "contractions": cons, "depths": depths, "pivot": cons[-1]["hi"],
        "pivot_i": cons[-1]["hi_i"], "final_low": cons[-1]["lo"], "final_low_i": cons[-1]["lo_i"],
        "dryup": dry, "checks": checks, "valid": all(ok for _, ok, _ in checks),
    }


def find_setup(s, t):
    """The first close above a base's pivot in the last BREAKOUT_WINDOW sessions, else today's base."""
    found = []
    for j in range(1, BREAKOUT_WINDOW + 1):
        d = t - j
        if d < BASE_MIN_SESSIONS:
            break
        b = analyze_base(s, d)
        if b and s.c[d + 1] > b["pivot"]:
            found.append((d + 1, b))
    # The earliest breakout in the window is the real one: after it, pauses in the new advance
    # can look like small bases with their own "pivots".
    valid = [x for x in found if x[1]["valid"]]
    pick = valid[-1] if valid else (found[-1] if found else None)
    if pick:
        bi, b = pick
        p = b["pivot"]
        confirm = None
        for i in range(bi, t + 1):
            av = s.avg_vol(50, i - 1)
            if s.c[i] > p and av and s.v[i] >= BREAKOUT_VOL * av:
                confirm = i
                break
        av_b = s.avg_vol(50, bi - 1)
        return {"state": "breakout", "base": b, "breakout_i": bi, "pivot": p,
                "pct_vs_pivot": (s.c[t] / p - 1) * 100, "confirmed_i": confirm,
                "breakout_vol_ratio": (s.v[bi] / av_b) if av_b else None,
                "sessions_since": t - bi}
    b = analyze_base(s, t)
    if b:
        return {"state": "base", "base": b, "pivot": b["pivot"],
                "pct_vs_pivot": (s.c[t] / b["pivot"] - 1) * 100}
    return {"state": "none", "base": None, "pivot": None, "pct_vs_pivot": None}


# --------------------------------------------------------------------- fundamentals
def fundamentals(f, is_etf):
    """SEPA's earnings test on the last three reported quarters (newest first)."""
    if is_etf:
        return {"grade": "N/A", "ok": True, "flags": [], "fails": [], "unknown": [],
                "line": "Fundamentals: n/a for an ETF"}
    f = f or {}
    qs = (f.get("quarters") or [])[:4]
    flags = []
    if not qs:
        return {"grade": "MISSING", "ok": None, "flags": ["fundamentals: no quarterly data"],
                "fails": [], "unknown": ["no quarterly data"],
                "line": "Fundamentals: not checked (no quarterly data)"}
    eps_g = [yoy(q.get("eps"), q.get("eps_ya")) for q in qs]
    op_g = [yoy(q.get("op_inc"), q.get("op_inc_ya")) for q in qs]
    rev_g = [yoy(q.get("rev"), q.get("rev_ya")) for q in qs]
    marg = [ratio(q.get("net_inc"), q.get("rev")) for q in qs]
    marg_ya = [ratio(q.get("net_inc_ya"), q.get("rev_ya")) for q in qs]
    distorted = eps_g[0] is not None and op_g[0] is not None and abs(eps_g[0] - op_g[0]) > GAAP_GAP_PP
    if distorted:
        flags.append(f"fundamentals: GAAP EPS growth ({eps_g[0]:.0f}%) and operating-income growth "
                     f"({op_g[0]:.0f}%) differ by >{GAAP_GAP_PP:.0f}pp; earnings growth measured on "
                     "operating income (one-off gain or charge in EPS)")
    g = op_g if distorted else eps_g
    q0 = qs[0]
    req = []
    eps0 = q0.get("eps")
    if eps0 is None:
        req.append((None, "latest EPS missing"))
    elif eps0 <= 0 and not distorted:
        req.append((False, f"latest quarter is a loss (EPS {eps0:.2f})"))
    elif g[0] is None:
        flags.append("fundamentals: year-ago quarter was a loss, growth undefined (turnaround)")
        req.append((True, "turnaround: profit vs a year-ago loss"))
    else:
        req.append((g[0] >= EPS_MIN_PCT, f"EPS {g[0]:+.0f}%" + ("" if g[0] >= EPS_MIN_PCT
                                                              else f" (needs +{EPS_MIN_PCT:.0f}%)")))
    if rev_g[0] is None:
        req.append((None, "sales growth unknown"))
    else:
        req.append((rev_g[0] > 0, f"sales {rev_g[0]:+.0f}%" + ("" if rev_g[0] > 0
                                                            else " (earnings growth without sales growth)")))
    ok_vals = [ok for ok, _ in req]
    ok = False if False in ok_vals else (None if None in ok_vals else True)

    def up(xs, n):
        vals = xs[:n]
        return len(vals) == n and None not in vals and all(a > b for a, b in zip(vals, vals[1:]))

    extras = {
        "eps_accelerating": up(g, 2),
        "sales_accelerating": up(rev_g, 2),
        "margin_expanding": marg[0] is not None and marg_ya[0] is not None and marg[0] > marg_ya[0],
        "code33": up(g, 3) and up(rev_g, 3) and up(marg, 3),
    }
    sp = f.get("surprise") or {}
    surprise = None
    ea, ee = sp.get("eps_actual"), sp.get("eps_estimate")
    if ea is not None and ee not in (None, 0):
        surprise = (ea - ee) / abs(ee) * 100
        extras["positive_surprise"] = ea >= ee
    grade = "FAIL" if ok is False else ("INCOMPLETE" if ok is None else "PASS")
    lab = q0.get("label") or "latest quarter"
    parts = [f"Fundamentals: {grade}", lab]
    if g[0] is not None:
        prior = f", prior {g[1]:+.0f}%" if len(g) > 1 and g[1] is not None else ""
        parts.append(f"{'op. income' if distorted else 'EPS'} {g[0]:+.0f}%{prior}"
                     + (" (accelerating)" if extras["eps_accelerating"] else ""))
    elif eps0 is not None:
        parts.append(f"EPS {eps0:.2f} vs {q0.get('eps_ya')}")
    if rev_g[0] is not None:
        prior = f", prior {rev_g[1]:+.0f}%" if len(rev_g) > 1 and rev_g[1] is not None else ""
        parts.append(f"sales {rev_g[0]:+.0f}%{prior}" + (" (accelerating)" if extras["sales_accelerating"] else ""))
    if marg[0] is not None and marg_ya[0] is not None:
        parts.append(f"net margin {marg[0] * 100:.1f}% vs {marg_ya[0] * 100:.1f}% a year ago")
    if surprise is not None:
        parts.append(f"EPS surprise {surprise:+.1f}%")
    parts.append("Code 33 ✓" if extras["code33"] else "Code 33 ✗")
    fails = [txt for o, txt in req if o is False]
    unknown = [txt for o, txt in req if o is None]
    return {"grade": grade, "ok": ok, "required": [{"pass": o, "text": x} for o, x in req],
            "extras": extras, "surprise_pct": r2(surprise), "eps_growth": [r2(x) for x in g],
            "sales_growth": [r2(x) for x in rev_g], "basis": "op_inc" if distorted else "eps",
            "fails": fails, "unknown": unknown, "flags": flags, "line": " · ".join(parts)}


# ---------------------------------------------------------------------------- market
def market_read(idx, last_date):
    if idx is None:
        return {"regime": None, "line": "Market: no S&P 500 data, market rule not applied"}
    i = idx.index_on_or_before(last_date)
    if i is None or i < MIN_BARS - 1:
        return {"regime": None, "line": "Market: not enough S&P 500 history, market rule not applied"}
    c, s50, s200, s200m = idx.c[i], idx.sma(50, i), idx.sma(200, i), idx.sma(200, i - MONTH)
    rising = s200 > s200m
    where = (f"S&P 500 {c:,.0f}, {pct_txt((c / s50 - 1) * 100)} vs its 50-day, "
             f"{pct_txt((c / s200 - 1) * 100)} vs its {'rising' if rising else 'falling'} 200-day")
    if c < s200 and not rising:
        regime, what = "downtrend", "Stage 4 downtrend: no new buys"
    elif c > s50 and c > s200 and rising:
        regime, what = "uptrend", "uptrend: normal position size"
    else:
        regime, what = "correction", "under pressure: half position size"
    return {"regime": regime, "date": idx.d[i], "close": c, "sma50": s50, "sma200": s200,
            "sma200_rising": rising, "line": f"Market: {what} ({where})"}


# --------------------------------------------------------------------- sell signals
def advance_start(s, t):
    w0 = max(0, t - YEAR + 1)
    return min(range(w0, t + 1), key=lambda i: (s.c[i], i))


def weakness_signals(s, t, setup):
    """Stage 3 warnings (selling into weakness)."""
    out = []
    st = advance_start(s, t)
    if t - st >= 30:
        days = [(s.c[i] / s.c[i - 1] - 1) * 100 for i in range(st + 1, t + 1)]
        k = min(range(len(days)), key=lambda j: (days[j], j))
        i = st + 1 + k
        if i >= t - 9 and days[k] <= -3:
            out.append(f"largest one-day drop since the advance began ({days[k]:.1f}% on {s.d[i]})")
        else:
            wk = [(s.c[i] / s.c[i - 5] - 1) * 100 for i in range(st + 5, t + 1)]
            if wk:
                k = min(range(len(wk)), key=lambda j: (wk[j], j))
                i = st + 5 + k
                if i >= t - 9 and wk[k] <= -5:
                    out.append(f"largest one-week drop since the advance began ({wk[k]:.1f}% to {s.d[i]})")
    s50t = s.sma(50, t)
    if s50t is not None and s.c[t] < s50t:
        for i in range(max(1, t - 4), t + 1):
            m, av = s.sma(50, i), s.avg_vol(50, i - 1)
            if m and av and s.c[i] < m and s.c[i] < s.c[i - 1] and s.v[i] >= HEAVY_VOL * av:
                out.append(f"closed below the 50-day on heavy volume ({s.v[i] / av:.1f}× average, {s.d[i]})")
                break
    if setup["state"] == "breakout" and setup["base"]["valid"] and s.c[t] < setup["pivot"]:
        out.append(f"failed breakout: back below the {money(setup['pivot'])} pivot "
                   f"{setup['sessions_since']} sessions after breaking out")
    return out


def climax_signals(s, t, tt):
    """Climax-top signs (selling into strength). Only counts in an uptrend."""
    out, key = [], False
    s50, s200 = tt["sma50"], tt["sma200"]
    if s50 is None or s.c[t] <= s50:
        return out, key
    w = s.c[max(0, t - CLIMAX_RUN_SESSIONS):t + 1]
    run = (s.c[t] / min(w) - 1) * 100
    if run >= CLIMAX_RUN_PCT:
        out.append(f"up {run:.0f}% in {CLIMAX_RUN_SESSIONS} sessions or less")
        key = True
    if s200 and (s.c[t] / s200 - 1) * 100 >= CLIMAX_EXT_200:
        out.append(f"{(s.c[t] / s200 - 1) * 100:.0f}% above the 200-day")
        key = True
    st = advance_start(s, t)
    if t - st >= 30:
        days = [(s.c[i] / s.c[i - 1] - 1) * 100 for i in range(st + 1, t + 1)]
        k = max(range(len(days)), key=lambda j: (days[j], -j))
        if st + 1 + k >= t - 9 and days[k] >= 4:
            out.append(f"largest one-day gain of the advance ({days[k]:+.1f}% on {s.d[st + 1 + k]})")
    ups = sum(1 for i in range(t - 9, t + 1) if i >= 1 and s.c[i] > s.c[i - 1])
    if ups >= CLIMAX_UP_DAYS:
        out.append(f"{ups} of the last 10 sessions closed up")
    for i in range(max(1, t - 4), t + 1):
        if s.l[i] > s.h[i - 1] * 1.01:
            out.append(f"gap up on {s.d[i]} ({(s.l[i] / s.h[i - 1] - 1) * 100:.1f}% above the prior high)")
            break
    return out, key


# --------------------------------------------------------------------------- verdicts
def entry_plan(s, t, setup, entry, regime):
    b = setup["base"]
    stop = max(b["final_low"], entry * (1 - MAX_STOP_PCT / 100))
    stop_pct = (1 - stop / entry) * 100
    size = min(RISK_PCT / stop_pct * 100, MAX_POSITION_PCT) if stop_pct > 0 else None
    half = regime == "correction"
    if size is not None and half:
        size /= 2
    capped = stop > b["final_low"]
    txt = (f"stop {money(stop)} ({-stop_pct:.1f}%"
           + (f", the {MAX_STOP_PCT:.0f}% maximum; the last contraction low {money(b['final_low'])} is further)"
              if capped else ", under the last contraction low)"))
    if size is not None:
        txt += (f"; size ≈ {size:.0f}% of the account (risks {RISK_PCT}% of it"
                + ("; halved, market under pressure" if half else "") + ")")
    txt += f"; once up {BREAKEVEN_R * stop_pct:.0f}% ({BREAKEVEN_R:.0f}× the risk), raise the stop to breakeven"
    return {"entry": entry, "stop": stop, "stop_pct": stop_pct, "size_pct": size, "half_size": half,
            "text": txt}


def new_money(s, t, tt, stage, setup, fund, mkt, is_etf, earn_days):
    st_n, st_label = stage
    items = tt["items"]
    fails = [it for it in items if it["pass"] is False]
    unknown = [it for it in items if it["pass"] is None]
    plan = None
    if st_n is None:
        return "WAIT", f"only {s.n} sessions of history; the Trend Template needs {MIN_BARS}", plan
    if st_n == 4:
        return "AVOID", f"{st_label}; the book never buys Stage 4", plan
    if not all(it["pass"] for it in items[:3]):
        miss = "; ".join(f"#{it['n']} {it['rule'].lower()}" for it in items[:3] if not it["pass"])
        return "AVOID", f"not in a Stage 2 uptrend ({st_label}): fails {miss}", plan
    if not is_etf and fund["ok"] is False:
        return "AVOID", "earnings don't meet SEPA: " + "; ".join(fund["fails"]), plan
    if fails or unknown:
        bits = [f"#{it['n']} {it['rule'].lower()} ({it['value']})" for it in fails + unknown]
        return "WAIT", f"Trend Template {tt['passed']}/8, still needs " + "; ".join(bits), plan
    if not is_etf and fund["ok"] is None:
        return "WAIT", "Trend Template 8/8, but earnings not checked (" + "; ".join(fund["unknown"] or ["no data"]) + ")", plan
    if mkt["regime"] == "downtrend":
        return "WAIT", "Trend Template 8/8, but the S&P 500 is in a Stage 4 downtrend: no new buys", plan
    soon = earn_days is not None and 0 <= earn_days <= EARNINGS_NEAR_DAYS
    earn = (f"; earnings in {earn_days} days: a gap can jump the stop, consider half size or waiting"
            if soon else "")
    p = setup["pivot"]
    b = setup["base"]
    if setup["state"] == "breakout":
        why_not = "; ".join(txt for _, ok, txt in b["checks"] if not ok)
        if not b["valid"]:
            return ("WAIT", f"broke out on {s.d[setup['breakout_i']]} above {money(p)}, but the base wasn't a "
                    f"valid VCP ({why_not}); wait for a proper base", plan)
        lo, hi = p, p * (1 + BUY_RANGE_PCT / 100)
        if s.c[t] < p:
            return ("WAIT", f"breakout above {money(p)} on {s.d[setup['breakout_i']]} failed (close back below "
                    "the pivot); wait for it to reclaim the pivot on volume or build a new base", plan)
        if s.c[t] > hi:
            return ("WAIT", f"extended {setup['pct_vs_pivot']:.1f}% above the {money(p)} pivot (buy range "
                    f"{money(lo)}–{money(hi)}); don't chase, wait for a new base or a pullback into the range", plan)
        if setup["confirmed_i"] is None:
            need = s.avg_vol(50, t) * BREAKOUT_VOL
            return ("WAIT", f"broke out above {money(p)} but on light volume ({setup['breakout_vol_ratio']:.1f}× "
                    f"average); buy on a close in {money(lo)}–{money(hi)} with volume ≥ {vol_txt(need)} "
                    f"({BREAKOUT_VOL}× average)", plan)
        plan = entry_plan(s, t, setup, s.c[t], mkt["regime"])
        return ("BUY", f"VCP breakout above {money(p)} on {s.d[setup['confirmed_i']]} with volume; "
                f"{setup['pct_vs_pivot']:.1f}% above the pivot, inside the buy range {money(lo)}–{money(hi)}; "
                + plan["text"] + earn, plan)
    if setup["state"] == "base":
        if not b["valid"]:
            why_not = "; ".join(txt for _, ok, txt in b["checks"] if not ok)
            return ("WAIT", f"basing {b['weeks']:.0f} weeks below {money(p)}, not a valid VCP yet "
                    f"({why_not})", plan)
        plan = entry_plan(s, t, setup, p, mkt["regime"])
        need = s.avg_vol(50, t) * BREAKOUT_VOL
        return ("BUY ON BREAKOUT", f"buy only if it trades above the {money(p)} pivot "
                f"({(p / s.c[t] - 1) * 100:.1f}% above the last close) on volume ≥ {vol_txt(need)} ({BREAKOUT_VOL}× average); buy range {money(p)}–"
                f"{money(p * (1 + BUY_RANGE_PCT / 100))}; " + plan["text"] + earn, plan)
    return ("WAIT", "no base to buy from: it set a new high within the last 3 weeks and there was no VCP "
            "breakout in the last 10 sessions; wait for a base of 3+ weeks and a new pivot", plan)


def holder(s, t, tt, stage, setup, pos):
    """Verdict for someone who owns it, with or without their entry price."""
    st_n, st_label = stage
    entry = pos.get("entry_price")
    stop = pos.get("stop")
    reasons_sell, warns, levels = [], [], []
    peak = None
    if entry:
        floor = entry * (1 - MAX_STOP_PCT / 100)
        if stop and stop < floor:
            levels.append(f"your {money(stop)} stop is wider than the {MAX_STOP_PCT:.0f}% maximum, "
                          f"using {money(floor)}")
        stop = max(stop or floor, floor)
        risk = entry - stop
        if pos.get("entry_date"):
            i0 = bisect.bisect_left(s.d, str(pos["entry_date"])[:10])
            if i0 < s.n:
                peak = max(s.c[i0:t + 1])
        if peak is not None and risk > 0 and peak >= entry + BREAKEVEN_R * risk and stop < entry:
            stop = entry
            levels.append(f"stop raised to breakeven {money(entry)} (it was up "
                          f"{(peak / entry - 1) * 100:.0f}%, more than {BREAKEVEN_R:.0f}× the risk)")
        gain = (s.c[t] / entry - 1) * 100
        if s.c[t] <= stop:
            if stop >= entry and peak is not None:
                reasons_sell.append(f"a gain of {(peak / entry - 1) * 100:.0f}% has turned into "
                                    f"{gain:+.1f}%; never let a {BREAKEVEN_R:.0f}R gain become a loss")
            else:
                reasons_sell.append(f"stop hit: closed at or below {money(stop)}, {gain:+.1f}% vs your "
                                    f"{money(entry)} entry (max loss {MAX_STOP_PCT:.0f}%)")
        else:
            levels.append(f"your stop {money(stop)} ({pct_txt((stop / s.c[t] - 1) * 100)} from here)")
    if st_n == 4:
        reasons_sell.append(st_label)
    elif tt["sma200"] is not None and s.c[t] < tt["sma200"]:
        reasons_sell.append(f"below the 200-day MA ({money(tt['sma200'])}): the Stage 2 uptrend is broken")
    weak = weakness_signals(s, t, setup)
    if len(weak) >= 2:
        reasons_sell.append("Stage 3 warnings: " + "; ".join(weak))
    if reasons_sell:
        return "SELL", "; ".join(reasons_sell), weak, []
    climax, key = climax_signals(s, t, tt)
    in_profit = entry is None or s.c[t] > entry
    if key and len(climax) >= 2 and in_profit:
        return ("SELL INTO STRENGTH", "climax-run signs: " + "; ".join(climax)
                + "; sell some or all while buyers are eager", weak, climax)
    warns += weak
    if key:  # an acceleration or extreme extension without a second sign yet
        warns.append("climax sign: " + "; ".join(climax))
    tt_fail = [f"#{it['n']} {it['rule'].lower()}" for it in tt["items"] if it["pass"] is False]
    if tt_fail:
        warns.append("Trend Template fails " + ", ".join(tt_fail))
    s50 = tt["sma50"]
    trend_line = f"trend line: 50-day {money(s50)}; a heavy-volume close below it is a sell signal"
    if not entry:
        levels.append(f"no entry price given: sell if it closes {MAX_STOP_PCT:.0f}% or more below your cost")
    if warns:
        return "HOLD, TIGHTEN STOP", "; ".join(warns + levels + [trend_line]), weak, climax
    return "HOLD", "; ".join(["Trend Template intact, no sell signals"] + levels + [trend_line]), weak, climax


def add_more(nm, nm_note, hv, s, t, pos, pivot):
    entry = pos.get("entry_price")
    if entry and s.c[t] < entry:
        return "DON'T ADD", (f"you're down {(1 - s.c[t] / entry) * 100:.1f}% from {money(entry)}; "
                             "never average down, add only to a position showing a profit")
    if hv != "HOLD":
        return "DON'T ADD", f"the holder verdict is {hv}; add only to a position that's acting right"
    tail = "" if entry else "; only if your position shows a profit"
    if nm == "BUY":
        return "ADD", ("new low-risk entry point (" + nm_note.split(';')[0]
                       + "); add a smaller amount than your first buy" + tail)
    if nm == "BUY ON BREAKOUT":
        return "ADD ON BREAKOUT", (f"add only on a breakout above the {money(pivot)} pivot on volume, "
                                   "a smaller amount than your first buy" + tail)
    return "DON'T ADD", f"no low-risk point to add at ({nm} for new money): " + nm_note


# ------------------------------------------------------------------------------ main
def fingerprint(rows, idx_rows, t_entry):
    payload = {"bars": rows, "index": idx_rows,
               "fundamentals": t_entry.get("fundamentals") or None,
               "position": {k: v for k, v in (t_entry.get("position") or {}).items() if v is not None},
               "type": t_entry.get("type", "stock"), "next_earnings": t_entry.get("next_earnings") or None,
               "rules": RULES_VERSION}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:10]


def trend_table(tt):
    lines = ["| # | Trend Template | Now | |", "|---|---|---|---|"]
    for it in tt["items"]:
        mark = "✓" if it["pass"] else ("?" if it["pass"] is None else "✗")
        lines.append(f"| {it['n']} | {it['rule']} | {it['value']} | {mark} |")
    return "\n".join(lines)


def setup_line(s, setup):
    b = setup["base"]
    if setup["state"] == "none":
        return "Setup: no base (new high within the last 3 weeks)"
    shown = " → ".join(f"{x:.1f}%" for x in b["depths"][:6]) + (" → …" if len(b["depths"]) > 6 else "")
    head = (f"Setup: {len(b['depths'])} contraction{'s' if len(b['depths']) != 1 else ''} {shown} over "
            f"{b['weeks']:.0f} wks from the {money(b['base_high'])} high (depth {b['depth_pct']:.1f}%)")
    vol = "" if b["dryup"] is None else f" · quietest week {b['dryup']:.2f}× avg volume"
    bad = [txt for _, ok, txt in b["checks"] if not ok]
    verdict = " · VCP ✓" if b["valid"] else " · not a VCP: " + "; ".join(bad)
    if setup["state"] == "breakout":
        vr = setup["breakout_vol_ratio"]
        return (head + vol + verdict + f" · broke out {s.d[setup['breakout_i']]} above the "
                f"{money(setup['pivot'])} pivot" + ("" if vr is None else f" on {vr:.1f}× volume")
                + f", now {pct_txt(setup['pct_vs_pivot'])} vs pivot")
    over = ""
    if b["pivot"] < 0.9 * b["base_high"]:
        over = f" · overhead supply up to {money(b['base_high'])}"
    return head + vol + verdict + f" · pivot {money(b['pivot'])} ({(b['pivot'] / s.c[s.n - 1] - 1) * 100:.1f}% above the close)" + over


def trim_index(idx_rows, s, t):
    """S&P 500 rows from the close the 12-month RS reads to the stock's last session.

    Like the stock's own trim, this keeps results independent of how much history was fetched.
    """
    if not idx_rows:
        return None, None
    first = s.d[max(0, t - YEAR)]
    dates = [r[0] for r in idx_rows]
    i0 = max(0, bisect.bisect_right(dates, first) - 1)
    i1 = bisect.bisect_right(dates, s.d[t])
    rows = idx_rows[i0:i1]
    return (Series(rows), rows) if rows else (None, None)


def evaluate(entry, idx_all, cutoff, intent, idx_flags=()):
    tk = entry.get("ticker", "?")
    is_etf = entry.get("type", "stock") == "etf"
    rows, flags = parse_bars(entry.get("bars"), f"{tk} bars")
    flags += list(idx_flags)
    dropped = [r for r in rows if r[0] > cutoff]
    rows = [r for r in rows if r[0] <= cutoff]
    if dropped:
        flags.append(f"ignored {len(dropped)} bar(s) after the last completed session {cutoff} "
                     f"({', '.join(r[0] for r in dropped[:3])})")
    rows = rows[-KEEP_BARS:]
    if len(rows) < 60:
        raise ValueError(f"{tk}: only {len(rows)} completed daily bars; need at least 60 (ideally 380)")
    if len(rows) < YEAR + 1:
        flags.append(f"only {len(rows)} sessions of history; 52-week and RS figures use what's there")
    s = Series(rows)
    t = s.n - 1
    idx, idx_rows = trim_index(idx_all, s, t)
    rs = rs_read(s, t, idx)
    if rs and rs["horizons"] < len(RS_WEIGHTS):
        flags.append(f"RS uses {rs['horizons']} of 4 horizons (short history)")
    tt = trend_template(s, t, rs)
    stage = stage_of(s, t, tt)
    setup = find_setup(s, t)
    fund = fundamentals(entry.get("fundamentals"), is_etf)
    flags += fund["flags"]
    mkt = market_read(idx, s.d[t])
    if idx is not None and mkt.get("date") and mkt["date"] != s.d[t]:
        flags.append(f"S&P 500 data ends {mkt['date']}, stock data {s.d[t]}")
    earn_days = None
    if entry.get("next_earnings"):
        try:
            earn_days = (date.fromisoformat(str(entry["next_earnings"])[:10]) - date.fromisoformat(s.d[t])).days
        except ValueError:
            flags.append(f"next_earnings {entry['next_earnings']!r} is not YYYY-MM-DD")
    if stage[0] == 2 and setup["base"] and setup["base"]["depth_pct"] > DEPTH_IDEAL_PCT:
        flags.append(f"base depth {setup['base']['depth_pct']:.0f}% is deeper than the usual "
                     f"{DEPTH_IDEAL_PCT:.0f}% (acceptable after a market correction)")
    pos = entry.get("position") or {}

    nm, nm_note, plan = new_money(s, t, tt, stage, setup, fund, mkt, is_etf, earn_days)
    hv, hv_note, weak, climax = holder(s, t, tt, stage, setup, pos)
    av, av_note = add_more(nm, nm_note, hv, s, t, pos, setup["pivot"])

    fp = fingerprint(rows, idx_rows, entry)
    main = {"buy": nm, "sell": hv, "add": av}.get(intent, nm)
    q = QUESTIONS.get(intent, QUESTIONS["buy"])
    head = (f"**{tk}: {main}** ({q}) · {money(s.c[t])} at the {s.d[t]} close · "
            f"{stage[1]} · Trend Template {tt['passed']}/8")
    v_lines = {
        "buy": f"Can I buy? **{nm}**. {cap(nm_note)}",
        "sell": f"Should I sell (if you hold)? **{hv}**. {cap(hv_note)}",
        "add": f"Should I buy more? **{av}**. {cap(av_note)}",
    }
    order = [intent] + [k for k in ("buy", "sell", "add") if k != intent] if intent in v_lines else ["buy", "sell", "add"]
    rs_line = ""
    if rs:
        rs_line = (f"RS ≈{rs['rating']} (proxy): weighted 12-month performance {rs['stock_pct']:+.0f}% vs "
                   f"S&P 500 {rs['sp500_pct']:+.0f}% ({rs['rel_pp']:+.0f}pp)"
                   + (" · RS line at a new high" if rs["rs_line_new_high"] else
                      " · RS line near its high" if rs["rs_line_near_high"] else ""))
    sig = []
    if weak:
        sig.append("weakness: " + "; ".join(weak))
    if climax:
        sig.append("climax: " + "; ".join(climax))
    text = {
        "headline": head,
        "verdict_lines": [v_lines[k] for k in order],
        "trend_table_md": trend_table(tt),
        "rs_line": rs_line or None,
        "setup_line": setup_line(s, setup),
        "fundamentals_line": fund["line"],
        "market_line": mkt["line"],
        "signals_line": "Sell signals: " + (" | ".join(sig) if sig else "none"),
        "earnings_line": (f"Next earnings {entry['next_earnings']} ({earn_days} days)"
                          if earn_days is not None and earn_days >= 0 else None),
        "data_line": (f"Data: {s.n} sessions through the {s.d[t]} close · fingerprint {fp} · rules {RULES_VERSION}"),
        "flags": flags,
    }
    b = setup["base"]
    return {
        "ticker": tk, "type": "etf" if is_etf else "stock", "as_of_close": s.d[t], "close": s.c[t],
        "intent": intent if intent in v_lines else "buy",
        "verdicts": {"buy": {"verdict": nm, "note": nm_note, "plan": plan},
                     "sell": {"verdict": hv, "note": hv_note},
                     "add": {"verdict": av, "note": av_note}},
        "stage": {"stage": stage[0], "label": stage[1]},
        "trend_template": {"passed": tt["passed"], "items": tt["items"],
                           "sma50": r2(tt["sma50"]), "sma150": r2(tt["sma150"]), "sma200": r2(tt["sma200"]),
                           "low52": tt["low52"], "high52": tt["high52"],
                           "months_200_rising": tt["months_200_rising"]},
        "rs": None if rs is None else {k: (r2(v) if isinstance(v, float) else v) for k, v in rs.items()},
        "setup": {"state": setup["state"], "pivot": r2(setup["pivot"]),
                  "pct_vs_pivot": r2(setup["pct_vs_pivot"]),
                  "breakout_date": s.d[setup["breakout_i"]] if setup["state"] == "breakout" else None,
                  "base": None if b is None else {
                      "valid": b["valid"], "high": b["base_high"], "high_date": s.d[b["high_i"]],
                      "depth_pct": r2(b["depth_pct"]), "weeks": r2(b["weeks"]),
                      "contractions": [{"high": k["hi"], "high_date": s.d[k["hi_i"]], "low": k["lo"],
                                        "low_date": s.d[k["lo_i"]], "depth_pct": r2(k["depth"])}
                                       for k in b["contractions"]],
                      "final_low": b["final_low"], "volume_dryup": r2(b["dryup"]),
                      "checks": [{"check": n, "pass": ok, "text": txt} for n, ok, txt in b["checks"]]}},
        "fundamentals": {k: v for k, v in fund.items() if k not in ("line", "flags")},
        "market": {k: (r2(v) if isinstance(v, float) else v) for k, v in mkt.items() if k != "line"},
        "signals": {"weakness": weak, "climax": climax},
        "earnings_in_days": earn_days,
        "fingerprint": fp,
        "text": text,
    }


def run(data, now_utc=None):
    cutoff, why = session_cutoff(data, now_utc)
    intent = (data.get("intent") or "buy").lower()
    idx_rows, iflags = None, []
    ix = data.get("index")
    if ix and ix.get("bars"):
        idx_rows, iflags = parse_bars(ix["bars"], "S&P 500 bars")
        idx_rows = [r for r in idx_rows if r[0] <= cutoff] or None
    tickers = data.get("tickers")
    if tickers is None:
        tickers = [{k: v for k, v in data.items() if k not in ("index", "intent", "as_of_close")}]
    if idx_rows is None:
        iflags = iflags + ["no S&P 500 bars: RS (Trend Template #8) and the market rule can't be checked"]
    results = [evaluate(t, idx_rows, cutoff, intent, iflags) for t in tickers]
    for r in results:
        r["session_cutoff"] = {"date": cutoff, "basis": why}
    return results


def main(argv):
    src = open(argv[1]) if len(argv) > 1 else sys.stdin
    with src:
        data = json.load(src)
    json.dump(run(data), sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main(sys.argv)
