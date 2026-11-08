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

### `/minervini`: buy / sell / buy-more verdicts from *Trade Like a Stock Market Wizard*

Applies Mark Minervini's SEPA rules to a US stock or ETF and answers the question you asked:

| You ask | Verdicts |
|---|---|
| *Can I buy AAPL?* | **BUY** · **BUY ON BREAKOUT** (pivot, volume needed, buy range) · **WAIT** · **AVOID** |
| *Should I sell AAPL?* | **SELL** · **SELL INTO STRENGTH** · **HOLD, TIGHTEN STOP** · **HOLD** |
| *Should I buy more AAPL?* | **ADD** · **ADD ON BREAKOUT** · **DON'T ADD** |

All three are computed every time; the one you asked about comes first. Rules applied:

- **Trend Template (all 8)**: price above the 150/200-day, 150 > 200, 200-day rising ≥ 1 month,
  50 > 150/200, price above the 50-day, ≥ 30% above the 52-wk low, within 25% of the 52-wk
  high, RS ≥ 70 (proxy: IBD-weighted 12-month performance vs the S&P 500).
- **Stage Analysis**: buys in Stage 2 only; Stage 4 or a break of the 200-day is a sell.
- **VCP**: at least 2 contractions, each shallower than the last, the final one ≤ 10%,
  volume drying up; pivot = high of the last contraction; buy within 5% above it on ≥ 1.4×
  average volume.
- **Earnings**: latest quarter EPS ≥ +20% with sales growing (GAAP one-offs neutralised via
  operating income); acceleration, margin expansion, surprise and **Code 33** shown.
- **Risk**: stop under the last contraction low and never more than 10% below the entry;
  size = 1.25% account risk ÷ stop; stop to breakeven at 2R; never average down.
- **Selling**: into weakness (largest drop of the advance, heavy-volume break of the 50-day,
  failed breakout) or into strength (a 25% run in 3 weeks or 70% above the 200-day, plus a
  second climax sign).
- **Market**: S&P 500 below a falling 200-day → no new buys; under pressure → half size.

```
/minervini AAPL
/minervini NVDA sell entry 120 on 2026-03-02
```

or just ask: *"Can I buy Apple?"*, *"Should I sell NVDA? I bought at 120 in March"*,
*"Should I buy more MSFT?"*

**Deterministic by construction.** The model only fetches data; `scripts/sepa.py` applies
every rule. It uses completed sessions only (a bar dated today counts after 18:00 New York
time), so asking twice during the trading day gives the same answer. It keeps the last 335
sessions, so fetching more history changes nothing, and it uses no judgment inputs at all.
Each result prints a data fingerprint: same fingerprint, same verdicts. The output is the
script's text verbatim, with no free-form synopsis.

Example (synthetic chart from `scripts/example_input.json`):

```
**DEMO: BUY ON BREAKOUT** (can I buy?) · $92.13 at the 2026-10-02 close · Stage 2 uptrend · Trend Template 8/8
Can I buy? **BUY ON BREAKOUT**. Buy only if it trades above the $94.18 pivot (2.2% above the last close) on volume ≥ 931K (1.4× average); buy range $94.18–$98.89; stop $90.53 (-3.9%, under the last contraction low); size ≈ 25% of the account (risks 1.25% of it); once up 8% (2× the risk), raise the stop to breakeven
Should I sell (if you hold)? **HOLD**. Trend Template intact, no sell signals; …
Should I buy more? **ADD ON BREAKOUT**. Add only on a breakout above the $94.18 pivot on volume, …
…Trend Template table…
Setup: 3 contractions 20.9% → 8.3% → 3.9% over 16 wks from the $100.61 high (depth 20.9%) · quietest week 0.64× avg volume · VCP ✓ · pivot $94.18 (2.2% above the close)
Fundamentals: PASS · Q3 FY26 · EPS +44%, prior +34% (accelerating) · sales +30%, prior +24% (accelerating) · net margin 25.0% vs 22.0% a year ago · EPS surprise +7.4% · Code 33 ✓
Market: uptrend: normal position size (S&P 500 6,490, +1.7% vs its 50-day, +7.4% vs its rising 200-day)
Data: 335 sessions through the 2026-10-02 close · fingerprint e1254b8e5d · rules 2026-11-08
```

**Horizon:** Minervini's rules are for trades of weeks to months with a stop of 10% or less.
`/canslim` is for 2–5 year positions. Both answer "can I buy X?", so name the method or
use the slash command when it matters.

**Data:** FMP MCP tools only: daily bars (`historical-price-eod-full`) for the stock and
`^GSPC`, three quarters of income statements, and the earnings calendar. Daily bars can't be
reproduced from web pages, so without FMP price history the skill stops instead of guessing.

| File | Purpose |
|---|---|
| `.claude/skills/minervini/SKILL.md` | Workflow, exact data calls, output format |
| `.claude/skills/minervini/references/methodology.md` | Every rule and threshold, marked as the book's or the skill's reading |
| `.claude/skills/minervini/scripts/sepa.py` | Deterministic rules engine (stdlib) |
| `.claude/skills/minervini/scripts/example_input.json` | Input schema (synthetic chart) |
| `.claude/skills/minervini/scripts/test_sepa.py` | Tests, rules and determinism: `python3 -m unittest -v test_sepa.py` |
| `.claude/skills/minervini/scripts/stress_vcp.py` | VCP recognition rate under noise and false-positive rate |
| `.claude/skills/minervini/scripts/synth.py` | Synthetic chart generator used by the tests |

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
