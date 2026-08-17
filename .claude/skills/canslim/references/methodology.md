# CAN SLIM Methodology — Thresholds, Scoring, and Data Map

This rubric approximates IBD's ratings from public data. Apply it mechanically so the same
inputs always produce the same score.

## Factor rubrics (stocks)

Each factor is scored 0–100, then combined with the weights in the Scoring section.

### C — Current quarterly earnings

Compare the most recent reported quarter to the same quarter a year ago (YoY, not
sequential). Use diluted EPS; if EPS is negative or turning positive, judge on revenue
growth and trajectory toward profitability.

| Evidence | Score |
|---|---|
| EPS growth ≥40% YoY **and** accelerating vs. prior quarter's YoY rate, sales ≥20% | 90–100 |
| EPS growth ≥25% YoY, sales ≥15% | 75–89 |
| EPS growth 10–25% YoY | 50–74 |
| EPS growth 0–10%, or positive EPS but sales shrinking | 25–49 |
| EPS declining YoY or losses widening | 0–24 |

Acceleration (each of the last 3 quarters' YoY growth rate higher than the one before)
adds up to +10 (cap 100); deceleration across 3 quarters subtracts up to −10.

### A — Annual earnings growth

Use the last 3 fiscal years of diluted EPS plus TTM ROE.

| Evidence | Score |
|---|---|
| 3-yr EPS CAGR ≥25% with growth in each year, ROE ≥17% | 90–100 |
| 3-yr EPS CAGR ≥25% but one down year, or CAGR 15–25% with ROE ≥17% | 70–89 |
| 3-yr EPS CAGR 10–15%, or strong CAGR but ROE <17% | 50–69 |
| Flat annual EPS (0–10% CAGR) | 25–49 |
| Declining annual EPS or persistent losses | 0–24 |

### N — New things / new highs

Two halves, averaged:
- **Newness (news scan):** genuine new product, new market, new management, or upgraded
  guidance within ~6 months → 80–100; ordinary news flow → 40–60; stale story or
  deteriorating narrative → 0–30.
- **New-high proximity:** within 5% of 52-week high → 100; within 15% → 75; within 25% →
  50; 25–40% off → 25; >40% off → 0. (IBD buys strength near highs, not dips.)

### S — Supply and demand

- Share count flat or shrinking YoY (buybacks; compare `weightedAverageShsOutDil` across
  annual statements) → start at 70; meaningful dilution (>3%/yr) → start at 30; heavy
  dilution (>8%/yr) → start at 10.
- Demand proxy from the quote: price rising recently (positive 1M change) on volume above
  the 50-day average → +20; price falling on above-average volume (distribution) → −20.
- Very large floats (>1B shares) dampen the CAN SLIM ideal slightly: −10. Cap 0–100.

### L — Leader or laggard (Relative Strength)

Use the `quote-change` endpoint (returns % change over standard periods) for the stock and
for `^GSPC`, and compute an IBD-style weighted return that overweights the recent quarter:

```
RS = 0.4·(3M % change) + 0.3·(6M % change) + 0.3·(1Y % change)
ΔRS = RS_stock − RS_index          (percentage points)
```

| ΔRS (pp) | Score |
|---|---|
| ≥ +25 (strong leader) | 90–100 |
| +10 to +25 | 70–89 |
| 0 to +10 | 50–69 |
| −10 to 0 | 25–49 |
| < −10 (laggard) | 0–24 |

This proxies IBD's RS Rating ≥80 rule: only scores ≥70 here correspond to "leader."

### I — Institutional sponsorship

From 13F positions-summary (or web fallback): sponsorship present and holder count /
institutional shares **increasing** over recent quarters → 70–100; present but flat →
50–69; declining ownership → 20–49; negligible institutional ownership → 0–19.
If only a point-in-time ownership % is available: >60% → 70, 30–60% → 55, <30% → 35.

### M — Market direction

Using `^GSPC` and `^IXIC` vs. their 50-day and 200-day moving averages. The
`index-quote` endpoint returns `price`, `priceAvg50`, and `priceAvg200` directly — no
history download or SMA computation needed:

| Condition | State | Score |
|---|---|---|
| Both indexes above both MAs, 50d > 200d | Confirmed uptrend | 85–100 |
| Above 200d but chopping around 50d | Uptrend under pressure | 55–70 |
| Below 50d, testing 200d | Correction risk | 30–50 |
| Both below 200d, 50d < 200d | Downtrend | 0–25 |

## Composite score (stocks)

Weighted average, echoing IBD's emphasis on earnings and relative strength:

| Factor | C | A | L | N | S | I | M |
|---|---|---|---|---|---|---|---|
| Weight | 20% | 20% | 20% | 12.5% | 7.5% | 10% | 10% |

Normalize to **0–99** (composite × 0.99, rounded).

**Market cap rule:** in a confirmed *downtrend* (M ≤ 25), cap the final score at 74 —
no Buy verdicts against the market. In "correction risk" (M ≤ 50), cap at 84.

**Verdict bands:** ≥80 **Buy** · 50–79 **Hold** · <50 **Sell**.

Interpretation guidance: Buy ≈ IBD Composite ≥80 leader in an uptrend; Hold ≈ fundamentals
intact but something (RS, trend, deceleration) argues against new money; Sell ≈ broken
fundamentals or clear laggard.

## ETF mode

CAN SLIM's earnings factors don't apply to funds. Score an ETF on four factors:

| Factor | Weight | Rubric |
|---|---|---|
| Relative strength vs. `^GSPC` (same RS_raw formula) | 35% | Same bands as L above |
| Trend: price vs. own 50d/200d SMA | 30% | Above both & 50d>200d → 85–100; above 200d only → 55–70; below 50d → 30–50; below both → 0–25 |
| 52-week-high proximity | 15% | Same bands as N's second half |
| Market direction (M, as above) | 20% | Same rubric |

Same 0–99 normalization, same downtrend caps, same verdict bands. Mention in the synopsis
what the ETF holds and its expense ratio if available.

**ETF data sourcing:** on the user's FMP plan, ETF symbols are gated across quote,
quote-change, chart, and etfAndMutualFunds. Try `quote` once; when denied, pull the ETF's
price, 52-week high, MA status, and 3M/6M/1Y returns from `WebSearch` (stockanalysis.com
and barchart summaries work well). Index data for `^GSPC`/`^IXIC` remains available via
`mcp__FMP__indexes` and `quote-change`.

## Long-term thesis read (stocks only, separate from the score)

CAN SLIM is a trading system: its sell rules (8% stop-loss, distribution-day breaks, RS
deterioration) are tuned for a holding period of months, not years. A long-term investor
who exits on those signals gets shaken out of positions they meant to hold for years. So
alongside the 0–99 score, produce a second, independent label: is the **long-term thesis**
Intact, At Risk, or Broken. It never changes the CAN SLIM score or verdict — it is
reported next to it, and the two are allowed to disagree.

Answer four questions from data already gathered in step 2 (annual/quarterly financials,
share-count trend, and the news search, which covers competitive and regulatory
developments alongside catalysts). No separate research pass.

1. **Core business durability** — is the primary revenue engine still growing and
   profitable on its own (revenue and margin trend), independent of the stock's price
   action? For pre-revenue or early-commercialization companies, judge instead on progress
   toward commercial traction (contracts, pilots, design wins) and whether the cash runway
   supports reaching it.
2. **Capital allocation discipline** — is heavy spending (capex, M&A, R&D ramps) a
   reasoned bet with a plausible payback, or empire-building? Read management's own stated
   rationale from the news search, not the headline spending number alone.
3. **Balance sheet & share count trend** — buybacks shrinking the share count and a
   manageable debt load favor "intact"; heavy dilution or rising leverage favor "at risk."
   (Reuses the S-factor data.)
4. **Moat / competitive position** — is competitive pressure, regulatory action, or
   technological disruption eroding the business's position over a multi-year horizon?

| Label | Meaning |
|---|---|
| **Intact** | All four hold up. Nothing structural has changed, even if the score is weak on short-term momentum. |
| **At Risk** | One or two are genuinely uncertain or turning negative (an unproven capex bet, a real competitive threat) — not yet disqualifying, but worth re-checking each quarter. |
| **Broken** | The core business is shrinking or impaired, capital is being destroyed, or the moat has clearly failed. Structural, not one bad quarter. |

Weight questions 1 and 4 most heavily: a company survives a bad capital-allocation cycle or
a stretched balance sheet far more often than a shrinking core business or a lost moat.

If the inputs behind two or more questions are missing or web-sourced only, call the thesis
read low-confidence rather than asserting a label flatly.

When the CAN SLIM verdict and the thesis label disagree (e.g. Sell score / Intact thesis),
say so explicitly — that gap is the useful signal: timing versus reasons to own.

**ETF mode:** skip the thesis read entirely and omit the line from the output. These four
questions are company-specific and have no meaningful fund analogue — do not improvise one.

## Data map: need → primary source → fallback

FMP plan-gating verified as of Aug 2026 on the user's plan: quarterly & TTM statements,
`news`, `calendar` (earnings history), and `form13F` are **gated** — go straight to the
web fallback for those. Everything in the "primary" column below is confirmed working.

| Data need | Primary source | Fallback |
|---|---|---|
| Price, 52w hi/lo, volume, mkt cap, 50/200-day avg | `quote` (`quote`) — includes `priceAvg50`/`priceAvg200` | search "TICKER stock price 52 week high" |
| Stock vs ETF, profile, sector | `company` (`profile-symbol`) — `isEtf`/`isFund` flags | search "TICKER company profile" |
| Multi-period returns (RS factor) | `quote` (`quote-change`) for ticker and `^GSPC` | search "TICKER 3 month 6 month 1 year performance" |
| Quarterly EPS/revenue YoY (C factor) | `WebSearch` "TICKER quarterly results EPS revenue YoY" (FMP quarterly gated) | `WebFetch` the latest earnings press release |
| Annual EPS (4y), share count trend | `statements` (`income-statement`, period `annual`, limit 4) | search "TICKER annual EPS history" |
| ROE, margins, debt | `statements` (`metrics-ratios`, annual) — ROE = `netIncomePerShare / shareholdersEquityPerShare` | search "TICKER return on equity" |
| Piotroski/Altman sanity check (optional) | `statements` (`financial-scores`) | — |
| Float | `company` (`shares-float`) | search "TICKER shares float" |
| Market direction (M factor) | `indexes` (`index-quote`) for `^GSPC` and `^IXIC` — `priceAvg50`/`priceAvg200` built in | search "S&P 500 Nasdaq above 50 day 200 day moving average" |
| Institutional ownership (I factor) | `WebSearch` "TICKER institutional ownership percent trend" (FMP 13F gated) | note factor as approximate |
| News/catalysts (N factor) | `WebSearch` "TICKER news product launch guidance" (FMP news gated) | — |
| ETF price/returns/MA status/fund info | `WebSearch` (FMP gates ETF symbols on this plan — try `quote` once, expect denial) | `WebFetch` stockanalysis.com/etf/TICKER |

Degrade gracefully: a missing single input means score that factor from the best available
proxy and flag it; it never blocks the whole analysis. If an FMP endpoint returns ACCESS
DENIED, don't retry it — use the fallback column.
