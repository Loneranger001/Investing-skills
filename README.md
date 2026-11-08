# Investing-skills

Claude Code skills for investing workflows.

## Skills

### `/canslim`: CAN SLIM for 2–5 year position investing

Built for an investor who holds for 2–5 years and makes entry and exit decisions on the
weekly chart. For a US stock or ETF it returns:

- **Quality 0–99**: is the business worth owning for years? Annual and quarterly growth,
  returns on capital, share count and balance sheet, catalysts, institutional sponsorship,
  and a trailing-PEG check on overpaying.
- **Timing 0–99**: is the weekly chart a good entry now? Weekly stage (10-wk / 40-wk MAs),
  relative strength vs. the S&P 500, extension, and the market's weekly trend.
- **Thesis**: Intact / At Risk / Broken.
- **Two actions**: one for new money (Buy · Buy on pullback · Buy (starter) · Watchlist ·
  Avoid) and one for current holders (Hold · Hold, re-check · Reduce · Exit), each with
  the weekly levels that would change it.

IBD's daily sell rules (8% stop, distribution days) are deliberately left out. Holders exit
on a broken thesis or a weekly Stage 4, not on daily noise. New buys are for **leaders**
only (Quality ≥ 70, thesis Intact, Stage 2, beating the S&P 500 by ≥ 10pp) and pause
while either index is below its 40-wk MA (or less than 2% above it), except half-size
starter buys in leaders once both are confirmed above a 40-wk that is still falling. The
gate is backtested on the 2000–02, 2007–09, 2020 and 2022 bear markets (S&P 500 + Nasdaq):
it never reopened between its final close and the low in any of them.

```
/canslim NVDA
/canslim AAPL MSFT QQQ
```

or just ask: *"Is PLTR still a buy?"* or *"Should I keep holding AMZN?"*

Example output (live data, 2026-11-07):

```
**NVDA — Watchlist** · $186.64 · 23% off 52-wk high · earnings 2026-11-17 (in 10d)
Quality 90 · Timing 32 · RS -10pp vs S&P · Thesis At Risk · Weekly: Stage 2 correction below 40-wk (10-wk $220.64 · 40-wk $204.66)
…synopsis…
New money: Watchlist. Thesis At Risk, let the next quarter resolve it; wait for a weekly close above the 40-wk MA ($204.66); not a leader yet: RS -10pp vs the S&P 500 (needs +10); Nasdaq below its 40-wk MA, no new buys until it recovers; earnings in 10d
If you hold: Hold, re-check. Thesis At Risk, revisit after the next report; below the 40-wk MA ($204.66); exit if the 40-wk turns down (Stage 4)
`A 100 · C 100 · R 100 · S 88 · N 90 · I 35 | W 35 · L 24 · E 37 · M 35 | conf High | web: I, N`
```

**How it stays consistent:** the model only gathers data and makes four categorical
judgments (newness, institutional trend, capital allocation, moat). All scoring is done by
`scripts/score.py` (stdlib Python), so the same inputs always give the same output.

**Data sources:** Financial Modeling Prep (FMP) MCP tools, with web search for news,
13F trends, and ETF data. On the current FMP plan, keep `limit` ≤ 5; see the data map in
the methodology.

| File | Purpose |
|---|---|
| `.claude/skills/canslim/SKILL.md` | Workflow, data calls, output format |
| `.claude/skills/canslim/references/methodology.md` | Every formula, threshold, and rule |
| `.claude/skills/canslim/scripts/score.py` | Deterministic scorer |
| `.claude/skills/canslim/scripts/example_input.json` | Input schema (live NVDA snapshot) |
| `.claude/skills/canslim/scripts/test_score.py` | Regression tests: `python3 -m unittest -v test_score.py` |
| `.claude/skills/canslim/scripts/backtest_market.py` | Replays the market gate on weekly index history (`fixtures/`) |

To use the skill outside this repo, copy the whole `.claude/skills/canslim/` folder
(including `references/` and `scripts/`) into `~/.claude/skills/`, or upload it as a zip
to claude.ai. Uploading only `SKILL.md` leaves the skill without its rubric or scorer.

### `/portfolio-verdict`: weekly or monthly portfolio check-up, with a dashboard

For a long-term portfolio that's mostly broad-market ETFs (the **core**: QQQ, SCHG, SPMO,
VOO…) plus about 20% in individual stocks (the **satellite**). Each run gives:

- **One verdict for the period and one per holding**, on a five-step scale, with the index
  levels that would change it:

  | Verdict | Core ETFs: this period's contribution | Satellite holding |
  |---|---|---|
  | **Buy More** | usual amount + the cash reserve; a fund in its own buy zone gets a double share | leader at a buyable entry: add a full tranche |
  | **Buy** | usual amount | add half a tranche / start a position |
  | **Exercise Caution** | half; the other half goes to the reserve | hold; add only at the stated level |
  | **Pause** | nothing new; all to the reserve; hold | hold; no new money; re-check |
  | **Sell** | never on market signals | exit, reduce by half, or trim an oversized position |

- **When each ETF makes more sense to buy:** its chart state, its buy zone in dollars
  (5–10% below its high while above a confirmed 40-wk line), and what followed similar
  weeks in 2000–2023 (median, % up, worst decile, episode count).
- **Market health with stats:** trend, participation (breadth, small caps, equal-weight vs
  cap-weight), volatility (VIX and its term structure), credit (high-yield spread) and the
  yield curve, scored 0–100. Valuation (forward P/E, CAPE), sentiment (Fear & Greed, AAII)
  and sector leadership are shown as context.
- **A dollar plan** for this period's contribution, steered to underweight funds.
- **Dashboard output:** `latest.json` + `history.jsonl` (a versioned JSON contract for your
  own dashboard, `references/output_schema.md`) and a self-contained `dashboard.html`
  (no network, light/dark, tooltips, table views, phone-friendly).

**What the data says** (2000–2023 weekly S&P 500 + Nasdaq):

- **The throttle is insurance.** Pause and Caution only *defer* money; the reserve goes
  back in when the market reclaims its 40-wk line. That beat plain DCA by **+2.8%** overall
  (+10.5% in 2000–03, +3.3% in 2007–10) and cost 1–1.5% in each bull run or V-shaped
  recovery.
- **Verdicts separate risk, not typical returns.** Next-26-week median after Buy weeks
  +5.5%, after Exercise Caution +5.9%, but the worst decile was −6% vs −20% (Pause: −27%).
- **Buy zones help, modestly.** A 5–10% pullback in an uptrend: median +7.0%, 76% up,
  worst decile −5%, vs +5.3%, 71% up, −8% near the high.
- **Never sell the core on these signals.** Doing so would have lost 10–18% before taxes.
- **Health is context.** Its thresholds are practitioner conventions, not backtested, so
  it never changes the verdict; it flags when the internals disagree with the trend.

```
/portfolio-verdict                 # full run from portfolio.json, updates the dashboard
/portfolio-verdict quick           # weekly: stocks trend-only, FMP-only health inputs
/portfolio-verdict $3000           # split $3,000 across holdings
```

or just ask: *"Should I keep buying this month?"*, *"Is QQQ in a buy zone?"*, *"How healthy
is the market right now?"*

Example (schema example: the index and NVDA data are the 2026-11-07 snapshot; the health
inputs and ETF figures are illustrative):

```
**Portfolio verdict 2026-11-07: Exercise Caution** · Market health 56/100 Mixed
Market: S&P 500 7,379 (+0.8% vs 40-wk 7,323, rising, 5.4% off high) · Nasdaq 24,579 (-2.0% vs 40-wk 25,093, rising, 9.7% off high)
Core: invest half the usual amount; the other half goes to the cash reserve.
Changes: Buy on weekly closes 2% above the 40-wk (S&P 500 7,469 and Nasdaq 25,594); Pause if a 40-wk turns down with the index below it
History: after Exercise Caution weeks in 2000–23, the next 26 weeks (S&P/Nasdaq blend): median +5.9%, 63% up, worst 10% -20.1% or worse (68 episodes).

| Area | Score | Read |
| Trend (40%) | 54 neutral | S&P 500: Stage 2 pullback below 10-wk; Nasdaq: Stage 2 correction below 40-wk |
| Participation (20%) | 45 neutral | 44% of S&P 500 stocks above their 200-day; small caps below 40-wk; equal-weight lagging by 2.6pp |
| Volatility (15%) | 47 neutral | VIX 22.6 |
| Credit (15%) | 72 good | HY spread 3.45%, +0.50pp in 3 months |
| Yield curve (10%) | 73 good | 10Y 4.18% vs 3M 3.85%: positive |
| Valuation (context) | rich | forward P/E 21.4, +13% vs its 10-yr average; CAPE 36.8 |
| Sentiment (context) | fear | Fear & Greed 29 (fear); AAII bull-bear -14.2pp |
| Leadership (context) | defensive | offensive sectors -7.3pp vs defensive over 3M; leaders XLU, XLP, XLV |

| Core fund | Of core / target | Verdict | Do | Chart now | After similar weeks (26w) | Buy zone |
| QQQ  | 33.8% / 40% | Exercise Caution | Half the usual amount | At or below the 40-wk, 10-20% off the high | median +10.9%, 72% up, worst 10% -15.6% (63 episodes) | Reclaim $582.73 first |
| SPMO | 32.3% / 30% | Exercise Caution | Half the usual amount | Uptrend, 5-10% pullback (buy zone) | median +7.0%, 76% up, worst 10% -5.2% (59 episodes) | In the zone now ($107.10–$111.53) |
…
Plan for $2,000: invest $1,000: QQQ $1,000 · to reserve $1,000 · reserve after $4,000
```

**Setup:** copy `portfolio.example.json` to `portfolio.json` (git-ignored) in the skill
folder or your working directory, and fill in shares, core targets (each fund's share of
the core), your usual contribution and `dashboard_dir`. Without it, the skill asks for your
holdings. Requires the canslim skill installed next to it; it uses canslim's scorer and
data steps.

| File | Purpose |
|---|---|
| `.claude/skills/portfolio-verdict/SKILL.md` | Workflow, data sources (incl. health inputs), output format |
| `.claude/skills/portfolio-verdict/references/methodology.md` | Every rule, the entry and verdict stats, health scoring, the backtest |
| `.claude/skills/portfolio-verdict/references/output_schema.md` | JSON contract for dashboards (`latest.json`, `history.jsonl`) |
| `.claude/skills/portfolio-verdict/references/entry_stats.json` | What followed each chart state and verdict, 2000–2023 |
| `.claude/skills/portfolio-verdict/scripts/verdict.py` | Deterministic scorer (imports canslim's `score.py`); `--out DIR` writes the dashboard data |
| `.claude/skills/portfolio-verdict/scripts/render_dashboard.py` | `DIR/latest.json` + `history.jsonl` → self-contained `dashboard.html` |
| `.claude/skills/portfolio-verdict/scripts/build_stats.py` | Regenerates `entry_stats.json` from the weekly fixture |
| `.claude/skills/portfolio-verdict/scripts/backtest_dca.py` | Plan vs plain DCA, 2000–2023 (`fixtures/weekly_1999_2023.csv`) |
| `.claude/skills/portfolio-verdict/scripts/test_verdict.py` | Regression tests: `python3 -m unittest -v test_verdict.py` |
| `.claude/skills/portfolio-verdict/scripts/example_input.json` | Input schema |
| `.claude/skills/portfolio-verdict/portfolio.example.json` | Template for your `portfolio.json` |

To use it outside this repo, copy both `canslim/` and `portfolio-verdict/` into
`~/.claude/skills/`.

*Output is automated analysis, not financial advice.*
