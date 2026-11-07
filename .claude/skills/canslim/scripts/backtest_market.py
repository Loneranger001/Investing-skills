#!/usr/bin/env python3
"""Replay the market gate over weekly index closes and show what the skill would have said.

Usage:
    python3 backtest_market.py [spx.csv [ixic.csv]]
    (default: fixtures/spx_weekly_2021_2023.csv, S&P 500 only)

CSV columns: date,close (one row per week, oldest first, >= 53 rows). With two files the
dates must match and the gate uses both indexes, as it does live. Weekly closes stand in for
what the skill sees live: 10-wk SMA ~ priceAvg50, 40-wk SMA ~ priceAvg200, 26/52-wk changes
~ quote-change 6M/1Y. fwd13w is the first index's return over the next 13 weeks; maxDD26w
is its worst close over the next 26 weeks. Run it on any change to weekly_stage or
market_regime before trusting the change.
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import score  # noqa: E402

GATE = {"stage4": "no buys", "below40": "no buys", "repair": "starter", "ok": "buy"}


def load(path):
    with open(path) as f:
        rows = list(csv.DictReader(f))
    return [r["date"] for r in rows], [float(r["close"]) for r in rows]


def reading(c, i):
    p = c[i]
    return score.weekly_stage(p, sum(c[i - 9:i + 1]) / 10, sum(c[i - 39:i + 1]) / 40,
                              {"6M": (p / c[i - 26] - 1) * 100, "1Y": (p / c[i - 52] - 1) * 100})


def replay(paths):
    """Yield (date, closes, readings, regime) per week from week 53 on."""
    series = [load(p) for p in paths]
    dates = series[0][0]
    for d, _ in series[1:]:
        if d != dates:
            raise SystemExit("index files must have identical dates")
    syms = ["^GSPC", "^IXIC"][:len(paths)]
    for i in range(52, len(dates)):
        reads = {s: reading(c, i) for s, (_, c) in zip(syms, series)}
        yield i, dates[i], [c for _, c in series], reads, score.market_regime(reads)[0]


def main(paths):
    lead = load(paths[0])[1]
    head = f"{'week':10} " + " ".join(f"{s:>22}" for s in ("S&P 500", "Nasdaq")[:len(paths)])
    print(head + f"  {'gate':8} {'fwd13w':>7} {'maxDD26w':>8}")
    for i, d, closes, reads, regime in replay(paths):
        cols = []
        for (sym, st), c in zip(reads.items(), closes):
            cols.append(f"{c[i]:8.0f} S{st['stage']} {st['slope_40w'][:4]:4} {st['pct_vs_40']:+5.1f}%")
        fwd = f"{(lead[i + 13] / lead[i] - 1) * 100:+6.1f}%" if i + 13 < len(lead) else "    n/a"
        dd = f"{(min(lead[i + 1:i + 27]) / lead[i] - 1) * 100:+7.1f}%" if i + 26 < len(lead) else "     n/a"
        print(f"{d:10} " + " ".join(f"{x:>22}" for x in cols) + f"  {GATE[regime]:8} {fwd} {dd}")


if __name__ == "__main__":
    args = sys.argv[1:] or [os.path.join(HERE, "fixtures", "spx_weekly_2021_2023.csv")]
    main(args)
