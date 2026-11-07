# Methodology: 2–5 year CAN SLIM with weekly-chart timing

`scripts/score.py` is the source of truth; this file documents it. If you change a
breakpoint, change it in both places and update the golden test in
`scripts/test_score.py` on purpose.

Every curve below is **piecewise-linear**: the score is interpolated between the listed
points and clamped at the ends. Notation `x→score`. Composites are weighted averages over
the factors that have data (missing ones are re-weighted away), then `×0.99`, rounded
half-up to an integer 0–99.

## Why it differs from stock IBD

| IBD CAN SLIM (months-long trades) | This skill (2–5 yr positions, weekly chart) |
|---|---|
| One composite score | **Quality** (own it for years?) and **Timing** (enter now?) kept separate |
| 50-day / 200-day MAs, daily signals | 10-wk / 40-wk MAs and weekly stage (`priceAvg50` ≈ 10-wk, `priceAvg200` ≈ 40-wk) |
| 8% stop, distribution days, RS dips as sells | Holder exits only on a Broken thesis or weekly Stage 4 |
| P/E ignored | Trailing-PEG penalty: over 2–5 years, the price paid matters |
| Market direction gates everything | Market gates **new buys only**; it never forces a long-term holder out |
| Float size, daily volume | Dropped: noise at this horizon |

## Quality (stocks only)

| Factor | Weight | What it measures |
|---|---|---|
| A: Annual growth | 30% | 3-yr EPS and revenue CAGR, consistency |
| C: Current quarters | 20% | Latest quarter YoY EPS and revenue, acceleration |
| R: Returns & margins | 15% | ROE (ROIC fallback), 3-yr operating-margin trend |
| S: Shares & balance sheet | 15% | Diluted share-count trend, net debt/EBITDA, FCF sign |
| N: New things | 10% | Catalyst: product, market, management, guidance |
| I: Institutional | 10% | 13F sponsorship trend |

### A: Annual growth

From `annual[]` (4 fiscal years → 3-yr CAGR).

- EPS CAGR % → `-10→0, 0→20, 10→45, 15→60, 25→80, 40→95, 60→100`, minus **8 per down
  year** in the EPS series.
- Revenue CAGR % → `-5→0, 0→15, 5→35, 10→55, 20→80, 30→95, 50→100`.
- A = 0.6·EPS + 0.4·revenue.
- Base-year EPS ≤ 0 but latest > 0 (turned profitable): A = 0.8·revenue score.
- Latest EPS ≤ 0: A = min(0.5·revenue score, 40).
- Fewer than 4 years (recent IPO): CAGR over what exists, flagged.

### C: Current quarters

From `quarters[]` (newest first, each with its year-ago quarter).

- **GAAP distortion check:** if latest-quarter EPS growth and operating-income growth
  differ by more than 25pp, score on operating-income growth for all quarters (flagged).
  Catches investment gains, impairments, and one-time tax items.
- EPS YoY % → `-20→0, 0→20, 10→40, 25→65, 40→85, 70→100`.
- Revenue YoY % → `-10→0, 0→20, 10→45, 20→70, 30→90, 50→100`.
- C = 0.65·EPS + 0.35·revenue.
- Acceleration: 3 quarters strictly rising → +8, strictly falling → −8; with only 2
  quarters, ±4. **Deceleration counts only when the latest rate is below 40%** (100% →
  70% is still elite growth for a long-term holder).
- Year-ago quarter was a loss (growth undefined) → EPS part = 70 (turnaround), flagged.
- Latest quarter is a loss → EPS part = 15 if narrowing, else 0; C = 0.4·EPS +
  0.6·revenue.

### R: Returns & margins

- ROE used when 0 < ROE ≤ 150%: ROE % → `-10→0, 0→10, 10→40, 17→70, 25→85, 40→100`.
  Otherwise (negative or tiny equity from buybacks) ROIC % →
  `-10→0, 0→10, 8→40, 12→60, 17→75, 25→90, 40→100`, flagged.
- Operating-margin change, oldest → newest FY, in pp → `-10→0, -3→30, 0→55, 3→75, 10→100`.
- R = 0.6·returns + 0.4·margin.

### S: Shares & balance sheet

- Diluted shares, %/yr (CAGR) → `-3→100, -1→85, 0→70, 1→60, 3→35, 8→10, 15→0`. A
  year-over-year jump >50% (or drop >33%) is treated as a possible unadjusted split: not
  scored, flagged.
- Net debt/EBITDA → `-0.5→100, 0→95, 1→85, 2→65, 3→40, 5→10`. Not scored if latest
  EBITDA ≤ 0.
- S = mean of the two, −15 if FCF yield < 0.

### N: New things and I: Institutional

- N: `major` 90 · `ordinary` 50 · `stale` 20 · omitted → dropped.
- I: trend `rising` 80 · `flat` 60 · `falling` 35, −20 if ownership < 20%. Trend unknown
  but % known: % → `10→25, 30→40, 60→65, 80→70`. Both unknown → dropped.

### Valuation check (2–5 yr specific)

Trailing PEG = (price / sum of last 4 quarters' diluted EPS) / min(3-yr EPS CAGR, 50).
Growth is capped at 50% because multi-hundred-percent CAGRs don't persist. Penalty on the
Quality composite before normalizing: PEG `2→0, 3→−5, 4→−10`. Not assessed when TTM EPS
≤ 0 or there's no positive growth (flagged). This is a check on overpaying, not a value
screen: CAN SLIM leaders usually look expensive.

## Timing (stocks and ETFs)

| Factor | Weight |
|---|---|
| W: Weekly stage | 40% |
| L: Relative strength vs. S&P 500 | 30% |
| E: Entry location | 15% |
| M: Market (weaker of S&P 500 / Nasdaq, same stage table) | 15% |

### W: Weekly stage

**40-wk MA slope**, from data already fetched. The change in a 200-day SMA over the last
50 days equals (today's 50-day SMA − the 50-day SMA from 200 days ago) / 4, and that old
50-day SMA is centred about 45 weeks back. So:

```
P26 = price / (1 + 6M%)      P52 = price / (1 + 1Y%)
P45 = exp( ln P26 + (19/26)·(ln P52 − ln P26) )       # log-interpolated
slope = rising if ma50 > 1.02·P45, falling if ma50 < 0.98·P45, else flat
```

Without 6M/1Y returns (IPO), slope = rising if ma50 > ma200, else falling (flagged).
"Prior uptrend" = 1Y return > 0.

| Price vs 40-wk | 40-wk slope | Other | Stage, label | Score |
|---|---|---|---|---|
| above | rising | 10-wk > 40-wk, above 10-wk | 2, uptrend | 92 |
| above | rising | 10-wk > 40-wk, below 10-wk | 2, pullback below 10-wk | 72 |
| above | rising | 10-wk < 40-wk, above 10-wk | 2, early (reclaimed 40-wk) | 75 |
| above | rising | 10-wk < 40-wk, below 10-wk | 2, early, below 10-wk | 55 |
| above | flat | prior uptrend | 3, top | 45 (+5 above 10-wk) |
| above | flat | no prior uptrend | 1, base | 55 (+5) |
| above | falling | | 1, repair | 45 (+5) |
| below | rising | | 2, correction below 40-wk | 35 (+5) |
| below | flat | prior uptrend | 3, breakdown | 25 (+5) |
| below | flat | no prior uptrend | 1, base below 40-wk | 30 (+5) |
| below | falling | | 4, downtrend | 5 (12 if 10-wk > 40-wk) |

### L, E, M

- **L:** `RS = 0.4·3M% + 0.3·6M% + 0.3·1Y%` for the stock and the benchmark (`^GSPC`, or
  `benchmark_returns` for web-sourced ETFs); ΔRS in pp →
  `-30→0, -10→25, 0→50, 10→70, 25→90, 40→100`. No 1Y return: both sides use
  `(0.4·3M + 0.3·6M)/0.7`. Dropped for bond, commodity, currency, or other non-equity ETFs.
- **E:** mean of (% above the 10-wk MA → `-15→20, -5→55, 0→80, 5→95, 10→90, 20→55,
  30→20, 40→5`) and (% below the 52-wk high → `0→100, 5→95, 15→75, 25→50, 40→15, 60→0`).
  Best entries are at or just above the 10-wk line near highs, not 30% extended.
- **M:** the weaker index's W score.

## Leader

A stock is a **leader** only if all four hold:

1. Quality ≥ 70 (worth owning for years),
2. thesis Intact,
3. its own weekly chart is in Stage 2 above the 40-wk MA,
4. weighted RS beats the S&P 500 by ≥ +10pp (L ≥ 70).

RS is only 30% of Timing, so without this explicit gate a stock trailing the market can
still reach Timing 70 on trend and market strength alone. +10pp is looser than IBD's RS
Rating ≥ 80 (a percentile rank against all stocks, which needs whole-market data this
skill doesn't have). Raise `LEADER_RS_PP` in `score.py` to tighten it. ETFs skip 1–2;
non-equity ETFs also skip 4.

## Market gate

Over both indexes (`market_regime` in `score.py`):

| Regime | Condition | New buys | Timing cap |
|---|---|---|---|
| ok | both indexes above a flat or rising 40-wk MA | normal rules | — |
| repair | both above their 40-wk, but at least one 40-wk is still falling | **starter (half-size) buys in leaders only** | 69 |
| below40 | any index below its 40-wk otherwise: under a rising 40-wk (correction) or a flat one | none | 69 |
| stage4 | any index below a falling 40-wk | none | 49 |

**Why "repair" and not "Stage 1 below the 40-wk".** A Stage 1 base can't be identified
reliably in real time. "Below a flat 40-wk after a down year" looks like one, but on the
S&P 500 in 2022 that state was the rollover *into* the bear market: Apr 29 to May 27, with
the index at fresh 52-wk lows on 4 of those 5 weeks, then another −13% to the October low.
An earlier version of this skill allowed starter buys there. The actual bottom formed
while the lagging 40-wk was still falling, so the first usable "buy cheap" signal was the
index **reclaiming** that falling line: Jan 13 2023 at 3,999, ~12% above the low and
about 4% below the level where the 40-wk flattened (Apr 28 2023, 4,169).
`scripts/backtest_market.py` replays every week; `test_score.MarketHistory` locks these
weeks in.

Known misses on the same data: the Mar 25 to Apr 1 2022 bear-market rally reclaimed a
still-rising 40-wk and read "ok" (the index then fell ~20%), and Dec 2 2022 read "repair"
for one week before slipping back. Any moving-average gate has these; the leader test and
starter sizing limit the damage. The weekly label for a flat 40-wk is also unreliable on
the Stage 1 vs Stage 3 question (Apr to Jun 2023 reads "Stage 3 top" at the start of a new
advance). It doesn't change the gate.

A Stage 1 *stock* is never a buy (it's Watchlist until it reaches Stage 2): its base can
last years or roll over, and its RS is weak by definition.

The market gate never applies to holders.

## Caps and missing data

- Market caps as in the table above.
- W or L missing → Timing capped at 69. A or C missing → Quality capped at 69.
- Any other missing factor is dropped and the rest re-weighted.

## Thesis (stocks only)

| Question | Source | pass | watch | fail |
|---|---|---|---|---|
| **core**: is the revenue engine growing and profitable? | auto | otherwise | latest-quarter revenue growth < 5%, latest FY revenue down, or op margin −3 to −8pp over 3 yrs | revenue down YoY in both of the last 2 quarters, or op margin down >8pp |
| **capital**: is spending disciplined? | judgment | stated, plausible payback | large unproven bet, big M&A | writedowns, value-destroying deals |
| **balance**: share count and leverage | auto | otherwise | dilution >1%/yr, ND/EBITDA >2, negative FCF, or EBITDA ≤ 0 | dilution >5%/yr, or ND/EBITDA >4 with negative FCF |
| **moat**: is the competitive position eroding? | judgment | no evidence of share or pricing loss | credible threat, no measurable damage yet | measurable share loss or impairing regulation |

Label: **Broken** if core or moat fails. **At Risk** if capital or balance fails, core or
moat is a watch, or there are ≥2 watches in total. Otherwise **Intact**. Two or more
unknown answers → "(low confidence)". Core and moat weigh most because a company survives
a bad capital cycle far more often than a shrinking core or a lost moat.

## Actions

**New money** (first match wins):

1. Thesis Broken, or Quality < 55 → **Avoid**. Weekly Stage 4 → **Avoid**.
2. Leader, regime ok or repair, and >20% above the 10-wk → **Buy on pullback** (level:
   the 10-wk MA). Checked first, because a strong trend and RS can lift Timing past 70
   even when the stock is extended.
3. Leader, regime repair → **Buy (starter)**: half size; add the rest once the falling
   40-wk flattens or turns up (regime ok).
4. Leader, regime ok, Timing ≥ 70 → **Buy**.
5. Anything else → **Watchlist**, with every reason that applies: Quality under 70, thesis
   At Risk, the weekly level to reclaim (40-wk, else 10-wk), not a leader (RS vs. the
   +10pp bar), the market gate.

Earnings within 14 days: a Buy gets "start half size or wait for the report", a starter
gets "consider waiting for the report", and a Watchlist gets the date.

**Holder:**

1. Thesis Broken → **Exit**.
2. Weekly Stage 4 → **Exit** if the thesis is At Risk; otherwise **Reduce** (rebuild on a
   weekly close back above the 40-wk).
3. Thesis At Risk, price below the 40-wk MA, or Quality < 55 → **Hold, re-check**.
4. Otherwise → **Hold**. The first warning is a weekly close below the 40-wk MA; the exit
   is the 40-wk turning down.

## Confidence

The count excludes N and I (always web-sourced on this plan). Any of A, C, W, L missing
(W, L for ETFs), or ≥3 other factors web-sourced or missing → **Low**. One or two →
**Medium**. None → **High**.

## Edge cases

- **Recent IPOs:** fewer than 4 annual statements and no 1Y return. Handled (CAGR over
  available years, RS from 3M/6M, slope from the MA cross), all flagged.
- **Foreign filers and ADRs:** many report semiannually (20-F/6-K), so quarterly YoY may
  not exist. Fill `quarters` with half-year periods if that's what's reported, and say so.
- **REITs, banks, insurers:** EPS and operating income are poor measures (use FFO for
  REITs). Score as normal but say in the synopsis that Quality is less meaningful.
- **Pre-revenue companies:** set `thesis.core` manually from commercial traction and cash
  runway; A and C will be low by construction.
- **Leveraged ETFs:** flagged. RS and drawdowns are amplified, and they decay in choppy
  markets: not a 2–5 yr holding.
- **Splits:** FMP statements are normally split-adjusted (verified on NVDA's 2024 10:1).
  The S-factor split guard catches the cases where they aren't.

## Data map and FMP plan behaviour

Verified 2026-11-07 on the user's plan:

- **The gate is `limit > 5`, not the endpoint.** Quarterly `income-statement` works at
  limit 5 and is denied at 8. `earnings-company` works at 5 and is denied at 10. Paging
  (`page`) is ignored, so use the `period: "Q<n>"` filter to reach older quarters (it
  returns the same fiscal quarter across years).
- **ETF symbols are blocked** on `quote` and `quote-change` regardless of limit. Indexes
  (`^GSPC`, `^IXIC`) work on `index-quote` and `quote-change`.
- **`quote` has no `avgVolume` or `sharesOutstanding`**; use the statements for share
  counts.
- **Trap in `historical-price-eod-full`:** its `change`/`changePercent` are close − open
  (intraday), not day-over-day. Example: ^IXIC on 2026-11-06 shows −0.09% but closed
  +1.09%. If you ever compute from EOD history, use consecutive closes.
- **GAAP vs adjusted:** FMP statements are GAAP; `earnings-company` `epsActual` is
  adjusted. Don't mix them. Example: NVDA Q2 FY27 GAAP diluted $2.46 vs adjusted $2.22,
  the gap being mostly a $7.8B equity-investment gain.

| Need | Primary | Fallback |
|---|---|---|
| Price, 52-wk range, 10/40-wk MA | `quote` (`quote`) | web: stockanalysis.com |
| Stock vs ETF, sector | `company` (`profile-symbol`) | web |
| 3M/6M/1Y returns | `quote` (`quote-change`) | web, same source for stock and benchmark |
| Quarterly EPS, revenue, op income | `statements` (`income-statement`, `quarter` limit 5, and `Q<n>` limit 2) | latest 10-Q / press release (GAAP figures) |
| Annual EPS, revenue, op income, shares, EBITDA | `statements` (`income-statement`, `annual` limit 4) | 10-K |
| ROE, ROIC, ND/EBITDA, FCF yield | `statements` (`key-metrics`, `annual` limit 1) | `metrics-ratios` annual |
| Next earnings date | `calendar` (`earnings-company`, limit 5) | web: company IR page |
| Market (both indexes) | `indexes` (`index-quote`) and `quote` (`quote-change`) | web |
| News, catalysts, moat, capital allocation | WebSearch with month and year in the query | omit N, set `moat`/`capital` to null |
| Institutional ownership trend | WebSearch "TICKER institutional ownership 13F <quarter YYYY>" | omit I |
| ETF price, MAs, returns, holdings | WebSearch / WebFetch stockanalysis.com/etf/TICKER | — |

If FMP isn't connected at all, gather the same fields from the web, add every factor so
sourced to `web_sourced`, and the confidence level will reflect it.

## Checking reliability

- `python3 -m unittest -v test_score.py` (in `scripts/`) covers band edges, losses,
  negative equity, splits, the stage table, caps, thesis rules, the actions, a golden
  NVDA snapshot, and the market gate on real 2022–23 S&P 500 weeks.
- `python3 backtest_market.py [weekly.csv]` replays the market gate week by week with
  forward returns. Run it on any change to `weekly_stage` or `market_regime`; add more
  history (2000–02, 2008–09, 2018, 2020) to `fixtures/` to widen the test.
- Repeat-run check after any change to `SKILL.md`: run 3–4 tickers five times on the same
  day and diff the factor lines. Scores can only vary through inputs or the four
  judgments, so any variance points at a data-gathering step that needs tightening.
