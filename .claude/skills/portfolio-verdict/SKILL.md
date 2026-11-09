---
name: portfolio-verdict
description: Weekly, monthly or ad hoc check-up for a long-term portfolio of broad-market ETFs (the core, e.g. QQQ, SCHG, SPMO, VOO) plus individual stocks (the satellite, ~20%). Returns one verdict for the period (Buy More / Buy / Exercise Caution / Pause / Sell) with a market-health panel (trend, breadth, volatility, credit, yield curve, valuation, sentiment, sector leadership), each ETF's buy zone and what followed similar weeks historically, a verdict and action for every holding, the dollar split of this period's contribution, and dashboard-ready JSON plus an HTML dashboard. Use whenever the user asks about the portfolio as a whole, such as whether to keep buying, pause contributions, buy the dip, add more, trim or sell across the portfolio; asks when a core ETF is a better buy, how healthy the market is, or for a weekly/monthly portfolio or DCA check; wants to refresh their portfolio dashboard; or invokes /portfolio-verdict. For a single ticker use minervini (trade verdict) or canslim (long-term thesis) instead.
argument-hint: [quick] [$amount] [path/to/portfolio.json | TICKER ...]
---

# Portfolio verdict

The user invests for the long term: about 80% in broad-market ETFs (the **core**) and about
20% in individual stocks and narrower ETFs (the **satellite**). They want to buy the ETFs
when it makes more sense to, see the state of the market with numbers behind it, and feed
the result into a dashboard. Every run answers on one five-step scale:

| Verdict | Core ETFs (this period's contribution) | Satellite holding |
|---|---|---|
| **Buy More** | usual amount + the cash reserve (all, or half in a repair); a fund in its own buy zone gets a double share | leader at a buyable entry: add a full tranche |
| **Buy** | usual amount (+ any reserve) | add a half tranche / start a position |
| **Exercise Caution** | half the usual amount; the other half goes to the reserve | hold; add only at the stated level |
| **Pause** | nothing new; the whole contribution goes to the reserve; hold | hold; no new money; re-check |
| **Sell** | never on market signals (see below) | exit (thesis Broken), reduce by half (Stage 4), or trim an oversized position |

What's behind it, all from `scripts/backtest_dca.py` and `scripts/build_stats.py` on
2000–2023 weekly S&P 500 and Nasdaq closes (details in `references/methodology.md`):

- **The verdict is trend-based and backtested.** Pause and Caution defer money to a reserve
  that goes back in when the market reclaims its 40-wk line: +2.8% vs plain DCA over
  2000–2023 (+10.5% in 2000–03, +3.3% in 2007–10), −1 to −1.5% in each bull run or V-shaped
  recovery. It's insurance against long bears, not alpha. Say so if asked.
- **Verdicts separate risk more than returns.** After Buy weeks the next 26 weeks had a
  median of +5.5% and a worst decile of −6% or worse. After Exercise Caution weeks: median
  +5.9%, worst decile −20%. After Pause: median +1.2%, worst decile −27%.
- **"When does an ETF make more sense to buy":** a 5–10% pullback in a confirmed uptrend
  (its **buy zone**) was followed by a 26-week median of +7.0% (76% up, worst decile −5%) vs
  +5.3% (71% up, −8%) near the high. Real but modest; the stats are shown so the user can
  judge. Each fund gets its zone prices.
- **The core is never sold on market signals.** Selling half the core on entering Pause
  would have cost −10% over 2000–2023 (−18% selling all of it), before taxes.
- **Market health is context, not a signal.** Trend, participation, volatility, credit and
  the yield curve are scored with practitioner thresholds (not backtested); valuation,
  sentiment and sector leadership are shown unscored. Health never changes a verdict; when
  it strongly disagrees with the trend, the output says so.

**All arithmetic happens in the scripts**, which reuse the canslim scorer for every
weekly-stage, market-gate, thesis and holder rule. Your job is to load the portfolio,
gather inputs exactly as specified, run the scripts, and write a short synopsis. Never
hand-compute or override a verdict, level, score or dollar amount.

**Requires the `canslim` skill installed next to this one** (`../canslim/scripts/score.py`).
Read `../canslim/SKILL.md` for the stock data steps referenced below.

## Workflow

### 1. Load the portfolio

Look for the portfolio file in this order: a path given as an argument, `portfolio.json` in
the current working directory, `portfolio.json` in this skill's directory. Shape:
`portfolio.example.json`. Core `target_pct` is each fund's share of the **core** (they sum
to 100); `satellite_target_pct` is the satellite's share of the whole portfolio.

- **No file and no tickers:** ask once for holdings (tickers, shares, which ETFs are core,
  the usual contribution), then offer to save them as `portfolio.json`. Don't block on
  shares: verdicts work without them; only drift checks, size caps and the dollar split
  need them.
- **Tickers passed as arguments** limit the run to those tickers: use their file entries
  where they exist, and treat tickers not in the file as not held (`held: false`). Leave
  out `shares` and `value` in a limited run, because weights need the whole portfolio (a
  lone NVDA would read as 100% of it). The market verdict is always computed. Don't write
  dashboard history from a limited run.
- **Classify ETFs** the file doesn't classify: core = a fund tracking a broad US index or a
  broad style or factor slice of one (S&P 500, total market, Nasdaq-100, large-cap growth,
  S&P 500 momentum or quality). Sector, thematic, single-country, leveraged and bond ETFs
  are satellite. Say which way you classified anything ambiguous.
- **Mode:** `quick` in the arguments sets `"mode": "quick"`: stocks get trend-only reads
  (no statements, no stock web searches) and only the FMP health inputs are gathered (step
  2b). A quick read can't produce Buy More for a stock. Default is `full`. If the user runs
  this weekly, suggest quick for the in-between weeks, and full monthly and right after a
  satellite stock reports.
- **Amount:** a dollar figure in the arguments or message ("I have $3k to put in") sets
  `portfolio.amount` for this run; otherwise the file's `contribution` is used.

### 2. Market and health (once per run, in parallel)

**a. The verdict's inputs (required).** As canslim step 2: `mcp__FMP__indexes`
(`index-quote`) for `^GSPC` and `^IXIC` (price, `priceAvg50`, `priceAvg200`, **`yearHigh` →
`year_high`**) and `mcp__FMP__quote` (`quote-change`) for both (3M/6M/1Y). Both indexes are
required; the script refuses to run without them. Only these two drive the verdict.

**b. Health inputs (optional; every one that's missing is dropped and the coverage shown).**
Put them in the input's `health` block. Each comes from one source; don't mix sources for
one field, and date-check web results (skip anything more than a week old).

| Field(s) | Source | Mode |
|---|---|---|
| `^RUT` {price, ma50, ma200, year_high, returns} | FMP `index-quote` + `quote-change` for `^RUT` | quick + full |
| `vix`, `vix3m` | FMP `index-quote` for `^VIX` and `^VIX3M` (price) | quick + full |
| `us10y`, `us2y`, `us3m` | FMP treasury rates endpoint (`treasury-rates`, latest row: `year10`, `year2`, `month3`) | quick + full |
| `pct_above_200d` | % of S&P 500 members above their 200-day MA (Barchart `$S5TH` or StockCharts `$SPXA200R`) | full |
| `rsp_3m`, `spy_3m` | 3M % return of RSP and SPY from the same ETF source as step 3 | full |
| `sectors_3m` {XLK, XLY, XLC, XLF, XLI, XLE, XLB, XLP, XLU, XLV, XLRE} | 3M % returns, same ETF source | full |
| `hy_oas`, `hy_oas_3m_ago` | ICE BofA US High Yield OAS, % (FRED `BAMLH0A0HYM2`): latest and ~3 months earlier | full |
| `fwd_pe`, `fwd_pe_10y_avg` | S&P 500 forward 12-month P/E and its 10-yr average (FactSet *Earnings Insight*, weekly) | full |
| `cape` | Shiller CAPE (multpl.com) | full |
| `fear_greed` | CNN Fear & Greed index, 0–100 | full |
| `aaii_bull_bear` | AAII sentiment survey, bullish % minus bearish %, latest week | full |

Record where each web figure came from in `health.sources` (field → "site, date"). If a
lookup fails, leave the field out rather than estimating it.

### 3. Holdings (run in parallel)

| Holding | Data | How |
|---|---|---|
| Core ETF | price, `year_high`, `ma50`, `ma200`, 3M/6M/1Y returns, `benchmark_returns` (SPY, same source and date) | canslim step 3b (FMP blocks ETF symbols on this plan; one web source) |
| Satellite stock, `full` | everything canslim needs, including the four judgments | canslim steps 1, 3a and 4 |
| Satellite stock, `quick` | `quote` (`quote`) and `quote-change` only, plus `next_earnings` from `calendar` (`earnings-company`, limit 5) | skip statements and web searches |
| Satellite ETF | as a core ETF, plus `etf_class` | canslim step 3b |

`year_high` matters for every fund: it sets the buy zone. Keep canslim's FMP rule: `limit`
≤ 5. If FMP isn't connected at all, gather the same fields from the web and list them in
`web_sourced`; confidence drops accordingly.

### 4. Score, store, render

Write one JSON file in the shape of `scripts/example_input.json` to your scratchpad (or a
temp dir): `as_of`, `mode`, `market`, `health`, a `portfolio` block (the file's settings
plus `amount` if given), and `holdings` = each file entry merged with its data. Then:

```
python3 <skill dir>/scripts/verdict.py /path/to/input.json --out <data dir>
python3 <skill dir>/scripts/render_dashboard.py <data dir>
```

`<data dir>` is the portfolio file's `dashboard_dir` if set, else `portfolio-verdict-data/`
next to the portfolio file. `--out` writes `latest.json` (the full result, schema in
`references/output_schema.md`) and upserts one line per date into `history.jsonl`; the
renderer turns both into a self-contained `dashboard.html`. Skip `--out` for ticker-limited
runs. The user's own dashboard should read `latest.json` and `history.jsonl`, not scrape
the HTML.

If the user wants the dashboard as a page they can open anywhere and a publishing tool
(such as an Artifact tool) is available, publish `dashboard.html` from the same path each
run so the link stays the same. If code execution isn't available, apply
`references/methodology.md` by hand, rule by rule, and write "scored manually" under the
headline.

### 5. Output

The script's `text` block holds everything for chat. Paste its lines and tables verbatim,
in this order, skipping any that are null (don't reword verdicts, levels, scores or
dollar amounts):

```
<headline>
<market_line>
<why_line>
<do_line>
<next_line>
<stats_line>
<divergence_line>

**Market health**
<health_table_md>

<sleeve_line>
<tables_md[0]>                     (core: verdict, buy zone, what followed similar weeks)

<tables_md[1]>                     (satellite, if any)

<plan_line>
<actions_line>

2–4 sentence synopsis: what the weekly chart says and the one level that matters most;
the strongest and weakest health readings and whether they agree with the verdict; which
core fund (if any) sits in its buy zone; anything notable in the satellite (a thesis at
risk, earnings inside two weeks, a position at its cap).
Mention any flag that changes how much to trust a row (missing data, low confidence,
assumed classification, health coverage below 5/5).

Dashboard: <path to dashboard.html, or the published link>
```

End with one line: automated trend-following analysis, not financial advice.

If the plan moved money into or out of the reserve, offer to update `cash_reserve` (and
any changed `shares`) in `portfolio.json`. Edit the file only after the user says they
followed the plan.
