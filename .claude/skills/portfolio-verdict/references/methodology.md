# Methodology: portfolio verdicts

`scripts/verdict.py` is the source of truth; this file documents it. Every weekly-stage,
market-gate, thesis and holder rule comes from the canslim scorer
(`../../canslim/references/methodology.md`); this skill adds the verdict scale, the market
verdict, the core and satellite mappings, the size caps and the dollar plan. Change a
threshold in both places and re-run `test_verdict.py` and `backtest_dca.py`.

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

Not used, on purpose: valuation (CAPE, forward P/E), sentiment, VIX, yield curve and
credit spreads. None has a reliable weekly timing record, and each is easy to
over-interpret. An index far above its 40-wk is not a caution signal either: 2009–10 and
2020–21 stayed extended for months and kept rising. The synopsis can mention macro news
as context, but it doesn't change a verdict.

## Core ETFs

A core fund starts at the market verdict, then:

1. Its own weekly Stage 4 (below a falling 40-wk) → cap at **Pause**.
2. Its own price below its 40-wk → cap at **Exercise Caution**.
3. Overweight: its share of the **core** exceeds its target by more than `band_pp` (5) →
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
   contribution (contributions rebalance; nothing is sold). Without weights, the split
   follows the targets. If no core fund qualifies, the core share goes to the reserve.
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
  satellite mapping and caps, the dollar plan, pinned historical weeks, the backtest
  bounds, and a golden run of `example_input.json`. canslim's own suite still applies:
  `python3 -m unittest -v test_score.py` in `../canslim/scripts/`.
- `python3 backtest_dca.py [--weeks 2008] [--cash 0.02]` after any change to the market
  verdict, the contribution and reserve fractions, or canslim's `weekly_stage` or
  `market_regime`.
