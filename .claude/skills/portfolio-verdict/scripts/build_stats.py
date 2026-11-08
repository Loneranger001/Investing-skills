#!/usr/bin/env python3
"""Build references/entry_stats.json: what followed each chart state and each verdict, 2000-2023.

Usage:
    python3 build_stats.py            # rewrite ../references/entry_stats.json
    python3 build_stats.py --print    # also print the tables

Two tables, both from fixtures/weekly_1999_2023.csv (see backtest_dca.py for the data):

- entry: every week of the S&P 500 and the Nasdaq, bucketed by verdict.entry_state (own
  trend x distance below the 52-wk high), with the index's own next 13/26/52-week price
  return. Pooled across the two indexes; QQQ, SCHG, SPMO and VOO all sit between them.
- verdict: every week's market verdict, with the next 13/26/52-week return of a 50/50
  S&P 500 / Nasdaq blend.

Weekly samples overlap heavily, so each row also counts episodes (separate runs of
consecutive weeks in that state). Judge a row by its episodes, not its weeks.
Re-run after any change to entry_state, weekly_stage or the market verdict.
"""
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_dca as bt  # noqa: E402
import verdict  # noqa: E402

OUT = os.path.join(HERE, "..", "references", "entry_stats.json")
HORIZONS = (13, 26, 52)


def summarize(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return None
    return {"n": n, "median": round(statistics.median(xs), 1), "mean": round(statistics.fmean(xs), 1),
            "pct_positive": round(sum(x > 0 for x in xs) / n * 100), "p10": round(xs[int(n * 0.1)], 1),
            "worst": round(xs[0], 1), "best": round(xs[-1], 1)}


def collect():
    dates, spx, ndx = bt.load()
    weeks = bt.verdicts(dates, spx, ndx)
    entry, verd = {}, {}
    prev_bucket, prev_verdict = {}, None
    for i, d, mv in weeks:
        for name, c in (("^GSPC", spx), ("^IXIC", ndx)):
            b = bt.index_block(c, i)
            st = verdict.entry_state(b["price"], b["ma50"], b["ma200"], b["year_high"], b["returns"])
            row = entry.setdefault(st["bucket"], {"episodes": 0, **{h: [] for h in HORIZONS}})
            if prev_bucket.get(name) != st["bucket"]:
                row["episodes"] += 1
            prev_bucket[name] = st["bucket"]
            for h in HORIZONS:
                if i + h < len(c):
                    row[h].append((c[i + h] / c[i] - 1) * 100)
        lab = bt.label(mv)
        row = verd.setdefault(lab, {"episodes": 0, **{h: [] for h in HORIZONS}})
        if prev_verdict != lab:
            row["episodes"] += 1
        prev_verdict = lab
        for h in HORIZONS:
            if i + h < len(spx):
                row[h].append(50 * (spx[i + h] / spx[i] + ndx[i + h] / ndx[i]) - 100)
    return dates[weeks[0][0]], dates[weeks[-1][0]], entry, verd


def table(rows, order):
    return {k: {"episodes": rows[k]["episodes"],
                **{f"fwd_{h}w": summarize(rows[k][h]) for h in HORIZONS}} for k in order if k in rows}


def build():
    first, last, entry, verd = collect()
    return {
        "generated_by": "scripts/build_stats.py",
        "period": f"{first} to {last}",
        "source": "S&P 500 and Nasdaq Composite weekly closes (fixtures/weekly_1999_2023.csv), price only",
        "note": "Forward % price returns. Weeks overlap: weigh a row by its episodes. Past behaviour of the "
                "index in a similar state, not a forecast.",
        "entry": table(entry, list(verdict.ENTRY_LABELS)),
        "verdict": table(verd, ["Buy More", "Buy More (repair)", "Buy", "Exercise Caution", "Pause"]),
    }


def main(argv):
    out = build()
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
        f.write("\n")
    if "--print" in argv:
        for name, tab in (("entry", out["entry"]), ("verdict", out["verdict"])):
            print(f"\n{name} ({out['period']})")
            for k, r in tab.items():
                s, y = r["fwd_26w"], r["fwd_52w"]
                lab = verdict.ENTRY_LABELS.get(k, k)
                print(f"  {lab[:52]:52} {r['episodes']:3d} ep  26w med {s['median']:+6.1f} pos {s['pct_positive']:3d}% "
                      f"p10 {s['p10']:+6.1f} (n={s['n']:4d}) | 52w med {y['median']:+6.1f} pos {y['pct_positive']:3d}%")
    print(f"wrote {os.path.normpath(OUT)}")


if __name__ == "__main__":
    main(sys.argv[1:])
