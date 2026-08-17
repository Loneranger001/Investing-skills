---
name: canslim
description: IBD-style CAN SLIM fundamental analysis of a US stock or ETF ticker. Produces a 0-99 composite score, a Buy/Hold/Sell verdict, and a short synopsis explaining why. Use when the user asks to analyze a ticker, asks "is TICKER a buy?", asks for a CAN SLIM or IBD-style check, or invokes /canslim with one or more tickers.
argument-hint: <TICKER> [TICKER ...]
---

# CAN SLIM Ticker Analysis

Analyze the ticker(s) given in the arguments (or in the user's message) using IBD's CAN SLIM
methodology and deliver a **short synopsis** — not a long report.

Read `references/methodology.md` (in this skill's directory) for exact thresholds, the scoring
rubric, and the data-source map before evaluating. Follow it strictly so scores are consistent
across runs.

## Workflow

### 1. Resolve the ticker

- Use `mcp__FMP__quote` (endpoint `quote`) to confirm the symbol and get price, 52-week
  high/low, avg volume, market cap, shares outstanding.
- Use `mcp__FMP__company` (endpoint `profile-symbol`) to get the profile; its `isEtf` /
  `isFund` flags decide the mode. ETF or fund → use **ETF mode** (methodology §ETF mode).
  Stock → full CAN SLIM.
- If the symbol is unknown, try `mcp__FMP__search` (endpoint `search-symbol`) and ask the
  user only if genuinely ambiguous.

### 2. Gather data (run independent calls in parallel)

Several FMP endpoints are plan-gated (quarterly/TTM statements, news, earnings calendar,
form13F). Use the cheap, plan-safe endpoints below first; the methodology's data map lists
the fallback for anything that errors with ACCESS DENIED — never let one gated endpoint
block the analysis.

For a **stock**, fetch in parallel:
- Multi-period returns for the stock AND `^GSPC`: `mcp__FMP__quote`
  (endpoint `quote-change`) → powers the Relative Strength factor directly.
- Annual income statements, last 4 years: `mcp__FMP__statements`
  (endpoint `income-statement`, period `annual`, limit 4) → annual EPS trend, revenue,
  share count trend (`weightedAverageShsOutDil`).
- Annual ratios: `mcp__FMP__statements` (endpoint `metrics-ratios`, period `annual`,
  limit 2) → compute ROE = `netIncomePerShare / shareholdersEquityPerShare`; margins, debt.
- Float: `mcp__FMP__company` (endpoint `shares-float`).
- Market direction: `mcp__FMP__indexes` (endpoint `index-quote`) for `^GSPC` and `^IXIC` —
  each quote already includes `priceAvg50` and `priceAvg200`; no history needed.
- Quarterly EPS/revenue (last 2–3 quarters, YoY): `WebSearch`
  (e.g. "TICKER quarterly EPS revenue last quarter year-over-year") — FMP quarterly
  statements are usually plan-gated, so web is the primary source for the C factor.
- News/catalysts + institutional ownership trend: `WebSearch`.

For an **ETF**: FMP gates ETF symbols on lower-tier plans (quote, quote-change, chart,
and etfAndMutualFunds all return ACCESS DENIED). Try `quote` once — if denied, get the
ETF's price, 52-week high, 50/200-day moving-average status, 3M/6M/1Y returns, expense
ratio, and top holdings via `WebSearch`. The `^GSPC`/`^IXIC` index quotes and `^GSPC`
`quote-change` still work on FMP for the market-direction and RS comparisons.

**Fallback:** if FMP tools are not available in the session at all, gather the same data
points with `WebSearch`/`WebFetch` and state in the output that figures are approximate.

### 3. Evaluate and score

Score each CAN SLIM factor per the methodology rubric, compute the weighted 0–99 composite,
apply the market-direction cap, and map to a verdict: **≥80 Buy · 50–79 Hold · <50 Sell**.

### 4. Long-term thesis read

CAN SLIM's score and sell rules are a trading/timing signal, not a long-term hold/exit
rule. Alongside the score, independently label the **long-term thesis**: **Intact / At
Risk / Broken**, per `references/methodology.md` §Long-term thesis read. This mostly
reuses data already gathered in step 2 — no separate research pass needed unless the
step-2 news search didn't cover competitive/regulatory context. The score and the thesis
read are allowed to disagree; when they do, say so explicitly rather than collapsing them
into one verdict.

### 5. Output — keep it short

Per ticker, output exactly this shape (no tables, no factor-by-factor dump):

```
**TICKER — VERDICT (score/99)** · $price, ±x% off 52-wk high
Long-term thesis: INTACT / AT RISK / BROKEN

3–6 sentence synopsis: the 2–3 factors that drove the verdict (with the key numbers,
e.g. "Q EPS +54% YoY, accelerating"), the biggest weakness or risk, and the current
market-direction context. If data was degraded (no FMP, no 13F), say so in one clause.

1–2 sentences on the thesis label: the core-business/capital-allocation/moat read behind
it. If the score and thesis point different directions (e.g. Sell score, Intact thesis),
name that gap explicitly — it's the signal a long-term holder actually needs.
```

End the message (once, not per ticker) with a one-line note that this is an automated
CAN SLIM-style analysis, not financial advice.
