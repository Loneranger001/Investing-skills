# Methodology: Minervini SEPA verdicts

`scripts/sepa.py` is the source of truth; this file documents it. Each rule is marked:

- **Book**: stated in *Trade Like a Stock Market Wizard* (Minervini, 2013) as a rule or number.
- **Skill**: the book describes a pattern or principle without a number (or leaves it to the
  trader's eye), and this skill fixes one so the answer can't drift. Change these in
  `sepa.py` and here together, and update `scripts/test_sepa.py` on purpose.

SEPA (Specific Entry Point Analysis) has five parts: trend, fundamentals, catalyst, entry point
and exit point. The catalyst part is left out on purpose: judging whether news is a real
catalyst is a judgment call, and judgment calls are what make two runs disagree.

## Determinism

| Source of drift | How it's removed |
|---|---|
| Live prices change during the day | Only completed sessions count. A bar dated today is dropped until 18:00 New York time (`SESSION_CUTOFF_ET`); the clock is read in `America/New_York`, with a built-in US DST rule if the tz database is missing. |
| More or less history fetched | Only the last 335 sessions are kept (`KEEP_BARS` = the 65-week base window as of 10 sessions ago, the longest lookback any rule uses). The S&P 500 is trimmed to the dates the 12-month RS reads. |
| Row order, objects vs arrays | Bars are parsed, de-duplicated and sorted before use. |
| Model judgment | None of the inputs is a judgment. News, analyst views and chart impressions never reach the script. |
| How the question is worded | All three verdicts are always computed; `intent` only picks which one heads the output. |
| Unnoticed input differences | `fingerprint`: SHA-256 over the trimmed bars, index rows, fundamentals, position, type, earnings date and `RULES_VERSION`. Same fingerprint, same verdicts. |

Between two sessions a verdict can change, and should: there is a new bar.

## Trend Template (Book)

All eight must pass. Moving averages are simple averages of daily closes; the 52-week high
and low use daily highs and lows over the last 252 sessions.

| # | Criterion | Test |
|---|---|---|
| 1 | Price above the 150-day and 200-day MA | close > SMA150 and close > SMA200 |
| 2 | 150-day above the 200-day | SMA150 > SMA200 |
| 3 | 200-day trending up for at least 1 month (4–5 months preferred) | SMA200 today > SMA200 21 sessions ago. Months of continuous rise (up to 5) are shown, not scored. |
| 4 | 50-day above the 150-day and 200-day | SMA50 > SMA150 and SMA50 > SMA200 |
| 5 | Price above the 50-day | close > SMA50 |
| 6 | At least 30% above the 52-week low | close ≥ 1.30 × 52-wk low |
| 7 | Within 25% of the 52-week high | close ≥ 0.75 × 52-wk high |
| 8 | RS ranking ≥ 70 (80s–90s preferred) | RS proxy ≥ 70, see below |

### RS proxy (Skill)

IBD's RS Rating ranks a stock's 12-month performance against every stock, which needs
whole-market data this skill doesn't have. The proxy uses IBD's weighting: 40% on the last 3
months, 20% each on 6, 9 and 12 months (63/126/189/252 sessions), computed for the stock and
the S&P 500 on the same dates. The difference in percentage points maps to a 1–99 proxy:

`−40→5, −20→20, −10→35, 0→50, +10→70, +20→80, +35→90, +60→97, +100→99`

So TT8 passes when the stock beats the S&P 500 by 10pp or more on the weighted measure. This
matches the leader bar `canslim` uses (+10pp). The anchor points assume a typical
cross-sectional spread of stock returns; they are not fitted to IBD's numbers, and the output
always labels the figure "proxy". The RS line (stock ÷ S&P 500) at or near its 52-week high is
reported but not scored.

## Stage Analysis (Book, with Skill boundaries)

| Stage | Test |
|---|---|
| 2 (advancing) | Trend Template #1–#3 pass |
| 4 (declining) | close < SMA200 and SMA200 falling (lower than 21 sessions ago) |
| 1 (basing) | SMA200 flat or falling, not Stage 4 |
| 3 (topping) | SMA200 still rising but close below it |
| "not yet Stage 2" | SMA200 rising, close above it, but #1 or #2 fails |

## The setup: base, VCP and pivot (Skill reading of the Book's VCP)

The book: a constructive base shows two to six contractions, each smaller than the one
before, from left to right. Volume dries up as the base tightens. The pivot is the high of the
final, tightest contraction, and the entry is the move through the pivot on rising volume.
Bases last 3 to 65 weeks. The numbers below make that mechanical.

**Base** as of a given day: the base high is the highest high of the last 65 weeks (325
sessions). If that high is less than 15 sessions old, the stock is at new highs and there is
no base.

**Contractions**: take every bar from the base high on whose high no later bar has exceeded
(these step down left to right). Walk them in order. A bar starts a new contraction only if:

1. price rallied at least 2% (`SWING_PCT`) into its high from the current contraction's low,
2. price then pulled back at least 2% after that bar (a single bar's own range doesn't count), and
3. that pullback didn't undercut the current contraction's low.

A lower low extends the current contraction; small wiggles are absorbed into it. Each
contraction's depth = (high − low) / high. The **pivot** is the last contraction's high.

**Valid VCP** (all required):

| Check | Rule |
|---|---|
| Contractions | at least 2 |
| Tightening | each contraction no deeper than the one before it + 1pp (`TIGHTEN_TOL_PP`) |
| Final contraction | ≤ 10% (`FINAL_MAX_PCT`) |
| Base depth | ≤ 50% from the base high (`DEPTH_MAX_PCT`); over 35% is flagged |
| Volume dry-up | the quietest 5 sessions of the last 15 average ≤ 0.75× the base's average daily volume (`DRYUP_RATIO`). The base average is used, not the 50-day, because a long quiet stretch drags the 50-day down with it. |

**Breakout**: the first close above a base's pivot in the last 10 sessions
(`BREAKOUT_WINDOW`), with the base measured the day before. The earliest one in the window
is used, because pauses after a breakout can look like small bases with their own "pivots".
It's **volume-confirmed** once any close above the pivot since then came on ≥ 1.4× the 50-day
average volume (`BREAKOUT_VOL`). The **buy range** is the pivot to 5% above it
(`BUY_RANGE_PCT`).

Stress test (`scripts/stress_vcp.py`, 60 seeds per noise level): a designed 3-contraction VCP
(20% → 9% → 4%) was recognised as valid in 100% of runs at 0.3% daily noise, 87–88% at
0.8–1.2%, and 60% at 1.8%. At 1.8% the daily noise is close to the size of the 4% final
contraction, so the base isn't tight any more. On 300 random-walk charts with upward drift,
3.3% read as a valid VCP, before the Trend Template and earnings filters remove more.

Not implemented: the power play (high tight flag), cheat and low-cheat entries, and
IPO bases (the Trend Template needs 221 sessions). These stocks get WAIT with the reason.

## Earnings (Book principles, Skill thresholds)

Stocks only; ETFs skip this. The last three reported quarters each have a year-ago
comparison, from GAAP income statements.

- **GAAP distortion (Skill):** if the latest quarter's EPS growth and operating-income growth
  differ by more than 25pp, growth is measured on operating income for all quarters (flagged).
  This catches one-off gains, impairments and tax items.
- **Required:**
  1. latest-quarter earnings growth ≥ +20% (`EPS_MIN_PCT`). A profit against a year-ago
     loss passes as a turnaround (flagged); a current loss fails.
  2. latest-quarter sales growth > 0. The book wants sales growth behind earnings growth;
     earnings growth from cost cuts alone is low quality.
- **Shown, not required:** EPS acceleration (latest > prior quarter), sales acceleration,
  net-margin expansion vs the year-ago quarter, the latest EPS surprise (FMP's
  adjusted `epsActual` vs `epsEstimated`, from the same source so they're comparable), and
  **Code 33** (Book): EPS growth, sales growth and net margin each rising across the last
  three quarters.
- Grades: FAIL (a requirement fails) → new money AVOID. INCOMPLETE/MISSING → at most WAIT.
  PASS → eligible.

## Market (Skill)

The book's stage idea applied to the S&P 500. It gates **new money only**, never holders.

| Regime | Test | Effect |
|---|---|---|
| uptrend | close above SMA50 and a rising SMA200 | normal size |
| correction | anything else that isn't a downtrend | half size |
| downtrend | close below a falling SMA200 | no new buys (WAIT) |

## Verdicts

### Can I buy? (first match wins)

1. Fewer than 221 sessions → **WAIT** (Trend Template can't be checked).
2. Stage 4 → **AVOID**.
3. Trend Template #1–#3 fail (not Stage 2) → **AVOID**.
4. Earnings FAIL → **AVOID**.
5. Any of Trend Template #4–#8 fails or is unknown → **WAIT**, listing what's missing.
6. Earnings not available → **WAIT**.
7. Market downtrend → **WAIT**.
8. Breakout in the last 10 sessions:
   base not a valid VCP → **WAIT**; close back below the pivot → **WAIT** (failed);
   more than 5% above the pivot → **WAIT** (extended); not volume-confirmed → **WAIT**;
   otherwise → **BUY**.
9. In a base: valid VCP → **BUY ON BREAKOUT** (pivot, volume needed, buy range, stop, size);
   otherwise → **WAIT** with the failing checks.
10. No base (new high in the last 3 weeks) → **WAIT** for a new base.

Earnings within 7 days adds a note to a BUY or BUY ON BREAKOUT (a gap can jump the stop) but
doesn't change it (Skill).

### Stop and size (Book: 10% max loss, 1.25–2.5% account risk; Skill: the exact stop)

- Entry = the last close (BUY) or the pivot (BUY ON BREAKOUT).
- Stop = the last contraction's low, but never more than 10% below the entry
  (`MAX_STOP_PCT`).
- Size = 1.25% account risk ÷ stop distance, capped at 25% of the account, halved in a
  correction market. The book allows up to 2.5% risk when trading well; the output uses 1.25%.
- Breakeven rule: once the gain reaches 2× the initial risk (`BREAKEVEN_R`), the stop moves to
  the entry. A 2R gain is never allowed to become a loss.

### Should I sell? (first match wins)

1. **SELL** if any of the following holds:
   - With an entry price: close ≤ stop (the user's stop or 10% below the entry, whichever is
     tighter). With an entry date: the position was up 2R and is now back at or below the
     entry.
   - Stage 4, or close below the 200-day (the Stage 2 uptrend is broken).
   - Two or more weakness signals (selling into weakness: Stage 3 warnings):
     - the largest one-day drop (≤ −3%) or one-week drop (≤ −5%) since the advance began
       (from the lowest close of the last 52 weeks) came in the last 10 sessions;
     - a down close below the 50-day on ≥ 1.5× the 50-day average volume in the last 5
       sessions, and still below it;
     - a failed breakout: back below the pivot of a VCP breakout from the last 10 sessions.
2. **SELL INTO STRENGTH** if, with price above the 50-day (and the position in profit, if the
   entry is known), there is an acceleration sign (up ≥ 25% in ≤ 15 sessions, or ≥ 70% above
   the 200-day) plus at least one more climax sign: the largest one-day gain of the advance
   (≥ 4%) in the last 10 sessions, 7+ up closes in the last 10, or a gap up (low > prior
   high + 1%) in the last 5 sessions. (Book principle: climax runs mark tops, so sell into
   the strength. The thresholds are Skill.)
3. **HOLD, TIGHTEN STOP** if there is one weakness signal, an acceleration sign on its own, or
   any failed Trend Template criterion.
4. **HOLD** otherwise. The output gives the stop (if the entry is known) and the 50-day as the
   trend line.

Big up days, gaps and runs of up closes without an acceleration sign are normal breakout
behaviour and raise no warning.

### Should I buy more? (first match wins)

1. Price below the entry → **DON'T ADD** (Book: never average down).
2. Holder verdict isn't HOLD → **DON'T ADD**.
3. New-money verdict BUY → **ADD** (smaller than the first buy). BUY ON BREAKOUT → **ADD ON
   BREAKOUT**.
4. Otherwise → **DON'T ADD** (no low-risk entry point).

Without an entry price, ADD verdicts carry "only if your position shows a profit".

## Parameters

| Constant | Value | Source |
|---|---|---|
| `TT_LOW_PCT`, `TT_HIGH_PCT`, `RS_MIN`, `MONTH` | 30%, 25%, 70, 21 sessions | Book |
| `MAX_STOP_PCT`, `RISK_PCT` / `RISK_PCT_HIGH` | 10%, 1.25% / 2.5% | Book |
| `BASE_MIN_SESSIONS`, `BASE_MAX_SESSIONS` | 15 (3 wks), 325 (65 wks) | Book |
| `RS_WEIGHTS`, `RS_PTS` | 3/6/9/12-mo at 40/20/20/20; +10pp ≈ 70 | Skill |
| `SWING_PCT`, `TIGHTEN_TOL_PP`, `FINAL_MAX_PCT` | 2%, 1pp, 10% | Skill |
| `DEPTH_MAX_PCT`, `DEPTH_IDEAL_PCT` | 50%, 35% | Skill |
| `DRYUP_RATIO`, `BREAKOUT_VOL`, `BUY_RANGE_PCT`, `BREAKOUT_WINDOW` | 0.75, 1.4×, 5%, 10 | Skill |
| `MAX_POSITION_PCT`, `BREAKEVEN_R` | 25%, 2R | Skill |
| `EPS_MIN_PCT`, `GAAP_GAP_PP` | +20%, 25pp | Skill |
| `HEAVY_VOL`, `CLIMAX_RUN_PCT` / `_SESSIONS`, `CLIMAX_UP_DAYS`, `CLIMAX_EXT_200` | 1.5×, 25% / 15, 7 of 10, 70% | Skill |
| `EARNINGS_NEAR_DAYS`, `SESSION_CUTOFF_ET` | 7 days, 18:00 New York | Skill |

## Known limits

- The RS figure is a proxy, not IBD's rating.
- VCP recognition is a heuristic. It's tuned so that clean, textbook bases pass and sloppy ones
  (widening contractions, no volume dry-up) fail. A trader's eye will sometimes disagree on
  bases that are borderline.
- The tests run on synthetic charts (`synth.py`) whose correct verdicts are known by
  construction. Before trusting the thresholds, check a few live verdicts against charts you
  know.
- Daily bars come from the FMP MCP tool and are written into the input file by the model.
  The script validates them (dates, high/low consistency, gaps over 7 days), and the
  fingerprint shows whether two runs saw the same data.

## Checking reliability

```
cd scripts
python3 -m unittest -v test_sepa.py   # rules and determinism
python3 stress_vcp.py                 # VCP recognition rate under noise, false-positive rate
```

The tests cover the setups (VCP in base, volume and light-volume breakouts, extended, loose
base, Stage 4), the gates (weak or missing earnings, ETFs, bear market, GAAP distortion,
earnings proximity), the holder rules (stop, breakeven, never average down, adding to a
winner, climax), and determinism. That includes: same input twice; reordered or
reformatted rows; more history fetched; intent changing only the headline; a live bar at
11:00 and 15:30 New York time giving the same answer, and being used after 18:00; the DST
fallback matching the tz database.
