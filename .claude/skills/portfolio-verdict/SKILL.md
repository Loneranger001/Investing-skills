---
name: portfolio-verdict
description: Weekly, monthly or ad hoc check-up for a long-term portfolio built from broad-market ETFs (the core, e.g. QQQ, SCHG, SPMO, VOO) plus individual stocks (the satellite, ~20%). Returns one verdict for the period (Buy More / Buy / Exercise Caution / Pause / Sell), a verdict and concrete action for every holding, how much of this period's contribution to invest and where, and the index levels that would change the call. Use whenever the user asks whether to keep buying, pause contributions, buy the dip, add more, trim or sell across their portfolio or ETFs; asks for a weekly or monthly portfolio check, a DCA check, or "what should I do with my money this month"; or invokes /portfolio-verdict. For a deep dive on a single ticker use canslim instead.
argument-hint: [quick] [$amount] [path/to/portfolio.json | TICKER ...]
---

# Portfolio verdict

The user invests for the long term: about 80% in broad-market ETFs (the **core**) and about
20% in individual stocks and narrower ETFs (the **satellite**). They run this weekly,
monthly, or whenever markets get loud, and want a straight answer on one five-step scale:

| Verdict | Core ETFs (this period's contribution) | Satellite holding |
|---|---|---|
| **Buy More** | usual amount + the cash reserve (all, or half in a repair); spare cash can go in too | leader at a buyable entry: add a full tranche |
| **Buy** | usual amount (+ any reserve) | add a half tranche / start a position |
| **Exercise Caution** | half the usual amount; the other half goes to the reserve | hold; add only at the stated level |
| **Pause** | nothing new; the whole contribution goes to the reserve; hold | hold; no new money; re-check |
| **Sell** | never on market signals (see below) | exit (thesis Broken), reduce by half (Stage 4), or trim an oversized position |

Two design decisions, both backed by `scripts/backtest_dca.py` on 2000–2023 weekly S&P 500
and Nasdaq closes (details in `references/methodology.md`):

- **Pause and Caution defer money; they don't lose it.** The reserve they build goes back
  in on Buy More when the market reclaims its 40-wk line. Over 2000–2023 that beat plain
  DCA by +2.8% in total (+10.5% in 2000–03, +3.3% in 2007–10) and cost 1–1.5% in each
  bull run or V-shaped recovery. It is insurance against long bear markets, not alpha. Say
  so if the user asks whether it beats just buying every month.
- **The core is never sold on market signals.** Selling half the core on entering Pause
  would have cost −10% over 2000–2023 (−18% selling all of it), before taxes, mostly from
  2011–19 whipsaws. Sells come from broken stocks, Stage 4 satellites and oversized
  positions.

**All arithmetic happens in `scripts/verdict.py`**, which reuses the canslim scorer for every
weekly-stage, market-gate, thesis and holder rule. Your job is to load the portfolio, gather
inputs exactly as specified, run the script, and write a short synopsis. Never hand-compute
or override a verdict, level or dollar amount.

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
  lone NVDA would read as 100% of it); size caps and drift checks are then skipped. The
  market verdict is always computed.
- **Classify ETFs** the file doesn't classify: core = a fund tracking a broad US index or a
  broad style or factor slice of one (S&P 500, total market, Nasdaq-100, large-cap growth,
  S&P 500 momentum or quality). Sector, thematic, single-country, leveraged and bond ETFs
  are satellite. Say which way you classified anything ambiguous.
- **Mode:** `quick` in the arguments sets `"mode": "quick"`: stocks get trend-only reads
  (no statements, no web searches), and a quick read can't produce Buy More. Default is
  `full`. If the user runs this weekly, suggest quick for the in-between weeks, and full
  monthly and right after a satellite stock reports.
- **Amount:** a dollar figure in the arguments or message ("I have $3k to put in") sets
  `portfolio.amount` for this run; otherwise the file's `contribution` is used.

### 2. Market (once per run)

As canslim step 2: `mcp__FMP__indexes` (`index-quote`) for `^GSPC` and `^IXIC` (price,
`priceAvg50`, `priceAvg200`, **`yearHigh` → `year_high`**) and `mcp__FMP__quote`
(`quote-change`) for both (3M/6M/1Y). Both indexes are required: the script refuses to run
without them.

### 3. Holdings (run in parallel)

| Holding | Data | How |
|---|---|---|
| Core ETF | price, `year_high`, `ma50`, `ma200`, 3M/6M/1Y returns, `benchmark_returns` (SPY, same source and date) | canslim step 3b (FMP blocks ETF symbols on this plan; one web source) |
| Satellite stock, `full` | everything canslim needs, including the four judgments | canslim steps 1, 3a and 4 |
| Satellite stock, `quick` | `quote` (`quote`) and `quote-change` only, plus `next_earnings` from `calendar` (`earnings-company`, limit 5) | skip statements and web searches |
| Satellite ETF | as a core ETF, plus `etf_class` | canslim step 3b |

Keep canslim's FMP rule: `limit` ≤ 5. If FMP isn't connected at all, gather the same fields
from the web and list them in `web_sourced`; confidence drops accordingly.

### 4. Score

Write one JSON file in the shape of `scripts/example_input.json` to your scratchpad (or a
temp dir): `as_of`, `mode`, `market`, a `portfolio` block (the file's settings plus
`amount` if given), and `holdings` = each file entry merged with its data. Then run:

```
python3 <this skill's directory>/scripts/verdict.py /path/to/input.json
```

If code execution isn't available, apply `references/methodology.md` by hand, rule by rule,
and write "scored manually" under the headline.

### 5. Output

Exactly this shape, pasting the script's lines and tables verbatim (don't reword verdicts,
levels or dollar amounts):

```
<headline>
<market_line>
<why_line>
<do_line>
<next_line>
<sleeve_line>                      (if not null)

<tables_md[0]>                     (core)

<tables_md[1]>                     (satellite, if any)

<plan_line>                        (if not null)
Action items: <actions joined by "; ">   (only if any)

2–4 sentence synopsis: what the market is doing on the weekly chart and the one level that
matters most; anything notable in the satellite (a thesis at risk, an earnings date inside
two weeks, a position at its cap); and, if the verdict changed the dollar plan, why.
Mention any flag that changes how much to trust a row (missing data, low confidence,
assumed classification).
```

End with one line: automated trend-following analysis, not financial advice.

If the plan moved money into or out of the reserve, offer to update `cash_reserve` (and
any changed `shares`) in `portfolio.json`. Edit the file only after the user says they
followed the plan.
