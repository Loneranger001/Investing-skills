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

*Output is automated analysis, not financial advice.*
