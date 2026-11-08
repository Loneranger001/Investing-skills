# Output schema (v2): for dashboards

`verdict.py input.json --out DIR` writes two files a dashboard can read. Both are plain
JSON; nothing else is needed.

| File | What | Update pattern |
|---|---|---|
| `DIR/latest.json` | the full result of the latest run (below) | overwritten each run |
| `DIR/history.jsonl` | one compact record per `as_of` date, oldest first | upserted: a re-run on the same date replaces that line |
| `DIR/dashboard.html` | `render_dashboard.py DIR` output: self-contained, no network | regenerated each run |

**Versioning.** `schema_version` is an integer. Additive changes (new keys) keep the
number; renaming, removing or changing the meaning of a key bumps it. Dashboards should
check it and ignore keys they don't know. Values are numbers or strings; any value can be
`null` when its input was missing. Percentages are in percent (`5.4` = 5.4%), prices in
the instrument's currency, money in dollars.

## latest.json

```jsonc
{
  "schema_version": 2,
  "generated_at": "2026-11-08T02:58:48+00:00",   // UTC, when the script ran
  "as_of": "2026-11-07",                         // the market date the data is for
  "mode": "full",                                // "full" | "quick"

  "verdict": {
    "label": "Exercise Caution",       // Buy More | Buy | Exercise Caution | Pause
    "kind": "Exercise Caution",        // label, or "pullback" / "repair" for the two Buy More cases
    "regime": "below40",               // canslim market gate: ok | repair | below40 | stage4
    "why": "...", "next": "...", "do": "...",       // sentences for display
    "contribution_pct": 50,            // share of this period's contribution to invest
    "reserve_deploy_pct": 0,           // share of the cash reserve to deploy
    "stats": StatsRow,                 // what followed weeks with this verdict, 2000-23
    "divergence": null                 // a sentence when health disagrees with the trend
  },

  "market": {
    "indexes": {                       // always ^GSPC and ^IXIC
      "^GSPC": {
        "name": "S&P 500", "price": 7378.9, "ma10": 7686.53, "ma40": 7322.74, "year_high": 7801.2,
        "off_high_pct": 5.4, "pct_vs_10": -4.0, "pct_vs_40": 0.8,
        "slope_40w": "rising",          // rising | flat | falling
        "stage": 2, "stage_label": "Stage 2 pullback below 10-wk", "trend_score": 72,
        "returns": {"3M": -4.29, "6M": 0.19, "1Y": 9.8},
        "levels": {"confirm_40w": 7469.19, "pullback": 7411.14, "bear_line": 6240.96},
        "entry": Entry, "stats": StatsRow
      },
      "^IXIC": { ... }
    },
    "stats_period": "2000-01-07 to 2023-06-30"
  },

  "health": {
    "score": 56, "label": "Mixed",     // 0-100; Healthy >= 70, Mixed >= 50, Weak >= 30, else Stressed
    "coverage": "5/5",                 // scored areas with data
    "internals_score": 57, "internals_label": "Mixed",   // health without trend
    "categories": [                    // scored, fixed order: trend, participation, volatility, credit, curve
      {"key": "trend", "name": "Trend", "weight": 40, "score": 54, "status": "neutral",   // good | neutral | weak
       "read": "...", "items": [HealthItem, ...]}
    ],
    "context": [                       // unscored: valuation, sentiment, leadership
      {"key": "valuation", "name": "Valuation", "status": "rich", "read": "...", "items": [HealthItem, ...]}
    ]
  },

  "core": [CoreRow, ...],              // sorted by weight, largest first
  "satellite": [SatelliteRow, ...],
  "sleeves": {"core_pct": 95.5, "satellite_pct": 4.5, "satellite_target_pct": 20},   // null without weights
  "plan": {"amount": 2000, "invest": 1000, "from_reserve": 0, "to_reserve": 1000,
           "reserve_after": 4000, "split": {"QQQ": 1000}},                           // null without an amount
  "actions": ["Sell XYZ: Exit"],       // sells and trims only
  "flags": ["..."],                    // data gaps and assumptions, for display
  "text": { ... }                      // markdown lines and tables for chat (see SKILL.md)
}
```

### Shared shapes

```jsonc
// StatsRow: what followed weeks in the same state, 2000-2023 (references/entry_stats.json)
{"episodes": 59,                       // separate runs of weeks; judge a row by this, not n
 "fwd_13w": Dist, "fwd_26w": Dist, "fwd_52w": Dist}
// Dist: forward % price return
{"n": 93, "median": 7.0, "mean": 7.3, "pct_positive": 76, "p10": -5.2, "worst": -28.8, "best": 31.2}

// Entry: where an index or fund sits on its own weekly chart
{"bucket": "up_5_10",                  // see ENTRY_LABELS in verdict.py (11 buckets)
 "label": "Uptrend, 5-10% pullback (buy zone)",
 "off_high_pct": 7.8, "pct_vs_40": 3.0, "pct_vs_10": -2.1,
 "stage": 2, "stage_label": "...", "slope_40w": "rising"}

// HealthItem
{"key": "vix", "label": "VIX", "value": 22.6, "display": "22.6",
 "score": 47, "status": "neutral"}     // score/status null for display-only items

// CoreRow
{"ticker": "SPMO", "sleeve": "core", "held": true, "price": 108.2,
 "verdict": "Exercise Caution", "do": "Half the usual amount", "why": "...",
 "weight_pct": 30.9,                   // share of the whole portfolio
 "core_weight_pct": 32.3, "target_pct": 30.0,   // share of the core vs target (rescaled to sum 100)
 "value": 50854.0, "rs_pp": 0.7, "timing": 61,
 "chart": "Stage 2 pullback below 10-wk",
 "entry": Entry, "stats": StatsRow,
 "levels": {"high": 117.4, "ma10": 110.5, "ma40": 105.0, "confirm_40w": 107.1,
            "zone_low": 107.1, "zone_high": 111.53,   // buy zone; null when the 40-wk is too close to the high
            "bear_line": 93.92,
            "to_zone_pct": null},       // % move down to reach the zone; null when in or below it
 "zone": "In the zone now ($107.10–$111.53)"}

// SatelliteRow
{"ticker": "NVDA", "sleeve": "satellite", "held": true, "price": 186.64,
 "verdict": "Pause", "do": "Hold; no new money", "why": "...", "read": "Q 90 · T 32 · ...",
 "weight_pct": 4.5, "value": 7465.6, "rs_pp": -10.5, "entry": Entry,
 "canslim": {"new_money": {"action": "Watchlist", "note": "..."},
             "holder": {"action": "Hold, re-check", "note": "..."},
             "quality": 90, "timing": 32, "thesis": "At Risk", "stage": 2, "confidence": "High"}}
```

## history.jsonl

One JSON object per line, sorted by `as_of`:

```json
{"as_of": "2026-11-07", "mode": "full", "verdict": "Exercise Caution", "kind": "Exercise Caution",
 "health": 56, "health_label": "Mixed",
 "indexes": {"^GSPC": {"price": 7378.9, "pct_vs_40": 0.8, "off_high_pct": 5.4},
             "^IXIC": {"price": 24579.42, "pct_vs_40": -2.0, "off_high_pct": 9.7}},
 "holdings": {"QQQ": {"verdict": "Exercise Caution", "price": 560.1}, "...": {}},
 "plan": {"invest": 1000, "to_reserve": 1000, "reserve_after": 4000}}
```

## Wiring it into your own dashboard

- Point the dashboard at `DIR` (a mounted volume or synced folder). Read `latest.json`
  for current state and `history.jsonl` for time series; both are small (tens of KB).
- Status colours: map `verdict.label` → Buy More / Buy = good, Exercise Caution = warning,
  Pause = serious, Sell = critical; `health.categories[].status` → good / neutral / weak.
  Always pair a colour with its text label.
- Render `text.*` only where you want the same wording as chat; everything in it is also
  available as structured fields.
- Staleness: show `as_of` and `generated_at`. A file older than your run cadence means the
  skill didn't run.
