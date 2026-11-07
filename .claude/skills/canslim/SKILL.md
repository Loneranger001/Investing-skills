---
name: canslim
description: CAN SLIM-based analysis of a US stock or ETF for a 2-5 year position investor who times entries and exits on the weekly chart. Produces a 0-99 Quality score (worth owning for years?), a 0-99 weekly Timing score (good entry now?), an Intact/At Risk/Broken thesis label, and separate actions for new money (Buy / Buy on pullback / Buy (starter) / Watchlist / Avoid) and for current holders (Hold / Hold, re-check / Reduce / Exit), with the weekly price levels that would change them. Use when the user asks to analyze a ticker, asks "is TICKER a buy?", asks whether to hold, add to, or exit a position, asks for a CAN SLIM or IBD-style check, or invokes /canslim with one or more tickers.
argument-hint: <TICKER> [TICKER ...]
---

# CAN SLIM for 2–5 year position investing

The user holds positions for 2–5 years and makes entry and exit decisions on the weekly
chart. The skill answers three separate questions:

1. **Quality (0–99)**: is this a business worth owning for 2–5 years? Based on CAN SLIM's
   C and A, plus returns on capital, share count and balance sheet, newness, and
   institutional sponsorship, with a valuation check.
2. **Timing (0–99)**: is the weekly chart a good entry right now? Based on the weekly
   stage (10-wk and 40-wk MAs), relative strength vs. the S&P 500, entry location, and the
   market's weekly trend.
3. **Thesis (Intact / At Risk / Broken)**: is the reason to own it still true? This, not
   short-term price action, drives what holders should do.

IBD's daily-chart sell rules (8% stop-loss, distribution days, RS dips) are deliberately
**not** used. They are tuned for months-long trades and shake a 2–5 year holder out of
good positions. Holder exits come from a Broken thesis or a weekly Stage 4 (price below a
falling 40-wk MA). New buys need a **leader** (Quality ≥ 70, thesis Intact, Stage 2,
beating the S&P 500 by ≥ 10pp) and pause while either index is below its 40-wk MA,
except half-size starter buys in leaders while the market bases in Stage 1.

**All arithmetic happens in `scripts/score.py`.** Your job is to gather inputs exactly as
specified, make four categorical judgments, run the script, and write the synopsis. Never
hand-compute, round, or adjust a score or action. Formulas and thresholds are in
`references/methodology.md`.

## Workflow

### 1. Resolve the ticker(s)

- `mcp__FMP__company` (`profile-symbol`): `isEtf`/`isFund` decide the mode; also gives
  sector and industry. ETF or fund → step 3b.
- Unknown symbol → `mcp__FMP__search` (`search-symbol`). Ask the user only if genuinely
  ambiguous. FMP spells share classes with a dash (`BRK-B`).

### 2. Market (once per run, shared by every ticker)

In parallel: `mcp__FMP__indexes` (`index-quote`) for `^GSPC` and `^IXIC` (price,
`priceAvg50`, `priceAvg200`), and `mcp__FMP__quote` (`quote-change`) for both (3M/6M/1Y).
These fill the `market` block.

### 3a. Stock data (run in parallel)

**FMP plan rule: keep `limit` ≤ 5.** On this plan the block is on larger limits, not on
the endpoints. If a call still returns ACCESS DENIED, don't retry it; use the fallback in
the methodology's data map.

| Call | Fills |
|---|---|
| `quote` (`quote`) | `price`, `year_high`, `year_low`, `ma50` ← `priceAvg50`, `ma200` ← `priceAvg200` |
| `quote` (`quote-change`) | `returns` 3M / 6M / 1Y |
| `statements` (`income-statement`, period `annual`, limit 4) | `annual[]`, oldest → newest: `eps` ← `epsDiluted`, `rev` ← `revenue`, `op_inc` ← `operatingIncome`, `shares` ← `weightedAverageShsOutDil`, `ebitda` |
| `statements` (`income-statement`, period `quarter`, limit 5) | `quarters[0]` = newest row, year-ago = 5th row; `last4_eps` = `epsDiluted` of rows 1–4 |
| `statements` (`income-statement`, period `Q<n>`, limit 2), once for each of the two fiscal quarters before the newest | `quarters[1]`, `quarters[2]`, each with its year-ago row |
| `statements` (`key-metrics`, period `annual`, limit 1) | `roe` ← `returnOnEquity`, `roic` ← `returnOnInvestedCapital`, `net_debt_to_ebitda` ← `netDebtToEBITDA`, `fcf_yield` ← `freeCashFlowYield` |
| `calendar` (`earnings-company`, limit 5) | `next_earnings` = date of the row whose `epsActual` is null |

- Copy numbers exactly as returned. Keep units consistent within a field (e.g. all revenue
  in $M); ratios stay as decimals.
- FMP `period` labels are **fiscal**. If the newest quarter is Q2, the prior two are Q1
  (same fiscal year) and Q4 (previous fiscal year).
- Use FMP's GAAP diluted EPS everywhere. Don't mix in adjusted EPS from the web; the
  script detects GAAP distortion itself by comparing against operating income.

### 3b. ETF data

FMP blocks ETF symbols on this plan (`quote` and `quote-change` both return ACCESS
DENIED). Try `quote` once, then take everything from **one** web source
(stockanalysis.com/etf/TICKER works): price, 52-wk high, 50-day and 200-day MA, 3M/6M/1Y
returns, expense ratio, top holdings. Also take **SPY's 3M/6M/1Y from the same source and
date** and put them in `benchmark_returns`; comparing a stale web snapshot against live
`^GSPC` data skews RS. Set `etf_class` to `equity` | `leveraged` | `bond` | `commodity` |
`currency` | `other`. Skip step 4.

### 4. Judgments (stocks only)

Run two web searches, each with the month and year in the query. Check the date on every
result: searches often return last year's quarter. Ignore anything older than 6 months.

1. `TICKER news <Month YYYY> guidance product launch competition regulation`
2. `TICKER institutional ownership 13F <latest quarter YYYY>`

Then set:

- `newness`: `major` (genuine new product, market, or management, or guidance raised
  above consensus within 6 months) | `ordinary` | `stale` (no catalyst, deteriorating
  narrative). If no dated news turns up, **omit it**: the factor is dropped, not guessed.
- `institutional`: `trend` rising | flat | falling (13F holder and share changes over
  recent quarters), plus `pct` (0–1). Omit whatever is unknown.
- `thesis.capital`: `pass` (spending has a stated, plausible payback; buybacks at sane
  prices) | `watch` (large unproven bet, big M&A, capex ramp ahead of demand) | `fail`
  (writedowns, value-destroying deals, empire-building).
- `thesis.moat`: `pass` (no evidence of share or pricing loss) | `watch` (credible
  competitive, regulatory, or technology threat in the news, no measurable damage yet) |
  `fail` (measurable share loss, pricing power gone, or regulation impairing the core
  business).
- `thesis.core` and `thesis.balance`: leave as `"auto"`. The script derives them from
  revenue, margins, share count, leverage, and free cash flow. Override only for
  pre-revenue companies (judge commercial traction and cash runway) and say why in
  `evidence`.

Put a one-line source for each judgment under `evidence` (the script ignores it; it's the
audit trail). List web-sourced factors in `web_sourced`, normally `["N", "I"]`.

### 5. Score

Write one JSON file in the shape of `scripts/example_input.json` to a temp location (your
scratchpad if you have one), then run:

```
python3 <this skill's directory>/scripts/score.py /path/to/input.json
```

Multiple tickers go in one file under `tickers`, sharing one `market` block. If code
execution isn't available, apply `references/methodology.md` by hand and write "scored
manually" in the output.

### 6. Output

Per ticker, exactly this shape:

```
<summary_lines[0]>
<summary_lines[1]>

3–5 sentence synopsis: what drives Quality (with the key numbers), what the weekly chart
says and which level changes the call, the biggest risk to the 2–5 yr thesis, and the
market backdrop. Mention any flag that matters (GAAP distortion, valuation, missing data).

<summary_lines[2]>
<summary_lines[3]>
`<factor_line>`
```

Paste the summary lines and factor line verbatim: don't reword actions, levels, or
numbers. For ETFs, name what the fund holds and its expense ratio in the synopsis. End the
message once (not per ticker) with a one-line note that this is an automated CAN
SLIM-style analysis, not financial advice.
