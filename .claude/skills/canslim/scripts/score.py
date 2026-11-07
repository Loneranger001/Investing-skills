#!/usr/bin/env python3
"""Deterministic scorer for the canslim skill.

The model gathers raw inputs (schema: example_input.json) and makes a few categorical
judgments; this script does every number: factor scores, the Quality and Timing
composites, the weekly stage, the thesis label, and the new-money / holder actions.
Same input -> same output, every run. Stdlib only.

Usage:
    python3 score.py input.json        # or pipe the JSON on stdin
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date

# --------------------------------------------------------------------------- weights
# Quality answers "is this worth owning for 2-5 years?"; Timing answers "is now a
# good weekly-chart entry?". They are reported separately and combined only in the
# action rules at the bottom.
QUALITY_WEIGHTS = {"A": 0.30, "C": 0.20, "R": 0.15, "S": 0.15, "N": 0.10, "I": 0.10}
TIMING_WEIGHTS = {"W": 0.40, "L": 0.30, "E": 0.15, "M": 0.15}

# ----------------------------------------------------------------------- breakpoints
# Piecewise-linear (x, score) curves. Scores are interpolated between points and
# clamped at the ends, so there are no bands to pick from and no cliff edges.
EPS_CAGR_PTS = [(-10, 0), (0, 20), (10, 45), (15, 60), (25, 80), (40, 95), (60, 100)]
REV_CAGR_PTS = [(-5, 0), (0, 15), (5, 35), (10, 55), (20, 80), (30, 95), (50, 100)]
EPS_YOY_PTS = [(-20, 0), (0, 20), (10, 40), (25, 65), (40, 85), (70, 100)]
REV_YOY_PTS = [(-10, 0), (0, 20), (10, 45), (20, 70), (30, 90), (50, 100)]
ROE_PTS = [(-10, 0), (0, 10), (10, 40), (17, 70), (25, 85), (40, 100)]
ROIC_PTS = [(-10, 0), (0, 10), (8, 40), (12, 60), (17, 75), (25, 90), (40, 100)]
MARGIN_DELTA_PTS = [(-10, 0), (-3, 30), (0, 55), (3, 75), (10, 100)]
SHARE_CHG_PTS = [(-3, 100), (-1, 85), (0, 70), (1, 60), (3, 35), (8, 10), (15, 0)]
LEVERAGE_PTS = [(-0.5, 100), (0, 95), (1, 85), (2, 65), (3, 40), (5, 10)]
RS_DELTA_PTS = [(-30, 0), (-10, 25), (0, 50), (10, 70), (25, 90), (40, 100)]
EXT_10W_PTS = [(-15, 20), (-5, 55), (0, 80), (5, 95), (10, 90), (20, 55), (30, 20), (40, 5)]
OFF_HIGH_PTS = [(0, 100), (5, 95), (15, 75), (25, 50), (40, 15), (60, 0)]
PEG_PENALTY_PTS = [(2, 0), (3, -5), (4, -10)]
INST_PCT_PTS = [(10, 25), (30, 40), (60, 65), (80, 70)]

NEWNESS = {"major": 90, "ordinary": 50, "stale": 20}
INST_TREND = {"rising": 80, "flat": 60, "falling": 35}

QUALITY_BUY = 70      # Quality needed for a Buy
QUALITY_FLOOR = 55    # below this: Avoid for new money
TIMING_BUY = 70       # Timing needed for a Buy
EXTENDED_PCT = 20     # % above the 10-wk MA that counts as extended
LEADER_RS_PP = 10     # weighted 3/6/12-mo return must beat the S&P 500 by this many pp (L = 70)
CONFIRM_PCT = 2.0     # an index counts as above its 40-wk only once it closes this % above it
EARNINGS_WINDOW = 14  # days; flag entries this close to a report
INDEX_NAMES = {"^GSPC": "S&P 500", "^IXIC": "Nasdaq", "^DJI": "Dow", "^RUT": "Russell 2000"}


# --------------------------------------------------------------------------- helpers
def interp(x, pts):
    """Piecewise-linear lookup through (x, y) breakpoints sorted by x, clamped at ends."""
    if x is None:
        return None
    if x <= pts[0][0]:
        return float(pts[0][1])
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return float(pts[-1][1])


def clamp(v, lo=0.0, hi=100.0):
    return None if v is None else max(lo, min(hi, v))


def yoy(new, old):
    """% change. None when either side is missing or the base is <= 0 (growth off a loss)."""
    if new is None or old is None or old <= 0:
        return None
    return (new / old - 1) * 100


def cagr(first, last, years):
    if first is None or last is None or first <= 0 or last <= 0 or years <= 0:
        return None
    return ((last / first) ** (1 / years) - 1) * 100


def mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def weighted(scores, weights):
    """Weighted average over the factors that have a score; missing ones are re-weighted away."""
    avail = {k: v for k, v in scores.items() if v is not None}
    if not avail:
        return None
    total = sum(weights[k] for k in avail)
    return sum(weights[k] * v for k, v in avail.items()) / total


def to99(x):
    """0-100 composite -> 0-99 integer (x * 0.99, half-up)."""
    return None if x is None else int(math.floor(clamp(x) * 0.99 + 0.5))


def r1(x):
    return None if x is None else round(x, 1)


def money(x):
    return "n/a" if x is None else f"${x:,.2f}"


# ---------------------------------------------------------------------- weekly stage
def slope_40w(price, ma50, r6m, r1y, band=0.02):
    """Direction of the 40-wk (~200-day) MA over the last ~10 weeks, from data we already have.

    SMA200 change over 50 days = (SMA50_now - SMA50_200d_ago) / 4, and SMA50 200 trading
    days ago is centred ~45 weeks back. That price is interpolated (log scale) between the
    26-wk and 52-wk-ago prices implied by the 6M and 1Y returns.
    """
    if None in (price, ma50, r6m, r1y) or r6m <= -100 or r1y <= -100:
        return None
    p26 = price / (1 + r6m / 100)
    p52 = price / (1 + r1y / 100)
    w = (45 - 26) / (52 - 26)
    p45 = math.exp(math.log(p26) + w * (math.log(p52) - math.log(p26)))
    ratio = ma50 / p45
    if ratio > 1 + band:
        return "rising"
    if ratio < 1 - band:
        return "falling"
    return "flat"


def weekly_stage(price, ma50, ma200, returns):
    """Stage 1-4 on the weekly chart. ma50 ~ 10-wk MA, ma200 ~ 40-wk MA."""
    if None in (price, ma50, ma200):
        return None
    r = returns or {}
    slope = slope_40w(price, ma50, r.get("6M"), r.get("1Y"))
    approx = slope is None
    if approx:
        slope = "rising" if ma50 > ma200 else "falling"
    above40, above10, golden = price > ma200, price > ma50, ma50 > ma200
    prior_up = r["1Y"] > 0 if r.get("1Y") is not None else golden
    bump = 5 if above10 else 0

    if above40:
        if slope == "rising":
            if golden:
                s, st, lab = (92, 2, "Stage 2 uptrend") if above10 else (72, 2, "Stage 2 pullback below 10-wk")
            else:
                s, st, lab = (75, 2, "early Stage 2, reclaimed 40-wk") if above10 else (55, 2, "early Stage 2, below 10-wk")
        elif slope == "flat":
            if prior_up:
                s, st, lab = 45 + bump, 3, "Stage 3 top, 40-wk flattening"
            else:
                s, st, lab = 55 + bump, 1, "Stage 1 base, 40-wk flat"
        else:
            s, st, lab = 45 + bump, 1, "Stage 1 repair above a falling 40-wk"
    else:
        if slope == "rising":
            s, st, lab = 35 + bump, 2, "Stage 2 correction below 40-wk"
        elif slope == "flat":
            # Below a flat 40-wk is ambiguous in real time: a base, or a rollover into
            # Stage 4 (S&P 500, Apr-May 2022). Labelled as such; never a buy signal.
            if prior_up:
                s, st, lab = 25 + bump, 3, "Stage 3 breakdown, 40-wk flat"
            else:
                s, st, lab = 30 + bump, 1, "below a flat 40-wk, base or rollover"
        else:
            s, st, lab = (12 if golden else 5), 4, "Stage 4 downtrend"
    return {
        "score": float(s), "stage": st, "label": lab, "slope_40w": slope,
        "ma40": ma200, "pct_vs_40": (price / ma200 - 1) * 100,
        "slope_approx": approx, "above10": above10, "above40": above40,
    }


# --------------------------------------------------------------------- quality factors
def factor_A(annual, flags):
    if not annual or len(annual) < 2:
        flags.append("A: fewer than 2 fiscal years of data")
        return None, {}
    years = len(annual) - 1
    if years < 3:
        flags.append(f"A: only {years + 1} fiscal years (recent IPO?), CAGR over {years}y")
    eps = [a.get("eps") for a in annual]
    rev = [a.get("rev") for a in annual]
    eps_g = cagr(eps[0], eps[-1], years)
    rev_g = cagr(rev[0], rev[-1], years)
    rev_s = interp(rev_g, REV_CAGR_PTS)
    detail = {"eps_cagr": r1(eps_g), "rev_cagr": r1(rev_g)}
    if eps_g is not None:
        down = sum(1 for a, b in zip(eps, eps[1:]) if a is not None and b is not None and b < a)
        detail["eps_down_years"] = down
        eps_s = interp(eps_g, EPS_CAGR_PTS) - 8 * down
        score = eps_s if rev_s is None else 0.6 * eps_s + 0.4 * rev_s
    elif eps[-1] is not None and eps[-1] > 0:
        flags.append("A: EPS base year was a loss, scored on revenue growth")
        score = None if rev_s is None else 0.8 * rev_s
    else:
        flags.append("A: currently unprofitable, scored on revenue growth (cap 40)")
        score = None if rev_s is None else min(0.5 * rev_s, 40)
    return clamp(score), detail


def factor_C(quarters, flags):
    qs = (quarters or [])[:3]
    if not qs:
        flags.append("C: no quarterly data")
        return None, {}
    q0 = qs[0]
    eps_r = [yoy(q.get("eps"), q.get("eps_ya")) for q in qs]
    op_r = [yoy(q.get("op_inc"), q.get("op_inc_ya")) for q in qs]
    rev_r = [yoy(q.get("rev"), q.get("rev_ya")) for q in qs]
    detail = {"eps_yoy": [r1(x) for x in eps_r], "rev_yoy": [r1(x) for x in rev_r],
              "op_inc_yoy": [r1(x) for x in op_r]}

    distorted = eps_r[0] is not None and op_r[0] is not None and abs(eps_r[0] - op_r[0]) > 25
    if distorted:
        flags.append(f"C: GAAP EPS growth ({eps_r[0]:.0f}%) vs operating income ({op_r[0]:.0f}%) "
                     "differ >25pp, scored on operating income")
    basis = op_r if distorted else eps_r
    detail["basis"] = "op_inc" if distorted else "eps"
    rev_s = interp(rev_r[0], REV_YOY_PTS)
    eps0 = q0.get("eps")

    if eps0 is None:
        flags.append("C: latest EPS missing, scored on revenue only")
        return clamp(rev_s), detail
    if eps0 <= 0:
        ya = q0.get("eps_ya")
        narrowing = ya is not None and eps0 > ya
        flags.append("C: latest quarter is a loss" + (" (narrowing)" if narrowing else ""))
        eps_s = 15.0 if narrowing else 0.0
        score = eps_s if rev_s is None else 0.4 * eps_s + 0.6 * rev_s
        return clamp(score), detail

    if basis[0] is None:
        flags.append("C: year-ago quarter was a loss, growth undefined, scored as turnaround (70)")
        eps_s = 70.0
    else:
        eps_s = interp(basis[0], EPS_YOY_PTS)
    score = eps_s if rev_s is None else 0.65 * eps_s + 0.35 * rev_s

    accel = 0
    if len(basis) >= 3 and None not in basis[:3]:
        if basis[0] > basis[1] > basis[2]:
            accel = 8
        elif basis[0] < basis[1] < basis[2] and basis[0] < 40:
            accel = -8
    elif len(basis) >= 2 and None not in basis[:2]:
        if basis[0] > basis[1]:
            accel = 4
        elif basis[0] < basis[1] and basis[0] < 40:
            accel = -4
    detail["accel_adj"] = accel
    return clamp(score + accel), detail


def factor_R(t, annual, flags):
    roe, roic = t.get("roe"), t.get("roic")
    if roe is not None and 0 < roe <= 1.5:
        ret_s, basis = interp(roe * 100, ROE_PTS), "ROE"
    elif roic is not None:
        ret_s, basis = interp(roic * 100, ROIC_PTS), "ROIC"
        if roe is not None:
            flags.append(f"R: ROE {roe * 100:.0f}% not meaningful (negative or tiny equity), used ROIC")
    elif roe is not None:
        ret_s, basis = (0.0 if roe <= 0 else 100.0), "ROE"
    else:
        ret_s, basis = None, None

    def margin(a):
        return a["op_inc"] / a["rev"] if a.get("op_inc") is not None and a.get("rev") else None

    mdelta = None
    if annual and len(annual) >= 2:
        m0, m1 = margin(annual[0]), margin(annual[-1])
        if m0 is not None and m1 is not None:
            mdelta = (m1 - m0) * 100
    margin_s = interp(mdelta, MARGIN_DELTA_PTS)
    detail = {"returns_basis": basis, "op_margin_delta_pp": r1(mdelta)}
    if ret_s is not None and margin_s is not None:
        score = 0.6 * ret_s + 0.4 * margin_s
    else:
        score = ret_s if ret_s is not None else margin_s
    return clamp(score), detail


def share_change(annual):
    """(%/yr change in diluted shares, split_suspected)."""
    if not annual or len(annual) < 2:
        return None, False
    sh = [a.get("shares") for a in annual]
    pairs = [(a, b) for a, b in zip(sh, sh[1:]) if a and b]
    split = any(b / a > 1.5 or b / a < 0.67 for a, b in pairs)
    return cagr(sh[0], sh[-1], len(sh) - 1), split


def factor_S(t, annual, flags):
    chg, split = share_change(annual)
    if split:
        flags.append("S: share count jumps >50% in a year, possible unadjusted split, share trend not scored")
        chg = None
    share_s = interp(chg, SHARE_CHG_PTS)

    ebitda = annual[-1].get("ebitda") if annual else None
    nd = t.get("net_debt_to_ebitda")
    if ebitda is not None and ebitda <= 0:
        flags.append("S: EBITDA <= 0, leverage not scored (judge cash runway in the thesis)")
        lev_s = None
    else:
        lev_s = interp(nd, LEVERAGE_PTS)

    fcf = t.get("fcf_yield")
    penalty = 15 if fcf is not None and fcf < 0 else 0
    if penalty:
        flags.append("S: free cash flow negative (-15)")
    base = mean([share_s, lev_s])
    detail = {"shares_chg_pct_yr": r1(chg), "net_debt_to_ebitda": nd, "fcf_yield": fcf}
    return (None if base is None else clamp(base - penalty)), detail


def factor_N(t, flags):
    v = t.get("newness")
    if v not in NEWNESS:
        flags.append("N: no dated catalyst news found, factor dropped")
        return None
    return float(NEWNESS[v])


def factor_I(t, flags):
    inst = t.get("institutional") or {}
    trend, pct = inst.get("trend"), inst.get("pct")
    if trend in INST_TREND:
        s = INST_TREND[trend]
        if pct is not None and pct < 0.2:
            s -= 20
        return float(clamp(s))
    if pct is not None:
        return interp(pct * 100, INST_PCT_PTS)
    flags.append("I: no institutional data, factor dropped")
    return None


def valuation(t, eps_cagr, flags):
    """Penalty (0 to -10) for a stretched trailing PEG. A 2-5 yr hold can't ignore price."""
    last4, price = t.get("last4_eps"), t.get("price")
    if not last4 or len(last4) < 4 or None in last4 or price is None:
        flags.append("valuation: need last4_eps, not assessed")
        return 0.0, {}
    ttm = sum(last4)
    if ttm <= 0:
        flags.append("valuation: TTM EPS <= 0, not assessed")
        return 0.0, {"ttm_eps": round(ttm, 2)}
    pe = price / ttm
    detail = {"ttm_eps": round(ttm, 2), "pe_ttm": r1(pe)}
    if eps_cagr is None or eps_cagr <= 0:
        flags.append("valuation: no positive EPS growth for PEG, not assessed")
        return 0.0, detail
    peg = pe / min(eps_cagr, 50)  # cap growth: multi-hundred-% CAGRs don't persist
    detail["peg"] = round(peg, 2)
    pen = interp(peg, PEG_PENALTY_PTS)
    if pen < 0:
        flags.append(f"valuation: trailing PEG {peg:.1f}, {pen:.0f} on Quality")
    return pen, detail


# ---------------------------------------------------------------------- timing factors
def rs_value(ret, use_1y=True):
    if not ret:
        return None
    m3, m6, y1 = ret.get("3M"), ret.get("6M"), ret.get("1Y")
    if m3 is None or m6 is None:
        return None
    if not use_1y or y1 is None:
        return (0.4 * m3 + 0.3 * m6) / 0.7
    return 0.4 * m3 + 0.3 * m6 + 0.3 * y1


def factor_L(t, bench, flags):
    ret = t.get("returns") or {}
    has_1y = ret.get("1Y") is not None
    if not has_1y:
        flags.append("L: no 1Y return, RS from 3M/6M only")
    rs_s, rs_b = rs_value(ret, has_1y), rs_value(bench, has_1y)
    if rs_s is None or rs_b is None:
        flags.append("L: returns missing, factor dropped")
        return None, {}
    d = rs_s - rs_b
    return interp(d, RS_DELTA_PTS), {"rs_delta_pp": r1(d)}


def factor_E(t):
    price, ma50, hi = t.get("price"), t.get("ma50"), t.get("year_high")
    ext = (price / ma50 - 1) * 100 if price and ma50 else None
    off = (1 - price / hi) * 100 if price and hi else None
    return mean([interp(ext, EXT_10W_PTS), interp(off, OFF_HIGH_PTS)]), ext, off


def market_read(market):
    """Weekly stage of each index; the weaker one sets M."""
    reads = {}
    for sym, d in (market or {}).items():
        st = weekly_stage(d.get("price"), d.get("ma50"), d.get("ma200"), d.get("returns"))
        if st:
            reads[sym] = st
    if not reads:
        return None, None, reads
    worst_sym = min(reads, key=lambda k: reads[k]["score"])
    return worst_sym, reads[worst_sym], reads


def market_regime(reads):
    """Gate for new buys, over both indexes. Returns (regime, symbols, note).

    stage4  - any index below a falling 40-wk: no new buys
    below40 - any index below its 40-wk, or less than CONFIRM_PCT above it: no new buys
    repair  - every index confirmed above its 40-wk, but at least one 40-wk is still
              falling (reclaimed after a decline): starter buys in leaders only
    ok      - every index confirmed above a flat or rising 40-wk: normal rules

    Lessons from replaying the 2000-02, 2007-09, 2020 and 2022 bears on S&P 500 and
    Nasdaq weekly closes (backtest_market.py, fixtures/):
    - "Below a flat 40-wk" is not a Stage 1 base. In Jan 2008 and Apr-May 2022 it was the
      rollover into the bear market. Real bottoms formed while the 40-wk was still falling.
    - Every false re-entry during those bears (Dec 2007, May 2008, Feb/Mar/Apr 2022) was
      a close within ~1.2% of the 40-wk. Requiring a 2% margin removed all five and
      delayed the real re-entries by 0-5%. Any margin from 1.5% to 3% removes the same
      five and gives the same re-entry weeks, so 2% is not a fitted knife-edge.
    - Requiring both indexes removed the S&P-only false buys of Mar 2002 and Jan 2022.
      Slow tops still leak: the gate was open on and off through mid-2000 while the S&P
      chopped near its high (the Nasdaq was too far above its own 40-wk to help).
    """
    if not reads:
        return None, [], ""
    s4 = [k for k, v in reads.items() if v["stage"] == 4]
    if s4:
        return "stage4", s4, f"{index_names(s4)} in a Stage 4 downtrend, no new buys"
    below = [k for k, v in reads.items() if v["pct_vs_40"] < CONFIRM_PCT]
    if below:
        parts = []
        for k in below:
            v, nm = reads[k], INDEX_NAMES.get(k, k)
            if v["above40"]:
                parts.append(f"{nm} only {v['pct_vs_40']:+.1f}% above its 40-wk MA, not confirmed until a "
                             f"weekly close above {v['ma40'] * (1 + CONFIRM_PCT / 100):,.0f}")
            else:
                parts.append(f"{nm} below its 40-wk MA")
        return "below40", below, "; ".join(parts) + ", no new buys"
    repairing = [k for k, v in reads.items() if v["slope_40w"] == "falling"]
    if repairing:
        return ("repair", repairing,
                "market repairing (back above a still-falling 40-wk), starter buys in leaders only")
    return "ok", [], ""


def index_names(syms):
    return " and ".join(INDEX_NAMES.get(s, s) for s in syms)


# ---------------------------------------------------------------------------- thesis
def core_auto(quarters, annual):
    q_rev = [yoy(q.get("rev"), q.get("rev_ya")) for q in (quarters or [])[:2]]
    fy_rev = yoy(annual[-1].get("rev"), annual[-2].get("rev")) if annual and len(annual) >= 2 else None
    mdelta = None
    if annual and len(annual) >= 2:
        a0, a1 = annual[0], annual[-1]
        if a0.get("op_inc") is not None and a0.get("rev") and a1.get("op_inc") is not None and a1.get("rev"):
            mdelta = (a1["op_inc"] / a1["rev"] - a0["op_inc"] / a0["rev"]) * 100
    if not q_rev or q_rev[0] is None:
        return None
    two_down = len(q_rev) >= 2 and None not in q_rev and q_rev[0] < 0 and q_rev[1] < 0
    if two_down or (mdelta is not None and mdelta < -8):
        return "fail"
    if q_rev[0] < 5 or (fy_rev is not None and fy_rev < 0) or (mdelta is not None and mdelta < -3):
        return "watch"
    return "pass"


def balance_auto(t, annual):
    chg, split = share_change(annual)
    if split:
        chg = None
    nd, fcf = t.get("net_debt_to_ebitda"), t.get("fcf_yield")
    ebitda = annual[-1].get("ebitda") if annual else None
    if chg is None and nd is None and fcf is None:
        return None
    neg_fcf = fcf is not None and fcf < 0
    if (chg is not None and chg > 5) or (nd is not None and nd > 4 and neg_fcf):
        return "fail"
    if ((chg is not None and chg > 1) or (nd is not None and nd > 2) or neg_fcf
            or (ebitda is not None and ebitda <= 0)):
        return "watch"
    return "pass"


def thesis_read(t, quarters, annual):
    raw = t.get("thesis") or {}
    ans = {}
    for k in ("core", "capital", "balance", "moat"):
        v = raw.get(k, "auto" if k in ("core", "balance") else None)
        if v == "auto":
            v = core_auto(quarters, annual) if k == "core" else balance_auto(t, annual)
        ans[k] = v if v in ("pass", "watch", "fail") else None
    vals = list(ans.values())
    unknown = sum(v is None for v in vals)
    if ans["core"] == "fail" or ans["moat"] == "fail":
        label = "Broken"
    elif ("fail" in (ans["capital"], ans["balance"]) or "watch" in (ans["core"], ans["moat"])
          or vals.count("watch") >= 2):
        label = "At Risk"
    else:
        label = "Intact"
    return {"label": label, "answers": ans, "low_confidence": unknown >= 2}


# --------------------------------------------------------------------------- actions
def is_leader(is_etf, q, thesis, stage, rs_delta, rs_applies):
    """Leader = own-it-for-years fundamentals + its own Stage 2 chart + beating the S&P 500.

    All four are required. RS alone is only 30% of Timing, so without this gate a stock
    lagging the market could still score a Buy on trend and market strength.
    """
    quality_ok = is_etf or (q is not None and q >= QUALITY_BUY)
    thesis_ok = is_etf or thesis == "Intact"
    stage2 = bool(stage) and stage["stage"] == 2 and stage["above40"]
    rs_ok = (not rs_applies) or (rs_delta is not None and rs_delta >= LEADER_RS_PP)
    return quality_ok and thesis_ok and stage2 and rs_ok


def new_money(is_etf, q, thesis, timing, stage, ext, rs_delta, rs_applies, regime, regime_syms,
              regime_note, ma10, ma40, earn_days):
    if not is_etf:
        if thesis == "Broken":
            return "Avoid", "thesis Broken"
        if q is not None and q < QUALITY_FLOOR:
            return "Avoid", f"Quality {q} is below {QUALITY_FLOOR}, not a 2-5 yr holding"
    if stage and stage["stage"] == 4:
        return "Avoid", "weekly Stage 4 downtrend"

    leader = is_leader(is_etf, q, thesis, stage, rs_delta, rs_applies)
    buy_ok = regime in ("ok", "repair", None)
    names = index_names(regime_syms)
    soon = earn_days is not None and 0 <= earn_days <= EARNINGS_WINDOW
    earn = f"; earnings in {earn_days}d, start half size or wait for the report" if soon else ""

    # Extension is checked first: a strong trend + RS can carry Timing past 70 even when
    # the stock is far above its 10-wk line, and buying there is chasing.
    if leader and buy_ok and ext is not None and ext > EXTENDED_PCT:
        return "Buy on pullback", f"extended {ext:.0f}% above the 10-wk MA; wait for a pullback toward {money(ma10)}{earn}"
    if leader and regime == "repair":
        tail = f"; earnings in {earn_days}d, consider waiting for the report" if soon else ""
        return "Buy (starter)", (f"market repairing: the {names} is back above a still-falling 40-wk MA "
                                 f"and this leader is already in Stage 2; half size now, add the rest "
                                 f"once that 40-wk flattens or turns up{tail}")
    if leader and buy_ok and timing is not None and timing >= TIMING_BUY:
        return "Buy", f"leader in Stage 2 above the 10/40-wk MAs, not extended{earn}"

    reasons = []
    if not is_etf and q is not None and q < QUALITY_BUY:
        reasons.append(f"Quality {q} is under the {QUALITY_BUY} bar")
    if not is_etf and thesis == "At Risk":
        reasons.append("thesis At Risk, let the next quarter resolve it")
    if stage:
        if not stage["above40"]:
            reasons.append(f"wait for a weekly close above the 40-wk MA ({money(ma40)})")
        elif not stage["above10"]:
            reasons.append(f"wait for a weekly close back above the 10-wk MA ({money(ma10)})")
        elif stage["stage"] != 2:
            reasons.append(f"{stage['label']}, wait for Stage 2")
    if rs_applies and rs_delta is not None and rs_delta < LEADER_RS_PP:
        reasons.append(f"not a leader yet: RS {rs_delta:+.0f}pp vs the S&P 500 (needs +{LEADER_RS_PP})")
    if regime_note:
        reasons.append(regime_note)
    if not reasons:
        reasons.append("wait for a new base or breakout")
    if soon:
        reasons.append(f"earnings in {earn_days}d")
    return "Watchlist", "; ".join(reasons)


def holder(is_etf, q, thesis, stage, ma40):
    if not is_etf and thesis == "Broken":
        return "Exit", "thesis Broken, the reason to own it is gone"
    if stage and stage["stage"] == 4:
        if not is_etf and thesis == "At Risk":
            return "Exit", "weekly Stage 4 and thesis At Risk"
        tail = ", thesis still Intact" if thesis == "Intact" else ""
        return "Reduce", f"weekly Stage 4 (below a falling 40-wk MA){tail}; rebuild on a weekly close above {money(ma40)}"
    reasons = []
    if not is_etf and thesis == "At Risk":
        reasons.append("thesis At Risk, revisit after the next report")
    if stage and not stage["above40"]:
        reasons.append(f"below the 40-wk MA ({money(ma40)}); exit if the 40-wk turns down (Stage 4)")
    if not is_etf and q is not None and q < QUALITY_FLOOR:
        reasons.append(f"Quality has slipped to {q}")
    if reasons:
        return "Hold, re-check", "; ".join(reasons)
    return "Hold", f"thesis and weekly trend intact; first warning is a weekly close below the 40-wk MA ({money(ma40)})"


# ------------------------------------------------------------------------------ main
def score_ticker(t, market, as_of):
    flags = []
    is_etf = t.get("type", "stock") == "etf"
    price, ma50, ma200 = t.get("price"), t.get("ma50"), t.get("ma200")
    quarters, annual = t.get("quarters") or [], t.get("annual") or []

    # --- market (shared) and benchmark for RS
    worst_sym, worst, mreads = market_read(market)
    bench = t.get("benchmark_returns") or ((market or {}).get("^GSPC") or {}).get("returns")

    # --- timing
    stage = weekly_stage(price, ma50, ma200, t.get("returns"))
    if stage and stage["slope_approx"]:
        flags.append("W: 40-wk slope approximated from the 10-wk/40-wk cross (6M/1Y returns missing)")
    etf_class = t.get("etf_class", "equity")
    if is_etf and etf_class in ("bond", "commodity", "currency", "other"):
        flags.append(f"L: {etf_class} ETF, RS vs the S&P 500 is not meaningful, factor dropped")
        L, ldet = None, {}
    else:
        L, ldet = factor_L(t, bench, flags)
    if is_etf and etf_class == "leveraged":
        flags.append("leveraged ETF: RS and drawdowns are amplified, decays in chop")
    E, ext, off = factor_E(t)
    tf = {"W": stage["score"] if stage else None, "L": L, "E": E,
          "M": worst["score"] if worst else None}
    timing = to99(weighted(tf, TIMING_WEIGHTS))
    # Market gate: no new buys while either index is below its 40-wk MA; starter buys in
    # leaders once both are back above it but a 40-wk is still falling (see market_regime).
    regime, regime_syms, regime_note = market_regime(mreads)
    if regime is None:
        flags.append("market data missing, market rule not applied")
    if timing is not None:
        if regime == "stage4":
            timing = min(timing, 49)
        elif regime in ("below40", "repair"):
            timing = min(timing, 69)
    if timing is not None and (tf["W"] is None or tf["L"] is None):
        timing = min(timing, 69)
        flags.append("Timing capped at 69: W or L missing")

    # --- quality (stocks only)
    quality, qf, qdet, val_det, thesis = None, {}, {}, {}, None
    if not is_etf:
        A, adet = factor_A(annual, flags)
        C, cdet = factor_C(quarters, flags)
        R, rdet = factor_R(t, annual, flags)
        S, sdet = factor_S(t, annual, flags)
        qf = {"A": A, "C": C, "R": R, "S": S, "N": factor_N(t, flags), "I": factor_I(t, flags)}
        qdet = {"A": adet, "C": cdet, "R": rdet, "S": sdet}
        raw = weighted(qf, QUALITY_WEIGHTS)
        pen, val_det = valuation(t, adet.get("eps_cagr"), flags)
        quality = to99(None if raw is None else raw + pen)
        if quality is not None and (A is None or C is None):
            quality = min(quality, 69)
            flags.append("Quality capped at 69: A or C missing")
        thesis = thesis_read(t, quarters, annual)

    # --- earnings proximity
    earn_days, nxt = None, t.get("next_earnings")
    if nxt:
        try:
            earn_days = (date.fromisoformat(nxt) - as_of).days
        except ValueError:
            flags.append(f"next_earnings '{nxt}' is not YYYY-MM-DD")

    # --- confidence
    allf = {**qf, **tf}
    missing = {k for k, v in allf.items() if v is None}
    extra = (set(t.get("web_sourced", [])) | missing) - {"N", "I"}
    core_missing = bool(missing & ({"W", "L"} if is_etf else {"A", "C", "W", "L"}))
    confidence = "Low" if core_missing or len(extra) >= 3 else ("Medium" if extra else "High")

    # --- actions
    tl = thesis["label"] if thesis else None
    rs_delta = ldet.get("rs_delta_pp")
    rs_applies = not (is_etf and etf_class in ("bond", "commodity", "currency", "other"))
    leader = is_leader(is_etf, quality, tl, stage, rs_delta, rs_applies)
    nm_action, nm_note = new_money(is_etf, quality, tl, timing, stage, ext, rs_delta, rs_applies,
                                   regime, regime_syms, regime_note, ma50, ma200, earn_days)
    h_action, h_note = holder(is_etf, quality, tl, stage, ma200)

    # --- presentation
    tk = t.get("ticker", "?")
    head = [f"**{tk} — {nm_action}**", money(price)]
    if off is not None:
        head.append(f"{off:.0f}% off 52-wk high")
    if nxt:
        head.append(f"earnings {nxt}" + (f" (in {earn_days}d)" if earn_days is not None and earn_days >= 0 else ""))
    line2 = []
    if not is_etf:
        line2.append(f"Quality {quality if quality is not None else 'n/a'}")
    line2.append(f"Timing {timing if timing is not None else 'n/a'}")
    if rs_delta is not None:
        line2.append(f"RS {rs_delta:+.0f}pp vs S&P" + (" (leader)" if leader else ""))
    if thesis:
        line2.append(f"Thesis {tl}" + (" (low confidence)" if thesis["low_confidence"] else ""))
    if stage:
        line2.append(f"Weekly: {stage['label']} (10-wk {money(ma50)} · 40-wk {money(ma200)})")

    def fmt(keys, src):
        return " · ".join(f"{k} {'–' if src.get(k) is None else round(src[k])}" for k in keys)

    parts = []
    if not is_etf:
        parts.append(fmt(["A", "C", "R", "S", "N", "I"], qf))
    parts.append(fmt(["W", "L", "E", "M"], tf))
    parts.append(f"conf {confidence}")
    web = sorted(set(t.get("web_sourced", [])))
    if web:
        parts.append("web: " + ", ".join(web))
    factor_line = " | ".join(parts)

    return {
        "ticker": tk,
        "type": "etf" if is_etf else "stock",
        "summary_lines": [
            " · ".join(head),
            " · ".join(line2),
            f"New money: {nm_action}. {nm_note[0].upper() + nm_note[1:]}",
            f"If you hold: {h_action}. {h_note[0].upper() + h_note[1:]}",
        ],
        "factor_line": factor_line,
        "quality": quality,
        "timing": timing,
        "leader": leader,
        "new_money": {"action": nm_action, "note": nm_note},
        "holder": {"action": h_action, "note": h_note},
        "thesis": thesis,
        "weekly": stage,
        "market": {"regime": regime, "weakest": worst_sym, "reads": {k: {"stage": v["stage"], "label": v["label"],
                                                      "score": v["score"]} for k, v in mreads.items()}},
        "factors": {k: r1(v) for k, v in allf.items()},
        "details": {**qdet, "L": ldet, "valuation": val_det,
                    "ext_10w_pct": r1(ext), "off_high_pct": r1(off), "earnings_in_days": earn_days},
        "confidence": confidence,
        "flags": flags,
    }


def run(data):
    as_of = date.fromisoformat(data["as_of"]) if data.get("as_of") else date.today()
    market = data.get("market") or {}
    tickers = data.get("tickers")
    if tickers is None:  # single-ticker input: the root object is the ticker
        tickers = [{k: v for k, v in data.items() if k not in ("market", "as_of")}]
    return [score_ticker(t, market, as_of) for t in tickers]


def main(argv):
    src = open(argv[1]) if len(argv) > 1 else sys.stdin
    with src:
        data = json.load(src)
    json.dump(run(data), sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main(sys.argv)
