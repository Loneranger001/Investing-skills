# Methodology: portfolio verdicts

`scripts/verdict.py` is the source of truth; this file documents it. Every weekly-stage,
market-gate, thesis and holder rule comes from the canslim scorer
(`../../canslim/references/methodology.md`); this skill adds the verdict scale, the market
verdict, fund entry timing, the market-health panel, the core and satellite mappings, the
size caps and the dollar plan. Change a threshold in both places, re-run `build_stats.py`
if it touches a chart state or the verdict, and re-run `test_verdict.py` and
`backtest_dca.py`. The JSON contract for dashboards is in `output_schema.md`.

## The scale

Worst to best: **Sell · Pause · Exercise Caution · Buy · Buy More**. "Avoid" is Sell for a
ticker you don't hold. A cap means "no better than": a cap at Exercise Caution turns a Buy
into Exercise Caution and leaves a Pause alone.

## Market verdict (the headline, and the core)

From canslim's weekly read of the S&P 500 and the Nasdaq (`market_read` / `market_regime`:
10-wk ≈ `priceAvg50`, 40-wk ≈ `priceAvg200`, "confirmed" = a weekly close ≥ 2% above the
40-wk), plus each index's distance below its 52-wk high.

| Condition (first match) | Verdict | Contribution in | Reserve out |
|---|---|---|---|
| any index below a falling 40-wk (stage4) | **Pause** | 0% | 0% |
| any index below its 40-wk, or < 2% above it (below40) | **Exercise Caution** | 50% | 0% |
| all confirmed above, a 40-wk still falling (repair) | **Buy More** | 100% | 50% |
| ok, but an index ≥ 20% below its 52-wk high | **Exercise Caution** | 50% | 0% |
| ok, S&P 500 ≥ 5% below its 52-wk high | **Buy More** (pullback) | 100% | 100% |
| ok | **Buy** | 100% | 100% |

The money not invested goes to a **cash reserve** (money market or T-bills). The reserve
goes back in on Buy and Buy More, so over a full cycle the same money is invested; only the
timing changes.

- **Repair** is the first point after a decline where both indexes close 2% above their
  40-wk. Half the reserve goes in then, the rest once every 40-wk stops falling.
- **The 20% check** is for 2000: after the 1999 run the Nasdaq's 40-wk sat so far below
  price that a 34% drop still left the Nasdaq above it, and the gate read "ok" while the
  Nasdaq was in a bear market. With the check, most of Apr–Nov 2000 reads Exercise Caution
  instead of Buy; three weeks in July and September (Nasdaq 16–19% off its high) still read
  Buy. It barely moves the backtest, because the reserve it builds goes back in on those
  Buy weeks; it's there so the label isn't "Buy" during a Nasdaq bear. 20% is the
  conventional bear-market line, not a fitted value: 15% scores better (+3.7% vs +2.8%)
  only because it also catches those three weeks.
- **The pullback rule** uses the S&P 500, not the Nasdaq. A Nasdaq-only dip in a strong
  tape (Mar–Apr 2000) is more often a top than a dip.

Only the S&P 500 and the Nasdaq feed the verdict (`GATE` in `verdict.py`). Any other index
in the input (e.g. `^RUT`) goes to the health panel, so adding context can never move the
backtested gate.

Not in the verdict, on purpose: valuation (CAPE, forward P/E), sentiment, VIX, yield curve,
credit spreads and breadth. None has a reliable weekly timing record over the data
available here, and each is easy to over-interpret. They're in the health panel instead.
An index far above its 40-wk is not a caution signal either: 2009–10 and 2020–21 stayed
extended for months and kept rising.

## What followed each verdict

`scripts/build_stats.py` → `entry_stats.json`, 2000–2023. Next-26-week return of a 50/50
S&P 500 / Nasdaq blend after each verdict:

| Verdict | Episodes | Median | % up | Worst 10% |
|---|---|---|---|---|
| Buy More (pullback) | 14 | +6.4% | 86% | −0.1% |
| Buy More (repair) | 11 | +13.2% | 100% | +6.3% |
| Buy | 46 | +5.5% | 73% | −6.4% |
| Exercise Caution | 68 | +5.9% | 63% | −20.1% |
| Pause | 25 | +1.2% | 52% | −26.8% |

The verdicts separate **risk** far more than they separate typical returns: Caution's median
is no worse than Buy's, but its worst decile is three times deeper. That is the honest case
for the throttle: it trims exposure to the left tail, not the median. Every run shows the
row for the current verdict.

## Fund entry timing ("when does it make more sense to buy?")

Each fund, and each index, is placed in one of 11 chart states from its own weekly chart
(`entry_state`): trend (uptrend = confirmed above a flat or rising 40-wk; repair = above a
falling 40-wk; testing = below or within 2% of the 40-wk; downtrend = Stage 4) × distance
below the 52-wk high. `build_stats.py` records what followed every S&P 500 and Nasdaq
week in each state, 2000–2023 (pooled; QQQ, SCHG, SPMO and VOO all sit between the two):

| State | Episodes | 26w median | % up | Worst 10% | 52w median |
|---|---|---|---|---|---|
| Uptrend, within 5% of the high | 101 | +5.3% | 71% | −7.8% | +9.0% |
| **Uptrend, 5–10% pullback (buy zone)** | 59 | **+7.0%** | **76%** | **−5.2%** | **+10.7%** |
| Uptrend on paper, 10%+ off the high | 8 | −24.6% | 25% | −40.2% | −44.6% |
| Repair | 25 | +10.9% | 93% | +2.5% | +15.3% |
| Testing the 40-wk, within 5% of the high | 49 | +5.5% | 74% | −8.5% | +9.3% |
| Testing the 40-wk, 5–10% off | 96 | +6.2% | 69% | −9.2% | +10.6% |
| At or below the 40-wk, 10–20% off | 63 | +10.9% | 72% | −15.6% | +16.8% |
| Below the 40-wk, 20%+ off | 20 | −22.5% | 34% | −48.4% | −30.7% |
| Downtrend (Stage 4), within 10% of the high | 17 | +10.1% | 97% | +2.7% | +19.2% |
| Downtrend, 10–20% off | 38 | −9.4% | 28% | −35.9% | −15.4% |
| Downtrend, 20%+ off | 25 | +3.0% | 56% | −18.7% | +16.4% |

Weekly samples overlap, so read the episodes column, not the week count. What it supports:

- **The buy zone is real but modest.** A 5–10% pullback above a confirmed 40-wk beat
  buying near the high by ~1.7pp of median over 26 weeks, with a shallower bad case. Within
  a market that already reads Buy, a Nasdaq-only pullback added ~1pp (median +7.2% vs
  +6.3%, 40 weeks). So the skill **tilts** money toward a fund in its zone; it doesn't
  promise a timing edge.
- **Deep drops while still "above the 40-wk" are traps** (8 episodes, all Nasdaq, 5 of
  them in 2000): a parabolic run leaves the 40-wk far below price. No buy zone there.
- **Stage 4 10–20% off the high was the worst place to buy** (28% up). Pause is right there.
- **Shallow Stage 4 (within 10% of the high) and deep bear lows bought well**, but in
  hindsight only. The shallow row is 2004, 2006, 2011, 2015–16 and early 2019, plus one
  week in May 2008 that preceded the crash (its worst case, −31.5%). Tested and rejected:
  switching Pause to Caution when the market is within 10% of its high moved the backtest
  by ≤0.2pp.

**Buy zone and levels** (`buy_levels`): zone = 5–10% below the fund's 52-wk high, but never
below its 40-wk +2% (the confirm line); no zone if the 40-wk sits too close to the high.
Also reported: the 10-wk, 40-wk, confirm line and the −20% bear line, and how far price
must fall to reach the zone.

**The rule.** When the market verdict is **Buy** and a core fund is in `up_5_10`, that fund
is **Buy More**: it gets double weight in this period's split (drift caps still apply). A
fund in its zone while the market reads Caution or Pause stays at the market verdict; the
dashboard still shows it's in its zone.

## Market health (context, never the verdict)

Five scored areas, each 0–100, combined with fixed weights over whatever data is present
(coverage is reported; trend is always present):

| Area | Weight | Inputs → score |
|---|---|---|
| Trend | 40% | mean of the S&P 500 and Nasdaq weekly-stage scores (canslim W, 5–92) |
| Participation | 20% | mean of: % of S&P 500 above 200-day `20→0, 40→30, 50→50, 60→70, 75→100`; Russell 2000 weekly-stage score; equal-weight minus cap-weight 3M (RSP − SPY, pp) `−8→0, −5→30, −2→70, 0→90, 2→100` |
| Volatility | 15% | VIX `12→100, 16→85, 20→60, 25→35, 30→15, 40→0`; capped at 20 when VIX ≥ VIX3M (inverted term structure) |
| Credit | 15% | high-yield OAS % `3→100, 4→70, 5→40, 6→15, 8→0`, minus a widening penalty on the 3-month change `+0.25→0, +0.5→−15, +1.0→−30` |
| Yield curve | 10% | 10Y − 3M (10Y − 2Y if 3M missing), pp `−1→10, −0.5→25, 0→50, 0.25→70, 1→100` |

Status per area: ≥67 good, 34–66 neutral, <34 weak. Health label: ≥70 Healthy, 50–69
Mixed, 30–49 Weak, <30 Stressed. **Internals** = the same composite without trend.

Unscored context:
- **Valuation**: forward P/E vs its 10-yr average (< −10% cheap, ±10% fair, ≤ +25% rich,
  more very rich), CAPE (<20 / <30 / <35 / above), earnings yield minus the 10Y.
- **Sentiment**: CNN Fear & Greed (≤25 extreme fear … ≥75 extreme greed) and the AAII
  bull-bear spread (beyond ±20 = fearful/euphoric). Contrarian at the extremes.
- **Leadership**: average 3M return of offensive sectors (XLK, XLY, XLC, XLF, XLI) minus
  defensive (XLP, XLU, XLV, XLRE): > +2pp risk-on, < −2pp defensive, else mixed.

**Divergence note.** Trend says Buy or Buy More but internals < 40 → "stick to the usual
amount, skip spare cash". Trend says Pause but internals ≥ 65 → "a quick reclaim is
plausible, watch the levels". Neither changes the verdict or the dollar plan.

Why health isn't in the verdict: the thresholds are standard practitioner readings, not
fitted, and the free data available here can't test them across bears (VIX history in this
environment covers only 2014–18; the bond-spread series is monthly and covers two bears).
Wiring an untested score into the money decision would undo the point of a backtested
verdict. If a longer history becomes available, test one input at a time with
`backtest_dca.py` before promoting it.

## Core ETFs

A core fund starts at the market verdict, then:

1. Its own weekly Stage 4 (below a falling 40-wk) → cap at **Pause**.
2. Its own price below its 40-wk → cap at **Exercise Caution**.
3. Market verdict Buy and the fund in its own buy zone (`up_5_10`) → **Buy More** (see
   *Fund entry timing*).
4. Overweight: its share of the **core** exceeds its target by more than `band_pp` (5) →
   cap at **Pause** ("new money goes to the underweight funds"). Drift is measured within
   the core so that an under- or over-weight satellite doesn't make every fund look off.

A core fund never gets Sell. Selling the core on market signals was tested and rejected
(see the backtest below); rebalancing happens through where new money goes.

## Satellite (stocks and narrower ETFs)

canslim scores each holding (Quality, Timing, thesis, weekly stage, leader test, new-money
action, holder action). Mapping for a **held** position, first match wins:

| canslim | Verdict | Do |
|---|---|---|
| holder Exit (thesis Broken, or Stage 4 with thesis At Risk) | **Sell** | exit |
| holder Reduce (Stage 4, thesis Intact) | **Sell** | reduce by half; rebuild above the 40-wk |
| holder Hold, re-check (thesis At Risk, below the 40-wk, Quality < 55) | **Pause** | hold; no new money |
| new money Buy (leader, Stage 2, Timing ≥ 70, market ok) | **Buy More** (Buy in quick mode) | add a full tranche |
| new money Buy (starter) (repair market) | **Buy** | add half a tranche |
| new money Buy on pullback (> 20% above the 10-wk) | **Exercise Caution** | add only near the 10-wk |
| new money Watchlist (healthy, but not a leader or not an entry now) | **Exercise Caution** | hold; don't add yet |

A ticker you **don't hold** maps from canslim's new-money action alone: Buy → **Buy**
(start a position), Buy (starter) → **Buy** (half size), Buy on pullback → **Exercise
Caution**, Watchlist → **Pause** (not yet), Avoid → **Avoid**.

Then caps, in order:

1. Market verdict Exercise Caution or Pause → cap at the market verdict (Sell and Avoid
   stand).
2. Held position over `trim_position_pct` (8%) of the portfolio → **Sell**: trim to
   `max_position_pct` (5%), with the dollar amount.
3. Held position over `max_position_pct` (5%) → cap at **Exercise Caution** (no adds).
4. Satellite sleeve over `satellite_target_pct` + `band_pp` (25%) → cap at **Exercise
   Caution**; new money goes to the core.

**Quick mode** scores stocks trend-only (canslim's ETF path: stage, RS, extension, market;
no Quality or thesis). Buy More is out of reach without fundamentals, and a Stage 4 reads
"reduce" with a note that the full check decides reduce vs. exit.

## Dollar plan

Only when an amount is given (`portfolio.amount`, else `portfolio.contribution`).

```
invest_new   = amount × contribution-in            (table above)
from_reserve = cash_reserve × reserve-out
pool         = invest_new + from_reserve
to_reserve   = amount − invest_new
```

1. **Satellite share** = pool × `satellite_target_pct`, split over satellite rows rated Buy
   (weight 1) or Buy More (weight 2), each capped so it doesn't push the position past
   `max_position_pct`. If none qualify, the share goes to the core.
2. **Core** gets the rest, split over core funds rated Buy More, Buy or Exercise Caution,
   in proportion to how far each is below its target share of the core after the
   contribution (contributions rebalance; nothing is sold), with a fund rated Buy More (in
   its own buy zone) counted double. Without weights, the split follows the targets. If no
   core fund qualifies, the core share goes to the reserve.
3. Whole dollars, largest-remainder rounding, so the parts add up to the total exactly.

## Backtest

`scripts/backtest_dca.py` replays the market verdict on every week from Jan 2000 to Jun
2023 (`fixtures/weekly_1999_2023.csv`: S&P 500 and Nasdaq Composite weekly closes; 1999–2018
from the daily data bundled with the `arch` Python package, which matches canslim's FMP
fixtures to within 0.1%; 2019–2023 from canslim's FMP fixtures). Each period starts from
zero. The portfolio is a 50/50 S&P 500 / Nasdaq blend, price only. Plain DCA invests 1
unit a week; the plan follows the verdicts, with the reserve earning nothing.

| Period | Plan vs plain DCA | Reserve earns 2% | Most money held back |
|---|---|---|---|
| 2000–2023, full | **+2.8%** | +3.5% | 127 weeks of contributions |
| 2000–03 dot-com bust | +10.5% | +12.5% | 127 |
| 2004–07 bull | −1.2% | −1.1% | 15 |
| 2007–10 GFC | +3.3% | +4.0% | 75 |
| 2011–19 bull + corrections | −0.9% | −0.8% | 29 |
| 2020–21 COVID V | −1.6% | −1.6% | 10 |
| 2022–23 bear + recovery | −1.3% | −0.6% | 49 |

Monthly instead of weekly runs: +1.0% to +2.1% over the full period, depending on the
week of the month; bull periods cost −1.1% to −1.8%, V-shaped bears up to −3.6%.

What the numbers say:

- **It's insurance.** The edge comes from the two long bears (2000–03, 2007–09), where the
  reserve built during Pause went back in on the repair 12–39% off the low but far below
  where Pause began. In bull markets, every Caution or Pause stretch (2004, 2006, 2010,
  2011, 2015–16, 2018) ended with the index 0.5–6% higher than where it began, a small
  cost each time. In V-shaped bears
  (2020, 2022) Pause sat out part of the rebound.
- **Never-buy windows.** From Dec 2000, Jan 2008 and Jan 2022 to each bear's low, the
  verdict never said Buy or Buy More (pinned in `test_verdict.History`).
- **Forward returns by verdict** (next 26 weeks, blend): Buy More (pullback) n=21, mean
  +10.6%, 14% negative; Buy More (repair) n=32, mean +13.7%, none negative; Buy n=608, mean
  +4.2%; Exercise Caution n=267, mean +3.0%; Pause n=272, mean +0.2%, 48% negative. The
  pullback rule rests on 21 weeks, so treat it as plausible rather than proven.
- **How often it changes:** 6.9 verdict changes a year on weekly runs, about 3 on monthly runs.
  Most are one- or two-week Caution blips with an index sitting near its 40-wk, and each
  moves only half of one contribution.

### Variants tested (full period / long bears / bull periods)

| Variant | 2000–23 | 2000–03 | 2007–10 | 2011–19 | 2020–21 |
|---|---|---|---|---|---|
| **Default** | +2.8% | +10.5% | +3.3% | −0.9% | −1.6% |
| Caution invests 25% | +3.0% | +11.4% | +3.8% | −1.2% | −2.1% |
| Caution invests 75% | +2.6% | +9.6% | +2.7% | −0.6% | −1.2% |
| Only Pause throttles (Caution 100%) | +2.4% | +8.7% | +2.2% | −0.4% | −0.7% |
| Pause invests 50% | +1.6% | +6.2% | +2.2% | −0.7% | −1.3% |
| Repair deploys none of the reserve | −0.2% | +3.4% | −1.1% | −1.1% | −1.6% |
| Repair deploys all of it | +3.3% | +12.4% | +3.2% | −0.8% | −1.7% |
| Confirm margin 1% / 3% (default 2%) | +1.7% / +2.0% | +6.4% / +8.6% | +2.9% / +3.1% | −0.8% / −1.3% | −1.6% / −1.7% |
| **Sell 50% of the core on entering Pause** | **−10.3%** | +15.5% | +6.0% | **−11.6%** | −2.4% |
| **Sell 100% of the core on entering Pause** | **−18.0%** | +18.0% | +6.7% | **−15.5%** | −3.1% |

The defaults sit in the middle of a flat region: no single knob changes the sign, and the
best-scoring variants (deploy all on repair, Caution 25%) buy a little more upside in long
bears with a little more cost in V-shapes. Putting the reserve back in on repair is what
makes the throttle work: without it the plan loses. Selling the core is the one clearly
bad idea, and that's before capital-gains tax.

### Limits

- Price only, US large caps, one 23-year sample with three real bears. Dividends and
  T-bill interest on the reserve (both ignored) would shift results by tenths of a point.
- A 50/50 S&P / Nasdaq blend stands in for QQQ + SCHG + SPMO. Factor funds (SPMO) can lag
  badly in rebounds after bears (momentum reversals), which the blend doesn't capture.
- Live data uses the intraday 52-wk high, so live drawdowns read ~0.5–1pp deeper than
  the weekly-close backtest.
- The satellite rules are canslim's and are tested there; the satellite isn't in this
  backtest.

## Checking reliability

- `python3 -m unittest -v test_verdict.py` (in `scripts/`): market rules, core caps,
  satellite mapping and caps, entry states and buy zones, the health curves and divergence
  notes, the dollar plan, pinned historical weeks, the backtest bounds, the JSON contract
  and history upsert, the dashboard (including HTML escaping), a check that
  `entry_stats.json` matches a fresh `build_stats.py` run, and a golden run of
  `example_input.json`. canslim's own suite still applies: `python3 -m unittest -v
  test_score.py` in `../canslim/scripts/`.
- `python3 build_stats.py --print` after any change to `entry_state`, the market verdict or
  canslim's `weekly_stage`; commit the regenerated `entry_stats.json`.
- `python3 backtest_dca.py [--weeks 2008] [--cash 0.02]` after any change to the market
  verdict, the contribution and reserve fractions, or canslim's `weekly_stage` or
  `market_regime`.
