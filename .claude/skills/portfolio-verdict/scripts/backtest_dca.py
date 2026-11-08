#!/usr/bin/env python3
"""Replay the market verdict week by week, 2000-2023, and compare the plan with plain DCA.

Usage:
    python3 backtest_dca.py                  # summary: full period, sub-periods, verdict stats
    python3 backtest_dca.py --weeks 2008     # also print every week whose date starts with 2008
    python3 backtest_dca.py --cash 0.02      # reserve earns 2%/yr (default 0)

Data: fixtures/weekly_1999_2023.csv, S&P 500 and Nasdaq Composite weekly closes. 1999-2018
are the daily closes bundled with the `arch` Python package (Yahoo Finance source), taken
at the last trading day of each week; they match canslim's FMP fixtures to within 0.1%.
2019-2023 are canslim's FMP fixtures. The first 52 weeks only warm up the averages.

Weekly closes stand in for what the skill sees live: 10-wk SMA ~ priceAvg50, 40-wk SMA ~
priceAvg200, 26/52-wk changes ~ quote-change 6M/1Y, highest weekly close of 52 ~ yearHigh
(live uses the intraday high, so live drawdowns read ~0.5-1pp deeper).

The portfolio is a 50/50 S&P 500 / Nasdaq blend, a stand-in for a QQQ / SCHG / SPMO core,
price only (no dividends, which favours neither side much). Plain DCA invests 1 unit every
week. The plan invests by the verdict: Buy and Buy More 1 unit plus the reserve (all of it,
or half in a repair), Exercise Caution 0.5 (0.5 to the reserve), Pause 0 (1 to the reserve).
Both put in the same money; only the timing differs. Leftover reserve counts as cash.
"""
import csv
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import verdict  # noqa: E402

DATA = os.path.join(HERE, "fixtures", "weekly_1999_2023.csv")
PERIODS = [  # (label, first week, last week): each simulated on its own, from zero
    ("2000-23 full", "2000-01", "2023-12"),
    ("2000-03 dot-com bust", "2000-01", "2003-12"),
    ("2004-07 bull", "2004-01", "2007-06"),
    ("2007-10 GFC", "2007-07", "2010-12"),
    ("2011-19 bull + corrections", "2011-01", "2019-12"),
    ("2020-21 COVID V", "2020-01", "2021-12"),
    ("2022-23 bear + recovery", "2022-01", "2023-12"),
]
ORDER = ["Buy More", "Buy More (repair)", "Buy", "Exercise Caution", "Pause"]


def load(path=DATA):
    with open(path) as f:
        rows = list(csv.DictReader(f))
    return [r["date"] for r in rows], [float(r["spx"]) for r in rows], [float(r["ixic"]) for r in rows]


def index_block(c, i):
    p = c[i]
    return {"price": p, "ma50": sum(c[i - 9:i + 1]) / 10, "ma200": sum(c[i - 39:i + 1]) / 40,
            "year_high": max(c[i - 51:i + 1]),
            "returns": {"6M": (p / c[i - 26] - 1) * 100, "1Y": (p / c[i - 52] - 1) * 100}}


def verdicts(dates, spx, ndx):
    """Market verdict for every week from week 53 on: list of (i, date, mv)."""
    return [(i, dates[i], verdict.market_verdict({"^GSPC": index_block(spx, i), "^IXIC": index_block(ndx, i)}))
            for i in range(52, len(dates))]


def label(mv):
    return "Buy More (repair)" if mv["kind"] == "repair" else mv["verdict"]


def simulate(weeks, spx, ndx, first, last, cash_yield=0.0):
    """Plain DCA vs the plan over weeks whose date is in [first, last] (prefix compare)."""
    g = (1 + cash_yield) ** (1 / 52)
    plain = [0.0, 0.0]
    plan = [0.0, 0.0]
    reserve = max_reserve = 0.0
    n, end = 0, None
    for i, d, mv in weeks:
        if not (first <= d[:len(first)] and d[:len(last)] <= last):
            continue
        n, end = n + 1, i
        reserve *= g
        plain[0] += 0.5 / spx[i]
        plain[1] += 0.5 / ndx[i]
        invest = mv["contrib"]
        reserve += 1 - invest
        deploy = reserve * mv["deploy"]
        reserve -= deploy
        invest += deploy
        plan[0] += 0.5 * invest / spx[i]
        plan[1] += 0.5 * invest / ndx[i]
        max_reserve = max(max_reserve, reserve)
    pv = plain[0] * spx[end] + plain[1] * ndx[end]
    qv = plan[0] * spx[end] + plan[1] * ndx[end] + reserve
    return {"weeks": n, "plain": pv, "plan": qv, "diff": (qv / pv - 1) * 100,
            "reserve_end": reserve, "max_reserve": max_reserve}


def main(argv):
    cash = float(argv[argv.index("--cash") + 1]) if "--cash" in argv else 0.0
    show = argv[argv.index("--weeks") + 1] if "--weeks" in argv else None
    dates, spx, ndx = load()
    weeks = verdicts(dates, spx, ndx)

    if show:
        for i, d, mv in weeks:
            if d.startswith(show):
                r = mv["reads"]
                print(f"{d} {label(mv):18} S&P {spx[i]:7.0f} {r['^GSPC']['pct_vs_40']:+5.1f}% vs 40wk "
                      f"{r['^GSPC']['off_high_pct']:4.1f}% off hi | Nasdaq {ndx[i]:6.0f} "
                      f"{r['^IXIC']['pct_vs_40']:+5.1f}% {r['^IXIC']['off_high_pct']:4.1f}% off hi")
        print()

    print(f"Plan vs plain DCA, 50/50 S&P 500 / Nasdaq, reserve earns {cash * 100:.1f}%/yr\n")
    print(f"{'period':28} {'weeks':>5} {'plain':>8} {'plan':>8} {'plan vs plain':>13} {'max reserve':>12}")
    for name, a, b in PERIODS:
        s = simulate(weeks, spx, ndx, a, b, cash)
        print(f"{name:28} {s['weeks']:5d} {s['plain']:8.1f} {s['plan']:8.1f} {s['diff']:+12.1f}% "
              f"{s['max_reserve']:7.1f} wks")

    fwd = defaultdict(list)
    counts = defaultdict(int)
    flips, prev = 0, None
    for i, d, mv in weeks:
        k = label(mv)
        counts[k] += 1
        flips += prev is not None and mv["verdict"] != prev
        prev = mv["verdict"]
        if i + 26 < len(spx):
            fwd[k].append(50 * (spx[i + 26] / spx[i] + ndx[i + 26] / ndx[i]) - 100)
    years = len(weeks) / 52
    print(f"\n{len(weeks)} weeks; verdict changed {flips} times ({flips / years:.1f}/yr on weekly runs)")
    print("share of weeks and next-26-week blend return by verdict:")
    for k in ORDER:
        xs = sorted(fwd.get(k, []))
        if xs:
            print(f"  {k:18} {counts[k] / len(weeks) * 100:4.0f}% of weeks  n={len(xs):4d}  "
                  f"mean {sum(xs) / len(xs):+6.1f}%  median {xs[len(xs) // 2]:+6.1f}%  worst {xs[0]:+6.1f}%  "
                  f"share<0 {sum(x < 0 for x in xs) / len(xs) * 100:3.0f}%")


if __name__ == "__main__":
    main(sys.argv[1:])
