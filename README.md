# Investing-skills

Claude Code skills for investing workflows.

## Skills

### `/canslim` — IBD-style CAN SLIM analysis

Give it a US stock or ETF ticker and it runs an IBD-methodology (CAN SLIM) analysis:
quarterly and annual earnings growth, new products/new highs, supply/demand, relative
strength vs. the S&P 500, institutional sponsorship, and overall market direction. It
returns a 0–99 composite score, a **Buy / Hold / Sell** verdict, and a short synopsis of
why. ETFs are scored in a trend/relative-strength mode since earnings factors don't apply.

Usage in a Claude Code session on this repo:

```
/canslim NVDA
/canslim AAPL MSFT QQQ
```

or just ask: *"Is PLTR still a buy?"*

**Data sources:** Financial Modeling Prep (FMP) MCP tools when connected; falls back to
web search otherwise. Skill definition: `.claude/skills/canslim/SKILL.md`, scoring rubric:
`.claude/skills/canslim/references/methodology.md`.

To use the skill outside this repo, copy `.claude/skills/canslim/` into `~/.claude/skills/`.

*Output is automated analysis, not financial advice.*
