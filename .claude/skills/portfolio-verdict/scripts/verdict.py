#!/usr/bin/env python3
"""Deterministic verdicts for the portfolio-verdict skill.

The model gathers market, health, ETF and stock data plus the portfolio file (schema:
example_input.json); this script turns them into:

- one of five verdicts for the period (from the S&P 500 and Nasdaq weekly charts) and for
  every holding, with the levels that would change them;
- each core ETF's entry read: where it sits on its own chart, its buy zone, and what
  followed similar weeks in 2000-2023 (references/entry_stats.json);
- a market-health panel (trend, participation, volatility, credit, yield curve, scored;
  valuation, sentiment and sector leadership as context);
- an optional dollar plan;
- a versioned JSON document for dashboards, plus markdown for chat.

Stock and ETF reads come from the canslim scorer (../../canslim/scripts/score.py), so both
skills share one weekly-stage, market-gate, thesis and holder rulebook. Same input -> same
output. Stdlib only.

Usage:
    python3 verdict.py input.json                  # JSON to stdout (or pipe JSON on stdin)
    python3 verdict.py input.json --out DIR        # also write DIR/latest.json and
                                                   # upsert DIR/history.jsonl (one line per as_of)
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CANSLIM_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "canslim", "scripts"))
STATS_PATH = os.path.normpath(os.path.join(HERE, "..", "references", "entry_stats.json"))
sys.path.insert(0, CANSLIM_DIR)
try:
    import score as canslim  # noqa: E402
except ImportError:  # pragma: no cover
    sys.exit(f"portfolio-verdict needs the canslim skill next to it: expected {CANSLIM_DIR}/score.py")

SCHEMA_VERSION = 2
interp = canslim.interp

# ----------------------------------------------------------------------------- scale
# Worst -> best. "Avoid" is "Sell" for a ticker you don't own.
VERDICTS = ["Sell", "Pause", "Exercise Caution", "Buy", "Buy More"]
RANK = {v: i for i, v in enumerate(VERDICTS)}
RANK["Avoid"] = RANK["Sell"]

# Share of this period's contribution that goes in (the rest goes to the cash reserve),
# and share of the reserve that is deployed, per market verdict.
CONTRIB = {"Buy More": 1.0, "Buy": 1.0, "Exercise Caution": 0.5, "Pause": 0.0}
DEPLOY = {"pullback": 1.0, "repair": 0.5, "Buy": 1.0, "Exercise Caution": 0.0, "Pause": 0.0}

# ------------------------------------------------------------------------ thresholds
GATE = ("^GSPC", "^IXIC")  # the verdict uses these two only; anything else is health context
PULLBACK_PCT = 5.0   # S&P 500 at least this far below its 52-wk high in a confirmed uptrend
BEAR_PCT = 20.0      # an index this far below its 52-wk high is in a bear market
BUY_ZONE = (5.0, 10.0)  # a fund's own pullback band, % off its 52-wk high, in a confirmed uptrend
DEFAULTS = {
    "satellite_target_pct": 20,  # stocks + non-broad ETFs, % of the portfolio
    "band_pp": 5,                # drift allowed over a target before new money stops
    "max_position_pct": 5,       # satellite holding: no adds above this weight
    "trim_position_pct": 8,      # satellite holding: trim back to max_position_pct above this
}
BROAD_HINT = ("core = a fund tracking a broad US index or a broad style/factor slice of one "
              "(S&P 500, total market, Nasdaq-100, large-cap growth, S&P 500 momentum)")

# ------------------------------------------------------------------------ entry state
# Where a fund (or index) sits on its own weekly chart, in the buckets that
# references/entry_stats.json holds 2000-2023 forward returns for. Bands are % below the
# 52-wk high.
ENTRY_LABELS = {
    "up_lt5": "Uptrend, within 5% of the high",
    "up_5_10": "Uptrend, 5-10% pullback (buy zone)",
    "up_ge10": "Uptrend on paper, but 10%+ off the high",
    "repair": "Repair: back above a still-falling 40-wk",
    "test_lt5": "Testing the 40-wk, within 5% of the high",
    "test_5_10": "Testing the 40-wk, 5-10% off the high",
    "test_10_20": "At or below the 40-wk, 10-20% off the high",
    "test_ge20": "Below the 40-wk, 20%+ off the high (bear territory)",
    "down_lt10": "Downtrend (Stage 4), within 10% of the high",
    "down_10_20": "Downtrend (Stage 4), 10-20% off the high",
    "down_ge20": "Downtrend (Stage 4), 20%+ off the high",
}

# ---------------------------------------------------------------------- market health
# Scored categories (weights) and the curves that turn a reading into 0-100. Thresholds are
# practitioner conventions, not backtested: the health score is context and never changes a
# verdict (see references/methodology.md).
HEALTH_WEIGHTS = {"trend": 40, "participation": 20, "volatility": 15, "credit": 15, "curve": 10}
HEALTH_NAMES = {"trend": "Trend", "participation": "Participation", "volatility": "Volatility",
                "credit": "Credit", "curve": "Yield curve", "valuation": "Valuation",
                "sentiment": "Sentiment", "leadership": "Leadership"}
BREADTH_PTS = [(20, 0), (40, 30), (50, 50), (60, 70), (75, 100)]      # % of S&P 500 above 200-day
EQUAL_WEIGHT_PTS = [(-8, 0), (-5, 30), (-2, 70), (0, 90), (2, 100)]  # RSP minus SPY, 3M, pp
VIX_PTS = [(12, 100), (16, 85), (20, 60), (25, 35), (30, 15), (40, 0)]
HY_OAS_PTS = [(3.0, 100), (4.0, 70), (5.0, 40), (6.0, 15), (8.0, 0)]  # high-yield spread, %
HY_WIDEN_PTS = [(0.25, 0), (0.5, -15), (1.0, -30)]                   # 3-month change, pp
CURVE_PTS = [(-1.0, 10), (-0.5, 25), (0.0, 50), (0.25, 70), (1.0, 100)]  # 10Y minus 3M (or 2Y)
OFFENSIVE = ("XLK", "XLY", "XLC", "XLF", "XLI")
DEFENSIVE = ("XLP", "XLU", "XLV", "XLRE")


def health_label(s):
    return None if s is None else "Healthy" if s >= 70 else "Mixed" if s >= 50 else "Weak" if s >= 30 else "Stressed"


def status_of(s):
    return None if s is None else "good" if s >= 67 else "neutral" if s >= 34 else "weak"


# --------------------------------------------------------------------------- helpers
def num(x, d=0):
    return "n/a" if x is None else f"{x:,.{d}f}"


def money(x):
    return "n/a" if x is None else f"${x:,.2f}"


def dollars(x):
    return f"${x:,.0f}"


def signed(x, d=1, unit="%"):
    return "n/a" if x is None else f"{x:+.{d}f}{unit}"


def cap_first(s):
    return s[:1].upper() + s[1:] if s else s


def r1(x):
    return None if x is None else round(x, 1)


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def round_split(total, shares):
    """Split a whole-dollar total by weights so the parts add up exactly (largest remainder)."""
    total = int(round(total))
    s = sum(shares.values())
    if total <= 0 or s <= 0:
        return {k: 0 for k in shares}
    raw = {k: total * v / s for k, v in shares.items()}
    out = {k: int(math.floor(v)) for k, v in raw.items()}
    left = total - sum(out.values())
    for k in sorted(raw, key=lambda k: (raw[k] - out[k], k), reverse=True)[:left]:
        out[k] += 1
    return out


def load_stats(path=STATS_PATH):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def stats_text(s, horizon="fwd_26w"):
    """'median +7.0%, 76% up, worst 10% -5.2% or worse (59 episodes)' for one stats row."""
    if not s or not s.get(horizon):
        return "n/a"
    h = s[horizon]
    return (f"median {h['median']:+.1f}%, {h['pct_positive']}% up, worst 10% {h['p10']:+.1f}% or worse "
            f"({s['episodes']} episodes)")


# ------------------------------------------------------------------------ entry state
def entry_state(price, ma10, ma40, year_high, returns):
    """Bucket a weekly chart for the entry-stats lookup. None if data is missing."""
    st = canslim.weekly_stage(price, ma10, ma40, returns)
    if not st or not year_high:
        return None
    dd = max(0.0, (1 - price / year_high) * 100)
    pv = st["pct_vs_40"]
    if st["stage"] == 4:
        key = "down_lt10" if dd < 10 else "down_10_20" if dd < 20 else "down_ge20"
    elif pv < canslim.CONFIRM_PCT:
        key = "test_lt5" if dd < 5 else "test_5_10" if dd < 10 else "test_10_20" if dd < 20 else "test_ge20"
    elif st["slope_40w"] == "falling":
        key = "repair"
    else:
        key = "up_lt5" if dd < BUY_ZONE[0] else "up_5_10" if dd < BUY_ZONE[1] else "up_ge10"
    return {"bucket": key, "label": ENTRY_LABELS[key], "off_high_pct": round(dd, 1),
            "pct_vs_40": round(pv, 1), "pct_vs_10": round((price / ma10 - 1) * 100, 1),
            "stage": st["stage"], "stage_label": st["label"], "slope_40w": st["slope_40w"]}


def buy_levels(price, ma10, ma40, high):
    """Price ladder for a fund: its 52-wk high, buy zone, 40-wk confirm line and bear line."""
    if None in (price, ma40, high):
        return None
    confirm = ma40 * (1 + canslim.CONFIRM_PCT / 100)
    zone_hi = high * (1 - BUY_ZONE[0] / 100)
    zone_lo = max(high * (1 - BUY_ZONE[1] / 100), confirm)
    zone = (round(zone_lo, 2), round(zone_hi, 2)) if zone_lo < zone_hi else None
    return {"high": round(high, 2), "ma10": None if ma10 is None else round(ma10, 2), "ma40": round(ma40, 2),
            "confirm_40w": round(confirm, 2), "zone_low": zone and zone[0], "zone_high": zone and zone[1],
            "bear_line": round(high * (1 - BEAR_PCT / 100), 2),
            "to_zone_pct": None if not zone or price <= zone[1] else round((zone[1] / price - 1) * 100, 1)}


def zone_text(entry, lv):
    if not entry or not lv:
        return "n/a"
    b = entry["bucket"]
    rng = f"{money(lv['zone_low'])}–{money(lv['zone_high'])}" if lv["zone_low"] else None
    if b == "up_5_10":
        return f"In the zone now ({rng})" if rng else "In the zone now"
    if b == "up_lt5":
        return (f"{rng} ({lv['to_zone_pct']:+.1f}% away)" if rng and lv["to_zone_pct"] is not None
                else rng or "none: the 40-wk is too close to the high")
    if b == "repair":
        return "Repair: half the reserve goes in now"
    if b == "up_ge10":
        return "Deep drop above a lagging 40-wk: no zone"
    if b.startswith("test"):
        return f"Reclaim {money(lv['confirm_40w'])} first"
    return f"Wait: below a falling 40-wk ({money(lv['ma40'])})"


# ----------------------------------------------------------------------------- market
def drawdowns(market):
    out = {}
    for sym, d in (market or {}).items():
        p, hi = d.get("price"), d.get("year_high")
        if p and hi:
            out[sym] = max(0.0, (1 - p / hi) * 100)
    return out


def iname(k):
    return canslim.INDEX_NAMES.get(k, k)


def market_verdict(market):
    """Period verdict from the S&P 500 and Nasdaq weekly charts. Raises if either is unusable.

    stage4  (any index below a falling 40-wk)                    -> Pause
    below40 (any index below its 40-wk or < 2% above it)          -> Exercise Caution
    repair  (all confirmed above, a 40-wk still falling)          -> Buy More, half the reserve
    ok + an index >= 20% off its 52-wk high (bear in one index)   -> Exercise Caution
    ok + S&P 500 >= 5% off its 52-wk high (pullback in an uptrend) -> Buy More, all the reserve
    ok                                                            -> Buy
    """
    market = {k: v for k, v in (market or {}).items() if k in GATE}
    _, _, reads = canslim.market_read(market)
    if len(reads) < 2:
        raise ValueError("market block needs ^GSPC and ^IXIC with price, ma50, ma200 "
                         "(and year_high, returns 6M/1Y)")
    regime, syms, _ = canslim.market_regime(reads)
    dd = drawdowns(market)
    nm = canslim.index_names
    flags = []
    if len(dd) < len(reads):
        flags.append("market: year_high missing for an index, pullback and bear checks use what's there")

    def confirm(k):
        return reads[k]["ma40"] * (1 + canslim.CONFIRM_PCT / 100)

    confirm_all = " and ".join(f"{iname(k)} {num(confirm(k))}" for k in reads)
    lead = "^GSPC"

    if regime == "stage4":
        verdict, kind = "Pause", "Pause"
        why = f"{nm(syms)} below a falling 40-wk MA (weekly Stage 4)"
        nxt = (f"Exercise Caution once every index is back above its 40-wk MA; Buy More on weekly "
               f"closes 2% above it ({confirm_all})")
    elif regime == "below40":
        verdict, kind = "Exercise Caution", "Exercise Caution"
        parts = []
        for k in syms:
            v = reads[k]
            if v["above40"]:
                parts.append(f"{iname(k)} only {v['pct_vs_40']:+.1f}% above its 40-wk MA, not confirmed")
            else:
                parts.append(f"{iname(k)} below its 40-wk MA ({num(v['ma40'])}), 40-wk {v['slope_40w']}")
        why = "; ".join(parts)
        nxt = (f"Buy on weekly closes 2% above the 40-wk ({confirm_all}); Pause if a 40-wk turns "
               f"down with the index below it")
    elif regime == "repair":
        verdict, kind = "Buy More", "repair"
        why = (f"market repairing: back above its 40-wk MA after a decline, {nm(syms)} 40-wk "
               f"still falling")
        nxt = "the rest of the reserve goes in once every 40-wk flattens or turns up"
    else:
        bears = {k: dd[k] for k in reads if dd.get(k) is not None and dd[k] >= BEAR_PCT}
        if bears:
            verdict, kind = "Exercise Caution", "Exercise Caution"
            why = "; ".join(f"{iname(k)} {dd[k]:.0f}% below its 52-wk high (bear-market territory) "
                            f"while still above a 40-wk MA lifted by the prior run" for k in bears)
            levels = " and ".join(f"{iname(k)} {num(market[k]['year_high'] * (1 - BEAR_PCT / 100))}" for k in bears)
            nxt = f"Buy once back within {BEAR_PCT:.0f}% of the high ({levels})"
        elif dd.get(lead) is not None and dd[lead] >= PULLBACK_PCT:
            verdict, kind = "Buy More", "pullback"
            why = (f"{iname(lead)} {dd[lead]:.1f}% below its 52-wk high with both indexes confirmed "
                   f"above a flat or rising 40-wk: a pullback in an uptrend")
            nxt = f"Exercise Caution on a weekly close under 2% above the 40-wk ({confirm_all})"
        else:
            verdict, kind = "Buy", "Buy"
            why = "both indexes confirmed above a flat or rising 40-wk MA, no pullback"
            hi = market[lead].get("year_high")
            pb = f"{iname(lead)} {num(hi * (1 - PULLBACK_PCT / 100))}" if hi else None
            nxt = ((f"Buy More on a pullback to {pb} (5% off the high) that holds 2% above the 40-wk; "
                    if pb else "") + f"Exercise Caution on a weekly close under {confirm_all}")

    return {
        "verdict": verdict, "kind": kind, "regime": regime, "why": why, "next": nxt,
        "contrib": CONTRIB[verdict], "deploy": DEPLOY[kind],
        "reads": {k: {"stage": v["stage"], "label": v["label"], "slope_40w": v["slope_40w"], "score": v["score"],
                      "ma40": v["ma40"], "pct_vs_40": round(v["pct_vs_40"], 1),
                      "off_high_pct": None if dd.get(k) is None else round(dd[k], 1)}
                  for k, v in reads.items()},
        "flags": flags,
    }


def index_panel(sym, d, stats):
    """Everything a dashboard shows for one index."""
    p, ma10, ma40, hi = d.get("price"), d.get("ma50"), d.get("ma200"), d.get("year_high")
    st = canslim.weekly_stage(p, ma10, ma40, d.get("returns"))
    ent = entry_state(p, ma10, ma40, hi, d.get("returns"))
    return {
        "name": iname(sym), "price": p, "ma10": ma10, "ma40": ma40, "year_high": hi,
        "off_high_pct": None if not (p and hi) else round(max(0.0, (1 - p / hi) * 100), 1),
        "pct_vs_10": None if not (p and ma10) else round((p / ma10 - 1) * 100, 1),
        "pct_vs_40": None if not st else round(st["pct_vs_40"], 1),
        "slope_40w": None if not st else st["slope_40w"], "stage": None if not st else st["stage"],
        "stage_label": None if not st else st["label"], "trend_score": None if not st else st["score"],
        "returns": d.get("returns"),
        "levels": {"confirm_40w": None if not ma40 else round(ma40 * (1 + canslim.CONFIRM_PCT / 100), 2),
                   "pullback": None if not hi else round(hi * (1 - PULLBACK_PCT / 100), 2),
                   "bear_line": None if not hi else round(hi * (1 - BEAR_PCT / 100), 2)},
        "entry": ent, "stats": None if not (ent and stats) else stats["entry"].get(ent["bucket"]),
    }


# ----------------------------------------------------------------------------- health
def _item(key, label, value, display, score):
    return {"key": key, "label": label, "value": value, "display": display,
            "score": None if score is None else round(score), "status": status_of(score)}


def market_health(gate_reads, h, flags):
    """Scored categories, unscored context, and a 0-100 composite over what's available."""
    h = h or {}
    cats = []

    # Trend: the two gate indexes' weekly-stage scores (canslim W, 5-92)
    items = [_item(k, iname(k), r["score"], f"{r['label']}, {r['pct_vs_40']:+.1f}% vs 40-wk", r["score"])
             for k, r in gate_reads.items()]
    cats.append(("trend", items, "; ".join(f"{iname(k)}: {r['label']}" for k, r in gate_reads.items())))

    # Participation: breadth, small caps, equal-weight vs cap-weight
    items, reads = [], []
    if h.get("pct_above_200d") is not None:
        v = h["pct_above_200d"]
        items.append(_item("pct_above_200d", "S&P 500 members above their 200-day", v, f"{v:.0f}%", interp(v, BREADTH_PTS)))
        reads.append(f"{v:.0f}% of S&P 500 stocks above their 200-day")
    rut = h.get("^RUT")
    if rut:
        st = canslim.weekly_stage(rut.get("price"), rut.get("ma50"), rut.get("ma200"), rut.get("returns"))
        if st:
            items.append(_item("^RUT", "Russell 2000", rut.get("price"), f"{st['label']}, {st['pct_vs_40']:+.1f}% vs 40-wk", st["score"]))
            reads.append(f"small caps {st['label']}")
    ew = h.get("rsp_spy_3m_pp")
    if ew is None and h.get("rsp_3m") is not None and h.get("spy_3m") is not None:
        ew = h["rsp_3m"] - h["spy_3m"]
    if ew is not None:
        items.append(_item("rsp_spy_3m_pp", "Equal-weight vs cap-weight, 3M", r1(ew), signed(ew, 1, "pp"), interp(ew, EQUAL_WEIGHT_PTS)))
        reads.append("equal-weight " + ("keeping up" if ew >= -2 else f"lagging by {-ew:.1f}pp (narrow leadership)"))
    cats.append(("participation", items, "; ".join(reads)))

    # Volatility: VIX level, term structure
    items, read = [], ""
    vix, vix3m = h.get("vix"), h.get("vix3m")
    if vix is not None:
        s = interp(vix, VIX_PTS)
        ratio = vix / vix3m if vix3m else None
        if ratio is not None and ratio >= 1:
            s = min(s, 20.0)  # spot above 3-month VIX (backwardation): stress, whatever the level
        items.append(_item("vix", "VIX", vix, f"{vix:.1f}", s))
        if ratio is not None:  # shown, not averaged: it caps the VIX score above
            items.append({"key": "vix_vix3m", "label": "VIX / VIX3M", "value": round(ratio, 2),
                          "display": f"{ratio:.2f}" + (" (inverted)" if ratio >= 1 else ""), "score": None,
                          "status": "weak" if ratio >= 1 else "good"})
        read = f"VIX {vix:.1f}" + (" with the curve inverted (stress)" if vix3m and vix / vix3m >= 1 else "")
    cats.append(("volatility", items, read))

    # Credit: high-yield spread and its 3-month change
    items, read = [], ""
    oas, oas0 = h.get("hy_oas"), h.get("hy_oas_3m_ago")
    if oas is not None:
        s = interp(oas, HY_OAS_PTS)
        chg = None if oas0 is None else oas - oas0
        if chg is not None and chg > HY_WIDEN_PTS[0][0]:
            s = max(0.0, s + interp(chg, HY_WIDEN_PTS))
        items.append(_item("hy_oas", "High-yield spread", oas, f"{oas:.2f}%" + ("" if chg is None else f" ({chg:+.2f} in 3M)"), s))
        read = f"HY spread {oas:.2f}%" + ("" if chg is None else f", {chg:+.2f}pp in 3 months")
    cats.append(("credit", items, read))

    # Yield curve: 10Y minus 3M (2Y if 3M missing)
    items, read = [], ""
    y10, short, short_lbl = h.get("us10y"), h.get("us3m"), "3M"
    if short is None:
        short, short_lbl = h.get("us2y"), "2Y"
    if y10 is not None and short is not None:
        sp = y10 - short
        items.append(_item("curve", f"10Y minus {short_lbl}", round(sp, 2), signed(sp, 2, "pp"), interp(sp, CURVE_PTS)))
        read = f"10Y {y10:.2f}% vs {short_lbl} {short:.2f}%: " + ("inverted" if sp < 0 else "positive")
    cats.append(("curve", items, read))

    scored = []
    for key, items, read in cats:
        s = mean([i["score"] for i in items])
        scored.append({"key": key, "name": HEALTH_NAMES[key], "weight": HEALTH_WEIGHTS[key],
                       "score": None if s is None else round(s), "status": status_of(s), "read": read or "no data",
                       "items": items})
    def composite(cs):
        cs = [c for c in cs if c["score"] is not None]
        w = sum(c["weight"] for c in cs)
        return round(sum(c["score"] * c["weight"] for c in cs) / w) if w else None

    avail = [c for c in scored if c["score"] is not None]
    score = composite(scored)
    internals = composite([c for c in scored if c["key"] != "trend"])
    missing = [c["name"] for c in scored if c["score"] is None]
    if missing:
        flags.append("health: no data for " + ", ".join(missing) + " (score uses the rest)")

    return {"score": score, "label": health_label(score), "coverage": f"{len(avail)}/{len(scored)}",
            "internals_score": internals, "internals_label": health_label(internals),
            "categories": scored, "context": health_context(h)}


def health_context(h):
    out = []
    # Valuation
    items, reads, status = [], [], None
    pe, avg, cape, y10 = h.get("fwd_pe"), h.get("fwd_pe_10y_avg"), h.get("cape"), h.get("us10y")
    if pe and avg:
        prem = (pe / avg - 1) * 100
        status = "cheap" if prem < -10 else "fair" if prem <= 10 else "rich" if prem <= 25 else "very rich"
        items.append({"key": "fwd_pe", "label": "S&P 500 forward P/E", "value": pe,
                      "display": f"{pe:.1f} vs {avg:.1f} 10-yr avg ({prem:+.0f}%)", "status": status})
        reads.append(f"forward P/E {pe:.1f}, {prem:+.0f}% vs its 10-yr average")
    if cape:
        cs = "cheap" if cape < 20 else "fair" if cape < 30 else "rich" if cape < 35 else "very rich"
        status = status or cs
        items.append({"key": "cape", "label": "Shiller CAPE", "value": cape, "display": f"{cape:.1f}", "status": cs})
        reads.append(f"CAPE {cape:.1f}")
    if pe and y10 is not None:
        gap = 100 / pe - y10
        items.append({"key": "earnings_yield_gap", "label": "Earnings yield minus 10Y", "value": round(gap, 2),
                      "display": signed(gap, 2, "pp"), "status": "thin" if gap < 1 else "normal"})
        reads.append(f"earnings yield {100 / pe:.1f}% vs 10Y {y10:.2f}%")
    out.append({"key": "valuation", "name": "Valuation", "status": status, "read": "; ".join(reads) or "no data", "items": items})

    # Sentiment (contrarian at the extremes)
    items, reads, status = [], [], None
    fg, aaii = h.get("fear_greed"), h.get("aaii_bull_bear")
    if fg is not None:
        status = ("extreme fear" if fg <= 25 else "fear" if fg < 45 else "neutral" if fg <= 55
                  else "greed" if fg < 75 else "extreme greed")
        items.append({"key": "fear_greed", "label": "CNN Fear & Greed", "value": fg, "display": f"{fg:.0f}", "status": status})
        reads.append(f"Fear & Greed {fg:.0f} ({status})")
    if aaii is not None:
        a = "euphoric" if aaii > 20 else "fearful" if aaii < -20 else "neutral"
        status = status or a
        items.append({"key": "aaii_bull_bear", "label": "AAII bulls minus bears", "value": aaii,
                      "display": signed(aaii, 1, "pp"), "status": a})
        reads.append(f"AAII bull-bear {aaii:+.1f}pp")
    out.append({"key": "sentiment", "name": "Sentiment", "status": status, "read": "; ".join(reads) or "no data", "items": items})

    # Leadership: offensive vs defensive sectors over 3 months
    items, read, status = [], "no data", None
    sec = h.get("sectors_3m") or {}
    off = mean([sec.get(k) for k in OFFENSIVE])
    dfn = mean([sec.get(k) for k in DEFENSIVE])
    if sec:
        ranked = sorted(sec.items(), key=lambda kv: -kv[1])
        items = [{"key": k, "label": k, "value": v, "display": signed(v), "status": None} for k, v in ranked]
        if off is not None and dfn is not None:
            spread = off - dfn
            status = "risk-on" if spread > 2 else "defensive" if spread < -2 else "mixed"
            read = (f"offensive sectors {spread:+.1f}pp vs defensive over 3M ({status}); leaders "
                    + ", ".join(k for k, _ in ranked[:3]) + "; laggards " + ", ".join(k for k, _ in ranked[-3:]))
    out.append({"key": "leadership", "name": "Leadership", "status": status, "read": read, "items": items})
    return out


def divergence(verdict, health):
    """A note when the internals (health without trend) disagree with the trend-based verdict."""
    s = health["internals_score"]
    if s is None:
        return None
    if verdict in ("Buy", "Buy More") and s < 40:
        return (f"Trend says {verdict}, but the internals are {health['internals_label'].lower()} ({s}/100: "
                f"participation, volatility, credit, curve): stick to the usual amount and skip spare cash "
                f"until they improve.")
    if verdict == "Pause" and s >= 65:
        return (f"The internals are holding up ({s}/100) despite the downtrend: a quick reclaim of the 40-wk "
                f"is plausible, so watch the levels above.")
    return None


# --------------------------------------------------------------------------- holdings
def satellite_from_canslim(r, held, quick):
    """Map canslim's new-money and holder actions onto the five-step scale: (verdict, do, why)."""
    h, nm = r["holder"]["action"], r["new_money"]["action"]
    hn, nn = r["holder"]["note"], r["new_money"]["note"]
    if not held:
        if nm == "Avoid":
            return "Avoid", "Don't buy", nn
        if nm == "Buy":
            return "Buy", "Start a position", nn
        if nm == "Buy (starter)":
            return "Buy", "Start at half size", nn
        if nm == "Buy on pullback":
            return "Exercise Caution", "Wait for the pullback level", nn
        return "Pause", "Not yet", nn
    if h == "Exit":
        return "Sell", "Exit", hn
    if h == "Reduce":
        return "Sell", "Reduce by half", hn
    if h == "Hold, re-check":
        return "Pause", "Hold; no new money", hn
    if nm == "Buy":
        return ("Buy", "Add a tranche", nn) if quick else ("Buy More", "Add a full tranche", nn)
    if nm == "Buy (starter)":
        return "Buy", "Add half a tranche", nn
    if nm == "Buy on pullback":
        return "Exercise Caution", "Hold; add only on the pullback", nn
    return "Exercise Caution", "Hold; don't add yet", nn


def strip_gate(note, gate_note):
    """canslim appends the market-gate reason to every Watchlist note; the market line covers it."""
    if gate_note and note:
        note = note.replace("; " + gate_note, "").replace(gate_note + "; ", "").replace(gate_note, "")
    return note.strip("; ").strip() or note


def read_cell(r, quick):
    bits = []
    if r["type"] == "stock" and not quick:
        bits.append(f"Q {r['quality'] if r['quality'] is not None else 'n/a'}")
    bits.append(f"T {r['timing'] if r['timing'] is not None else 'n/a'}")
    rs = (r.get("details") or {}).get("L", {}).get("rs_delta_pp")
    if rs is not None:
        bits.append(f"RS {rs:+.0f}pp")
    if r.get("thesis"):
        bits.append(f"thesis {r['thesis']['label']}")
    if r.get("weekly"):
        bits.append(r["weekly"]["label"])
    return " · ".join(bits)


def weights(holdings):
    """Market value per held ticker and the total, or (None, None) if any held value is unknown."""
    vals = {}
    for h in holdings:
        if not h.get("_held"):
            continue
        if h.get("value") is not None:
            vals[h["ticker"]] = float(h["value"])
        elif h.get("shares") is not None and h.get("price") is not None:
            vals[h["ticker"]] = float(h["shares"]) * float(h["price"])
        else:
            return None, None
    total = sum(vals.values())
    if total <= 0:
        return None, None
    return vals, total


CORE_DO = {"Buy More": "Usual amount + reserve", "Buy": "Usual amount",
           "Exercise Caution": "Half the usual amount", "Pause": "No new money; hold"}


def run(data):
    as_of = date.fromisoformat(data["as_of"]) if data.get("as_of") else date.today()
    market_in = data.get("market") or {}
    market = {k: v for k, v in market_in.items() if k in GATE}
    health_in = dict(data.get("health") or {})
    for k, v in market_in.items():  # extra indexes (e.g. ^RUT) are health context, never the gate
        if k not in GATE:
            health_in.setdefault(k, v)
    cfg = {**DEFAULTS, **(data.get("portfolio") or {})}
    quick = data.get("mode", "full") == "quick"
    holdings = [dict(h) for h in (data.get("holdings") or [])]
    flags = []
    stats = load_stats()
    if stats is None:
        flags.append("references/entry_stats.json missing: historical stats omitted (run build_stats.py)")

    mv = market_verdict(market)
    flags += mv["flags"]
    _, _, reads = canslim.market_read(market)
    gate_note = canslim.market_regime(reads)[2]
    health = market_health(mv["reads"], health_in, flags)
    div = divergence(mv["verdict"], health)

    # ---- canslim read per holding
    results = []
    for h in holdings:
        is_etf = h.get("type", "stock") == "etf"
        sleeve = h.get("sleeve")
        if sleeve not in ("core", "satellite"):
            sleeve = "core" if is_etf else "satellite"
            if is_etf:
                flags.append(f"{h.get('ticker')}: sleeve not given, assumed core ({BROAD_HINT})")
        if sleeve == "core" and not is_etf:
            flags.append(f"{h.get('ticker')}: a single stock can't be core, scored as satellite")
            sleeve = "satellite"
        h["_sleeve"] = sleeve
        h["_held"] = h.get("held", True) and h.get("shares", 1) != 0 and h.get("value", 1) != 0
        t = dict(h)
        if quick and not is_etf:
            t["type"], t["etf_class"] = "etf", "equity"  # trend-only read, fundamentals skipped
        r = canslim.score_ticker(t, market, as_of)
        r["type"] = "etf" if is_etf else "stock"
        results.append(r)
        flags += [f"{h.get('ticker')}: {f}" for f in r["flags"]]

    vals, total = weights(holdings)
    if vals is None and any(h["_held"] for h in holdings):
        flags.append("weights unknown (shares or value missing on a held position): drift checks and size caps skipped")
    wt = {k: v / total * 100 for k, v in vals.items()} if vals else {}
    sat_wt = sum(wt.get(h["ticker"], 0) for h in holdings if h["_sleeve"] == "satellite") if vals else None
    sat_target, band = cfg["satellite_target_pct"], cfg["band_pp"]
    sat_over = sat_wt is not None and sat_wt > sat_target + band
    # Core targets are each fund's share of the core, so a satellite sleeve that is under or over
    # its target doesn't make every core fund look off.
    core_tk = [h["ticker"] for h in holdings if h["_sleeve"] == "core"]
    raw_t = {h["ticker"]: h.get("target_pct") for h in holdings if h["_sleeve"] == "core"}
    core_tgt = {}
    if core_tk and all(v is not None for v in raw_t.values()) and sum(raw_t.values()) > 0:
        if abs(sum(raw_t.values()) - 100) > 0.5:
            flags.append(f"core target_pct values sum to {sum(raw_t.values()):g}, not 100: rescaled to 100")
        core_tgt = {k: v * 100 / sum(raw_t.values()) for k, v in raw_t.items()}
    elif any(v is not None for v in raw_t.values()):
        flags.append("target_pct missing on some core funds: core drift check skipped, new money split evenly")
    core_total = sum(vals.get(k, 0.0) for k in core_tk) if vals else 0.0
    core_wt = {k: vals.get(k, 0.0) / core_total * 100 for k in core_tk} if vals and core_total > 0 else {}

    rows = []
    for h, r in zip(holdings, results):
        tk, sleeve, held = h["ticker"], h["_sleeve"], h["_held"]
        stage = r.get("weekly") or {}
        w = wt.get(tk)
        rs = (r.get("details") or {}).get("L", {}).get("rs_delta_pp")
        ent = entry_state(h.get("price"), h.get("ma50"), h.get("ma200"), h.get("year_high"), h.get("returns"))
        notes = []
        row = {"ticker": tk, "sleeve": sleeve, "held": held, "price": h.get("price"),
               "weight_pct": None if w is None else round(w, 1),
               "value": None if not vals else (None if vals.get(tk) is None else round(vals[tk], 2)),
               "rs_pp": rs, "entry": ent}
        if sleeve == "core":
            v, do = mv["verdict"], CORE_DO[mv["verdict"]]
            if mv["kind"] == "repair":
                do = "Usual amount + half the reserve"
            if stage.get("stage") == 4 and RANK[v] > RANK["Pause"]:
                v, do = "Pause", CORE_DO["Pause"]
                notes.append(f"{tk} itself below a falling 40-wk MA ({money(stage['ma40'])})")
            elif stage and not stage.get("above40") and RANK[v] > RANK["Exercise Caution"]:
                v, do = "Exercise Caution", CORE_DO["Exercise Caution"]
                notes.append(f"{tk} below its own 40-wk MA ({money(stage['ma40'])})")
            elif v == "Buy" and ent and ent["bucket"] == "up_5_10":
                v, do = "Buy More", "Usual amount, tilted here"
                notes.append(f"{tk} in its own buy zone: {ent['off_high_pct']:.1f}% off its high above a "
                             f"confirmed 40-wk")
            cw, tgt = core_wt.get(tk), core_tgt.get(tk)
            if cw is not None and tgt is not None and cw > tgt + band and RANK[v] > RANK["Pause"]:
                v, do = "Pause", CORE_DO["Pause"]
                notes.append(f"{cw:.1f}% of the core vs {tgt:.0f}% target: new money goes to the underweight funds")
            own = stage.get("label", "no weekly read") + ("" if rs is None else f", RS {rs:+.0f}pp vs S&P")
            lv = buy_levels(h.get("price"), h.get("ma50"), h.get("ma200"), h.get("year_high"))
            row.update({"verdict": v, "do": do,
                        "why": "; ".join(notes) if notes else f"Follows the market; own chart: {own}",
                        "target_pct": None if tgt is None else round(tgt, 1),
                        "core_weight_pct": None if cw is None else round(cw, 1),
                        "levels": lv, "zone": zone_text(ent, lv),
                        "stats": None if not (ent and stats) else stats["entry"].get(ent["bucket"]),
                        "chart": stage.get("label"), "timing": r["timing"]})
        else:
            v, do, why = satellite_from_canslim(r, held, quick)
            why = strip_gate(why, gate_note)
            if v not in ("Sell", "Avoid") and RANK[mv["verdict"]] <= RANK["Exercise Caution"] \
                    and RANK[v] > RANK[mv["verdict"]]:
                v = mv["verdict"]
                do = "Hold; no new money" if held else "Not yet"
                notes.append(f"market verdict is {mv['verdict']}")
            if held and w is not None and v != "Sell":
                if w > cfg["trim_position_pct"]:
                    v = "Sell"
                    do = f"Trim to {cfg['max_position_pct']:g}%"
                    if vals:
                        do += f" (≈{dollars(vals[tk] - cfg['max_position_pct'] / 100 * total)})"
                    notes.append(f"{w:.1f}% of the portfolio, over the {cfg['trim_position_pct']:g}% trim line")
                elif w > cfg["max_position_pct"] and RANK[v] > RANK["Exercise Caution"]:
                    v, do = "Exercise Caution", "Hold; no adds"
                    notes.append(f"{w:.1f}% of the portfolio, at the {cfg['max_position_pct']:g}% position cap")
            if sat_over and v not in ("Sell", "Avoid") and RANK[v] > RANK["Exercise Caution"]:
                v, do = "Exercise Caution", "Hold; no adds" if held else "Not yet"
                notes.append(f"satellite sleeve {sat_wt:.1f}% vs {sat_target:g}% target: new money goes to the core")
            if quick and r["type"] == "stock" and v == "Sell" and r["holder"]["action"] == "Reduce":
                notes.append("quick run: the full check decides Reduce vs Exit")
            if notes:
                why = cap_first(why) + "; " + "; ".join(notes)
            row.update({"verdict": v, "do": do, "why": cap_first(why), "read": read_cell(r, quick),
                        "canslim": {"new_money": r["new_money"], "holder": r["holder"], "quality": r["quality"],
                                    "timing": r["timing"],
                                    "thesis": None if not r.get("thesis") else r["thesis"]["label"],
                                    "stage": stage.get("stage"), "confidence": r["confidence"]}})
        rows.append(row)

    plan = make_plan(cfg, mv, rows, vals, total)
    actions = [f"{x['verdict']} {x['ticker']}: {x['do']}" for x in rows if x["verdict"] == "Sell"]
    sleeves = None if sat_wt is None else {"core_pct": round(100 - sat_wt, 1), "satellite_pct": round(sat_wt, 1),
                                           "satellite_target_pct": sat_target}
    return build_output(as_of, quick, market, mv, health, div, stats, rows, plan, actions, sleeves, flags)


# ------------------------------------------------------------------------------- plan
def make_plan(cfg, mv, rows, vals, total):
    """Dollar split of this period's amount. None when no amount is given."""
    amount = cfg.get("amount") or cfg.get("contribution")
    if not amount:
        return None
    reserve = float(cfg.get("cash_reserve") or 0)
    new_in = amount * mv["contrib"]
    from_reserve = reserve * mv["deploy"]
    pool = new_in + from_reserve
    to_reserve = amount - new_in

    tilt = {"Buy More": 2.0, "Buy": 1.0, "Exercise Caution": 1.0}
    sat = {r["ticker"]: tilt[r["verdict"]] for r in rows
           if r["sleeve"] == "satellite" and r["verdict"] in ("Buy More", "Buy")}
    sat_pool = pool * cfg["satellite_target_pct"] / 100 if sat else 0.0
    alloc = {}
    if sat:
        split = {k: sat_pool * v / sum(sat.values()) for k, v in sat.items()}
        if vals:  # never push a position past the per-position cap
            after = total + pool
            for k in split:
                room = max(0.0, cfg["max_position_pct"] / 100 * after - (vals.get(k) or 0.0))
                split[k] = min(split[k], room)
        alloc.update(split)
    core_pool = pool - sum(alloc.values())

    core = [r for r in rows if r["sleeve"] == "core" and r["verdict"] in tilt]
    if core and core_pool > 0:
        tg = {r["ticker"]: (r["target_pct"] if r["target_pct"] is not None else 1.0) for r in core}
        mult = {r["ticker"]: tilt[r["verdict"]] for r in core}
        if vals:
            base = sum(vals.get(k, 0.0) for k in tg) + core_pool
            gaps = {k: max(0.0, base * tg[k] / sum(tg.values()) - vals.get(k, 0.0)) for k in tg}
            shares = gaps if sum(gaps.values()) > 0 else dict(tg)
        else:
            shares = dict(tg)
        # A fund in its own buy zone (Buy More) gets double weight this period; the drift check
        # (target + band_pp) stops new money to it once it's overweight.
        shares = {k: v * mult[k] for k, v in shares.items()}
        alloc.update({k: core_pool * v / sum(shares.values()) for k, v in shares.items()})
    elif core_pool > 0:
        to_reserve += core_pool
    split = round_split(sum(alloc.values()), alloc)
    split = {k: v for k, v in split.items() if v > 0}
    return {"amount": amount, "invest": int(round(sum(split.values()))), "from_reserve": round(from_reserve),
            "to_reserve": round(to_reserve), "reserve_after": round(reserve - from_reserve + to_reserve),
            "split": split}


# ----------------------------------------------------------------------------- output
def esc(s):
    return str(s).replace("|", "/")


def build_output(as_of, quick, market, mv, health, div, stats, rows, plan, actions, sleeves, flags):
    order = {"core": 0, "satellite": 1}
    rows.sort(key=lambda r: (order[r["sleeve"]], -1 if r["weight_pct"] is None else -r["weight_pct"], r["ticker"]))
    core = [r for r in rows if r["sleeve"] == "core"]
    sat = [r for r in rows if r["sleeve"] == "satellite"]
    vstats = None if not stats else stats["verdict"].get("Buy More (repair)" if mv["kind"] == "repair" else mv["verdict"])
    indexes = {k: index_panel(k, market[k], stats) for k in GATE}

    verdict = {"label": mv["verdict"], "kind": mv["kind"], "regime": mv["regime"], "why": mv["why"],
               "next": mv["next"], "do": core_do(mv), "contribution_pct": round(mv["contrib"] * 100),
               "reserve_deploy_pct": round(mv["deploy"] * 100), "stats": vstats, "divergence": div}

    text = render_text(as_of, quick, mv, verdict, indexes, health, core, sat, plan, actions, sleeves)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "as_of": as_of.isoformat(),
        "mode": "quick" if quick else "full",
        "verdict": verdict,
        "market": {"indexes": indexes, "stats_period": None if not stats else stats["period"]},
        "health": health,
        "core": core,
        "satellite": sat,
        "sleeves": sleeves,
        "plan": plan,
        "actions": actions,
        "flags": flags,
        "text": text,
    }


def core_do(mv):
    v = mv["verdict"]
    if v == "Pause":
        return "Core: invest nothing new this period; the whole contribution goes to the cash reserve. Don't sell the core."
    if v == "Exercise Caution":
        return "Core: invest half the usual amount; the other half goes to the cash reserve."
    if mv["kind"] == "repair":
        return "Core: invest the usual amount plus half the cash reserve."
    if v == "Buy More":
        return "Core: invest the usual amount plus all of the cash reserve; spare cash outside the plan can go in too."
    return "Core: invest the usual amount (plus any cash reserve)."


def render_text(as_of, quick, mv, verdict, indexes, health, core, sat, plan, actions, sleeves):
    hs = "" if health["score"] is None else f" · Market health {health['score']}/100 {health['label']}"
    head = f"**Portfolio verdict {as_of.isoformat()}: {mv['verdict']}**{hs}" + (" (quick run)" if quick else "")
    mkt = []
    for k, ix in indexes.items():
        off = "" if ix["off_high_pct"] is None else f", {ix['off_high_pct']:.1f}% off high"
        mkt.append(f"{ix['name']} {num(ix['price'])} ({ix['pct_vs_40']:+.1f}% vs 40-wk {num(ix['ma40'])}, "
                   f"{ix['slope_40w']}{off})")
    vs = verdict["stats"]
    stats_line = None
    if vs:
        stats_line = (f"History: after {mv['verdict'] if mv['kind'] != 'repair' else 'repair'} weeks in 2000–23, "
                      f"the next 26 weeks (S&P/Nasdaq blend): {stats_text(vs)}.")

    # health table
    ht = ["| Area | Score | Read |", "|---|---|---|"]
    for c in health["categories"]:
        sc = "n/a" if c["score"] is None else f"{c['score']} {c['status']}"
        ht.append(f"| {c['name']} ({c['weight']}%) | {sc} | {esc(c['read'])} |")
    for c in health["context"]:
        ht.append(f"| {c['name']} (context) | {c['status'] or 'n/a'} | {esc(c['read'])} |")

    tables = []
    if core:
        t = ["| Core fund | Of core / target | Verdict | Do | Chart now | After similar weeks (26w) | Buy zone |",
             "|---|---|---|---|---|---|---|"]
        for r in core:
            w = "n/a" if r["core_weight_pct"] is None else f"{r['core_weight_pct']:.1f}%"
            if r["target_pct"] is not None:
                w += f" / {r['target_pct']:.0f}%"
            do = r["do"] + ("" if r["why"].startswith("Follows the market") else f" ({r['why']})")
            chart = (r["entry"]["label"] if r["entry"] else (r["chart"] or "n/a"))
            st = "n/a" if not r["stats"] else stats_text(r["stats"])
            t.append(f"| {r['ticker']} | {w} | **{r['verdict']}** | {esc(do)} | {esc(chart)} | {esc(st)} | {esc(r['zone'])} |")
        tables.append("\n".join(t))
    if sat:
        t = ["| Satellite | Of portfolio | Verdict | Do | Read | Why |", "|---|---|---|---|---|---|"]
        for r in sat:
            w = "—" if not r["held"] else ("n/a" if r["weight_pct"] is None else f"{r['weight_pct']:.1f}%")
            t.append(f"| {r['ticker']} | {w} | **{r['verdict']}** | {esc(r['do'])} | {esc(r['read'])} | {esc(r['why'])} |")
        tables.append("\n".join(t))

    plan_line = None
    if plan:
        parts = [f"{k} {dollars(v)}" for k, v in sorted(plan["split"].items(), key=lambda kv: (-kv[1], kv[0]))]
        plan_line = (f"Plan for {dollars(plan['amount'])}: invest {dollars(plan['invest'])}"
                     + (f" (incl. {dollars(plan['from_reserve'])} from the reserve)" if plan["from_reserve"] else "")
                     + (": " + " · ".join(parts) if parts else "")
                     + (f" · to reserve {dollars(plan['to_reserve'])}" if plan["to_reserve"] else "")
                     + f" · reserve after {dollars(plan['reserve_after'])}")
    sleeve_line = None if not sleeves else (
        f"Sleeves: core {sleeves['core_pct']:.1f}% · satellite {sleeves['satellite_pct']:.1f}% "
        f"(target {100 - sleeves['satellite_target_pct']:g} / {sleeves['satellite_target_pct']:g})")
    return {
        "headline": head,
        "market_line": "Market: " + " · ".join(mkt),
        "why_line": "Why: " + cap_first(mv["why"]),
        "do_line": verdict["do"],
        "next_line": "Changes: " + mv["next"],
        "stats_line": stats_line,
        "divergence_line": verdict["divergence"],
        "health_table_md": "\n".join(ht),
        "sleeve_line": sleeve_line,
        "tables_md": tables,
        "plan_line": plan_line,
        "actions_line": None if not actions else "Action items: " + "; ".join(actions),
    }


# ---------------------------------------------------------------------------- history
def history_record(out):
    """One compact line per run for dashboards' time series."""
    ix = out["market"]["indexes"]
    return {
        "as_of": out["as_of"], "mode": out["mode"], "verdict": out["verdict"]["label"],
        "kind": out["verdict"]["kind"], "health": out["health"]["score"],
        "health_label": out["health"]["label"],
        "indexes": {k: {"price": v["price"], "pct_vs_40": v["pct_vs_40"], "off_high_pct": v["off_high_pct"]}
                    for k, v in ix.items()},
        "holdings": {r["ticker"]: {"verdict": r["verdict"], "price": r["price"]} for r in out["core"] + out["satellite"]},
        "plan": None if not out["plan"] else {k: out["plan"][k] for k in ("invest", "to_reserve", "reserve_after")},
    }


def write_out(out, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "latest.json"), "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")
    path = os.path.join(out_dir, "history.jsonl")
    lines = []
    if os.path.exists(path):
        with open(path) as f:
            lines = [json.loads(x) for x in f if x.strip()]
    rec = history_record(out)
    lines = [x for x in lines if x.get("as_of") != rec["as_of"]] + [rec]
    lines.sort(key=lambda x: x["as_of"])
    with open(path, "w") as f:
        for x in lines:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")


def main(argv):
    args = argv[1:]
    out_dir = None
    if "--out" in args:
        i = args.index("--out")
        out_dir = args[i + 1]
        del args[i:i + 2]
    src = open(args[0]) if args else sys.stdin
    with src:
        data = json.load(src)
    try:
        out = run(data)
    except ValueError as e:
        sys.exit(f"verdict.py: {e}")
    if out_dir:
        write_out(out, out_dir)
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main(sys.argv)
