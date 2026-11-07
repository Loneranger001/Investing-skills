#!/usr/bin/env python3
"""Replay the market gate over weekly index closes and show what the skill would have said.

Usage: python3 backtest_market.py [weekly_closes.csv]   (default: fixtures/spx_weekly_2021_2023.csv)

CSV columns: date,close (one row per week, oldest first, >= 53 rows). Weekly closes stand in
for what the skill sees live: 10-wk SMA ~ priceAvg50, 40-wk SMA ~ priceAvg200, 26/52-wk
changes ~ quote-change 6M/1Y. fwd13w is the index return over the next 13 weeks; maxDD26w is
the worst close over the next 26 weeks. Use it to check any change to weekly_stage or
market_regime against real history before trusting it.
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import score  # noqa: E402


def main(path):
    rows = list(csv.DictReader(open(path)))
    d, c = [r["date"] for r in rows], [float(r["close"]) for r in rows]
    gate = {"stage4": "no buys", "below40": "no buys", "repair": "starter", "ok": "buy"}
    print(f"{'week':10} {'close':>8} {'10wk':>8} {'40wk':>8} {'40wkΔ10w':>8} {'proxy':>7} "
          f"{'vs52wLo':>7}  {'weekly label':38} {'gate':8} {'fwd13w':>7} {'maxDD26w':>8}")
    for i in range(52, len(c)):
        p = c[i]
        ma10, ma40 = sum(c[i - 9:i + 1]) / 10, sum(c[i - 39:i + 1]) / 40
        ma40_prev = sum(c[i - 49:i - 9]) / 40
        st = score.weekly_stage(p, ma10, ma40, {"6M": (p / c[i - 26] - 1) * 100,
                                                "1Y": (p / c[i - 52] - 1) * 100})
        regime, _ = score.market_regime({"idx": st})
        fwd = f"{(c[i + 13] / p - 1) * 100:+6.1f}%" if i + 13 < len(c) else "    n/a"
        dd = f"{(min(c[i + 1:i + 27]) / p - 1) * 100:+7.1f}%" if i + 26 < len(c) else "     n/a"
        print(f"{d[i]:10} {p:8.0f} {ma10:8.0f} {ma40:8.0f} {(ma40 / ma40_prev - 1) * 100:+7.1f}% "
              f"{st['slope_40w']:>7} {(p / min(c[i - 51:i + 1]) - 1) * 100:+6.1f}%  "
              f"{st['label']:38} {gate[regime]:8} {fwd} {dd}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "fixtures", "spx_weekly_2021_2023.csv"))
