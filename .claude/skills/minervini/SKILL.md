---
name: minervini
description: Rules-based buy / sell / buy-more verdict for a US stock or ETF using Mark Minervini's SEPA method from "Trade Like a Stock Market Wizard" (Trend Template, Stage Analysis, volatility contraction pattern and pivot, earnings acceleration and Code 33, 10% max stop, breakeven rule, selling into strength or weakness). Answers "Can I buy X?" (BUY / BUY ON BREAKOUT / WAIT / AVOID), "Should I sell X?" (SELL / SELL INTO STRENGTH / HOLD, TIGHTEN STOP / HOLD) and "Should I buy more X?" (ADD / ADD ON BREAKOUT / DON'T ADD), with the pivot, buy range, stop and position size. Deterministic: a script applies every rule to the last completed daily session, so the same question gives the same answer. Use when the user asks whether to buy, sell, add to or trim a stock as a trade, mentions Minervini, SEPA, VCP, the Trend Template, Stage 2 or a pivot/breakout, or invokes /minervini. For a 2-5 year investment thesis use canslim instead.
argument-hint: <TICKER> [TICKER ...] [buy|sell|add] [entry PRICE [on DATE]]
---

# Minervini SEPA verdicts

The user asks one of three questions about a ticker: **can I buy it, should I sell it, should
I buy more**. This skill answers it the way *Trade Like a Stock Market Wizard* would, using
**rules only**: the Trend Template, Stage Analysis, a volatility contraction pattern (VCP) with
a pivot, the earnings test, and the book's risk rules.

Minervini's method is for trades held from weeks to months, with a stop no more than 10% below
the entry. It is not a 2–5 year holding method; `canslim` covers that. If the user's question
is clearly about a long-term position, say so in one line and offer `canslim`.

**Determinism is the point of this skill.** All logic lives in `scripts/sepa.py` (stdlib
Python). You gather data exactly as specified, run the script, and paste its text verbatim.
Never compute, round, override or reword a verdict, level or size, and never add judgment
calls (news, "the story", chart impressions) to the verdict. The script makes it
deterministic in three ways:

- It uses only **completed daily sessions**. A bar dated today is ignored until 18:00 New York
  time, so asking twice during a trading day gives the same answer.
- It keeps only the **last 335 sessions**, so fetching a bit more or less history never changes
  a result.
- Every result prints a **fingerprint** of the data it used. Same fingerprint, same verdicts.

The rules, with which parts are the book's and which are this skill's fixed reading of
them, are in `references/methodology.md`.

## Workflow

### 1. Read the question

- **Tickers:** the symbol(s) asked about. Company names → `mcp__FMP__search` (`search-symbol`).
  FMP writes share classes with a dash (`BRK-B`).
- **Intent:** `buy` ("can I buy", "is it a buy", "should I get in", plain "analyze X"),
  `sell` ("should I sell", "exit", "take profits", "should I keep holding"), `add` ("buy more",
  "add to", "average up/down", "pyramid"). It only changes which verdict is shown first; the
  script always computes all three.
- **Position** (only what the user states; never assume):
  `entry_price` (their average cost), `entry_date` (YYYY-MM-DD; a month alone → the 1st of that
  month), `stop` (only if they say they use one). Missing entry price is fine: run anyway.
- Don't ask questions before running. The output itself asks for the entry price when it
  matters.

### 2. Gather data (run the calls in parallel)

Let `today` = today's date in New York, `from` = `today` minus 520 calendar days.

| Call | Fills |
|---|---|
| `mcp__FMP__company` (`profile-symbol`) | `type`: `"etf"` if `isEtf` or `isFund`, else `"stock"` |
| FMP chart tool (`historical-price-eod-full`; `mcp__FMP__chart` on the FMP MCP server), symbol, `from`, `to` = `today` | `bars`: every row as `[date, open, high, low, close, volume]` |
| Same tool (`historical-price-eod-light`, or `-full`), symbol `^GSPC`, same `from`/`to` | `index.bars`: every row as `[date, price]` (or `[date, close]`) |
| `mcp__FMP__statements` (`income-statement`, period `quarter`, limit 5) | `fundamentals.quarters[0]` from row 1, with the `_ya` fields from row 5 (same quarter a year earlier) |
| `mcp__FMP__statements` (`income-statement`, period `Q<n>`, limit 2), once for each of the two fiscal quarters before the newest | `quarters[1]`, `quarters[2]`: row 1 is the quarter, row 2 its year-ago |
| `mcp__FMP__calendar` (`earnings-company`, limit 5) | `fundamentals.surprise` from the newest row with a non-null `epsActual`: `eps_actual` ← `epsActual`, `eps_estimate` ← `epsEstimated`. `next_earnings` = date of the earliest row on or after `today` with a null `epsActual` |

Quarter fields: `eps` ← `epsDiluted`, `rev` ← `revenue`, `op_inc` ← `operatingIncome`,
`net_inc` ← `netIncome`, each with a `_ya` twin from the year-ago row; `label` ← period and
fiscal year (e.g. `"Q3 FY2026"`). FMP `period` labels are fiscal: if the newest is Q2, the
prior two are Q1 (same fiscal year) and Q4 (previous one).

Rules for the data:

- **Copy every number exactly as returned.** No rounding, no reformatting, no skipped rows.
  Row order doesn't matter (FMP returns newest first; the script sorts). Bars as FMP objects
  also work, but the compact arrays are shorter to write.
- **FMP plan:** keep `limit` ≤ 5 on statements and calendar (larger limits are blocked on
  this plan). The history calls take `from`/`to`, not `limit`.
- ETFs: skip the statements and calendar calls (`type: "etf"` skips the earnings test).
- If a statements call is denied, leave `fundamentals` out: the stock can still get every
  verdict except BUY / BUY ON BREAKOUT, and the output says why. If the price history is
  denied or FMP isn't connected, **stop and tell the user**. Don't reconstruct daily bars from
  web pages: a web snapshot can't reproduce 335 exact sessions, and a guessed bar breaks the
  determinism this skill exists for.
- Never set `as_of_close` (it pins the date for replays and tests only).

### 3. Run

Write one JSON file in the shape of `scripts/example_input.json` to your scratchpad (or a
temp dir): `intent`, `index`, and `tickers` (one entry per symbol, sharing one `index`). Then:

```
python3 <this skill's directory>/scripts/sepa.py /path/to/input.json
```

If code execution isn't available, say the skill needs it and stop. Hand-applying these
rules to 335 bars isn't reproducible.

### 4. Output

For each ticker, paste the script's `text` fields verbatim, in this order, skipping nulls:

```
<headline>
<verdict_lines[0]>
<verdict_lines[1]>
<verdict_lines[2]>

<trend_table_md>

<rs_line>
<setup_line>
<fundamentals_line>
<market_line>
<signals_line>
<earnings_line>
<data_line>
Flags: <flags joined with "; ">            (only if there are any)
```

Then, only when the intent is `sell` or `add` and no entry price was given, add exactly:
`Give me your entry price (and date) to apply the stop-loss and breakeven rules.`

End the message once with: *Rules-based reading of Minervini's SEPA method, not financial advice.*

Don't add a synopsis, opinions or other commentary. The verdict lines already give the
reasons, and any extra text could differ between two runs of the same question. Answer
follow-up questions ("why WAIT?", "what's a VCP?") from the script's JSON (`trend_template`,
`setup`, `fundamentals`, `signals`) and `references/methodology.md`.
