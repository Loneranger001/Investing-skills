#!/usr/bin/env python3
"""Deterministic verdicts for the portfolio-verdict skill.

The model gathers market, ETF and stock data plus the portfolio file (schema:
example_input.json); this script turns them into one of five verdicts for the period and
for every holding, and an optional dollar plan. Stock and ETF reads come from the canslim
scorer (../../canslim/scripts/score.py), so both skills share one weekly-stage, market-gate,
thesis and holder rulebook. Same input -> same output. Stdlib only.

Usage:
    python3 verdict.py input.json        # or pipe the JSON on stdin
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
CANSLIM_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "canslim", "scripts"))
sys.path.insert(0, CANSLIM_DIR)
try:
    import score as canslim  # noqa: E402
except ImportError:  # pragma: no cover
    sys.exit(f"portfolio-verdict needs the canslim skill next to it: expected {CANSLIM_DIR}/score.py")

# ----------------------------------------------------------------------------- scale
# Worst -> best. "Avoid" is "Sell" for a ticker you don't own.
VERDICTS = ["Sell", "Pause", "Exercise Caution", "Buy", "Buy More"]
RANK = {v: i for i, v in enumerate(VERDICTS)}
RANK["Avoid"] = RANK["Sell"]

# Share of this period's contribution that goes in (the rest goes to the cash reserve),
# and share of the reserve that is deployed, per market verdict.
CONTRIB = {"Buy More": 1.0, "Buy": 1.0, "Exercise Caution": 0.5, "Pause": 0.0}
DEPLOY = {"pullback": 1.0, "repair": 0.5, "Buy": 1.0, "Exercise Caution": 0.0, "Pause": 0.0}

# ------------------------------------------------------------------------ thresholds
PULLBACK_PCT = 5.0   # S&P 500 at least this far below its 52-wk high in a confirmed uptrend
BEAR_PCT = 20.0      # an index this far below its 52-wk high is in a bear market
DEFAULTS = {
    "satellite_target_pct": 20,  # stocks + non-broad ETFs, % of the portfolio
    "band_pp": 5,                # drift allowed over a target before new money stops
    "max_position_pct": 5,       # satellite holding: no adds above this weight
    "trim_position_pct": 8,      # satellite holding: trim back to max_position_pct above this
}
BROAD_HINT = ("core = a fund tracking a broad US index or a broad style/factor slice of one "
              "(S&P 500, total market, Nasdaq-100, large-cap growth, S&P 500 momentum)")


# --------------------------------------------------------------------------- helpers
def worse(a, b):
    return a if RANK[a] <= RANK[b] else b


def num(x, d=0):
    return "n/a" if x is None else f"{x:,.{d}f}"


def money(x):
    return "n/a" if x is None else f"${x:,.2f}"


def dollars(x):
    return f"${x:,.0f}"


def pct(x, d=1):
    return "n/a" if x is None else f"{x:.{d}f}%"


def cap_first(s):
    return s[:1].upper() + s[1:] if s else s


def round_split(total, shares):
    """Split a whole-dollar total by weights so the parts add up exactly (largest remainder)."""
    total = int(round(total))
    s = sum(shares.values())
    if total <= 0 or s <= 0:
        return {k: 0 for k in shares}
    raw = {k: total * v / s for k, v in shares.items()}
    out = {k: int(math.floor(v)) for k, v in raw.items()}
    left = total - sum(out.values())
    for k in sorted(raw, key=lambda k: (raw[k] - out[k], k), reverse=True)[:left]:
        out[k] += 1
    return out


# ----------------------------------------------------------------------------- market
def drawdowns(market):
    out = {}
    for sym, d in (market or {}).items():
        p, hi = d.get("price"), d.get("year_high")
        if p and hi:
            out[sym] = max(0.0, (1 - p / hi) * 100)
    return out


def market_verdict(market):
    """Period verdict from both indexes' weekly charts. Raises if the market block is unusable.

    stage4  (any index below a falling 40-wk)                    -> Pause
    below40 (any index below its 40-wk or < 2% above it)          -> Exercise Caution
    repair  (all confirmed above, a 40-wk still falling)          -> Buy More, half the reserve
    ok + an index >= 20% off its 52-wk high (bear in one index)   -> Exercise Caution
    ok + S&P 500 >= 5% off its 52-wk high (pullback in an uptrend) -> Buy More, all the reserve
    ok                                                            -> Buy
    """
    _, _, reads = canslim.market_read(market)
    if len(reads) < 2:
        raise ValueError("market block needs ^GSPC and ^IXIC with price, ma50, ma200 "
                         "(and year_high, returns 6M/1Y)")
    regime, syms, _ = canslim.market_regime(reads)
    dd = drawdowns(market)
    nm = canslim.index_names
    flags = []
    if len(dd) < len(reads):
        flags.append("market: year_high missing for an index, pullback and bear checks use what's there")

    def confirm(k):
        return reads[k]["ma40"] * (1 + canslim.CONFIRM_PCT / 100)

    confirm_all = " and ".join(f"{canslim.INDEX_NAMES.get(k, k)} {num(confirm(k))}" for k in reads)
    lead = "^GSPC" if "^GSPC" in reads else next(iter(reads))

    if regime == "stage4":
        verdict, kind = "Pause", "Pause"
        why = f"{nm(syms)} below a falling 40-wk MA (weekly Stage 4)"
        nxt = (f"Exercise Caution once every index is back above its 40-wk MA; Buy More on weekly "
               f"closes 2% above it ({confirm_all})")
    elif regime == "below40":
        verdict, kind = "Exercise Caution", "Exercise Caution"
        parts = []
        for k in syms:
            v = reads[k]
            n = canslim.INDEX_NAMES.get(k, k)
            if v["above40"]:
                parts.append(f"{n} only {v['pct_vs_40']:+.1f}% above its 40-wk MA, not confirmed")
            else:
                parts.append(f"{n} below its 40-wk MA ({num(v['ma40'])}), 40-wk {v['slope_40w']}")
        why = "; ".join(parts)
        nxt = (f"Buy on weekly closes 2% above the 40-wk ({confirm_all}); Pause if a 40-wk turns "
               f"down with the index below it")
    elif regime == "repair":
        verdict, kind = "Buy More", "repair"
        why = (f"market repairing: back above its 40-wk MA after a decline, {nm(syms)} 40-wk "
               f"still falling")
        nxt = "the rest of the reserve goes in once every 40-wk flattens or turns up"
    else:
        bears = {k: dd[k] for k in reads if dd.get(k) is not None and dd[k] >= BEAR_PCT}
        if bears:
            verdict, kind = "Exercise Caution", "Exercise Caution"
            why = "; ".join(f"{canslim.INDEX_NAMES.get(k, k)} {dd[k]:.0f}% below its 52-wk high "
                            f"(bear-market territory) while still above a 40-wk MA lifted by the prior run"
                            for k in bears)
            levels = " and ".join(f"{canslim.INDEX_NAMES.get(k, k)} {num(market[k]['year_high'] * (1 - BEAR_PCT / 100))}"
                                  for k in bears)
            nxt = f"Buy once back within {BEAR_PCT:.0f}% of the high ({levels})"
        elif dd.get(lead) is not None and dd[lead] >= PULLBACK_PCT:
            verdict, kind = "Buy More", "pullback"
            why = (f"{canslim.INDEX_NAMES.get(lead, lead)} {dd[lead]:.1f}% below its 52-wk high "
                   f"with both indexes confirmed above a flat or rising 40-wk: a pullback in an uptrend")
            nxt = f"Exercise Caution on a weekly close under 2% above the 40-wk ({confirm_all})"
        else:
            verdict, kind = "Buy", "Buy"
            why = "both indexes confirmed above a flat or rising 40-wk MA, no pullback"
            hi = market[lead].get("year_high")
            pb = f"{canslim.INDEX_NAMES.get(lead, lead)} {num(hi * (1 - PULLBACK_PCT / 100))}" if hi else None
            nxt = ((f"Buy More on a pullback to {pb} (5% off the high) that holds 2% above the 40-wk; "
                    if pb else "") + f"Exercise Caution on a weekly close under {confirm_all}")

    return {
        "verdict": verdict, "kind": kind, "regime": regime, "why": why, "next": nxt,
        "contrib": CONTRIB[verdict], "deploy": DEPLOY[kind],
        "reads": {k: {"stage": v["stage"], "label": v["label"], "slope_40w": v["slope_40w"],
                      "ma40": v["ma40"], "pct_vs_40": round(v["pct_vs_40"], 1),
                      "off_high_pct": None if dd.get(k) is None else round(dd[k], 1)}
                  for k, v in reads.items()},
        "flags": flags,
    }


def market_line(market, mv):
    parts = []
    for k, r in mv["reads"].items():
        n = canslim.INDEX_NAMES.get(k, k)
        off = f", {r['off_high_pct']:.1f}% off high" if r["off_high_pct"] is not None else ""
        parts.append(f"{n} {num(market[k]['price'])} ({r['pct_vs_40']:+.1f}% vs 40-wk {num(r['ma40'])}, "
                     f"{r['slope_40w']}{off})")
    return " · ".join(parts)


def core_do(mv):
    v = mv["verdict"]
    if v == "Pause":
        return "Core: invest nothing new this period; the whole contribution goes to the cash reserve. Don't sell the core."
    if v == "Exercise Caution":
        return "Core: invest half the usual amount; the other half goes to the cash reserve."
    if mv["kind"] == "repair":
        return "Core: invest the usual amount plus half the cash reserve."
    if v == "Buy More":
        return "Core: invest the usual amount plus all of the cash reserve; spare cash outside the plan can go in too."
    return "Core: invest the usual amount (plus any cash reserve)."


# --------------------------------------------------------------------------- holdings
def satellite_from_canslim(r, held, quick):
    """Map canslim's new-money and holder actions onto the five-step scale: (verdict, do, why)."""
    h, nm = r["holder"]["action"], r["new_money"]["action"]
    hn, nn = r["holder"]["note"], r["new_money"]["note"]
    if not held:
        if nm == "Avoid":
            return "Avoid", "Don't buy", nn
        if nm == "Buy":
            return "Buy", "Start a position", nn
        if nm == "Buy (starter)":
            return "Buy", "Start at half size", nn
        if nm == "Buy on pullback":
            return "Exercise Caution", "Wait for the pullback level", nn
        return "Pause", "Not yet", nn
    if h == "Exit":
        return "Sell", "Exit", hn
    if h == "Reduce":
        return "Sell", "Reduce by half", hn
    if h == "Hold, re-check":
        return "Pause", "Hold; no new money", hn
    if nm == "Buy":
        return ("Buy", "Add a tranche", nn) if quick else ("Buy More", "Add a full tranche", nn)
    if nm == "Buy (starter)":
        return "Buy", "Add half a tranche", nn
    if nm == "Buy on pullback":
        return "Exercise Caution", "Hold; add only on the pullback", nn
    return "Exercise Caution", "Hold; don't add yet", nn


def strip_gate(note, gate_note):
    """canslim appends the market-gate reason to every Watchlist note; the market line covers it."""
    if gate_note and note:
        note = note.replace("; " + gate_note, "").replace(gate_note + "; ", "").replace(gate_note, "")
    return note.strip("; ").strip() or note


def read_cell(r, quick):
    bits = []
    if r["type"] == "stock" and not quick:
        bits.append(f"Q {r['quality'] if r['quality'] is not None else 'n/a'}")
    bits.append(f"T {r['timing'] if r['timing'] is not None else 'n/a'}")
    rs = (r.get("details") or {}).get("L", {}).get("rs_delta_pp")
    if rs is not None:
        bits.append(f"RS {rs:+.0f}pp")
    if r.get("thesis"):
        bits.append(f"thesis {r['thesis']['label']}")
    if r.get("weekly"):
        bits.append(r["weekly"]["label"])
    return " · ".join(bits)


def weights(holdings):
    """Market value and portfolio weight per held ticker, or (None, None) if any is unknown."""
    vals = {}
    for h in holdings:
        if not h.get("_held"):
            continue
        if h.get("value") is not None:
            vals[h["ticker"]] = float(h["value"])
        elif h.get("shares") is not None and h.get("price") is not None:
            vals[h["ticker"]] = float(h["shares"]) * float(h["price"])
        else:
            return None, None
    total = sum(vals.values())
    if total <= 0:
        return None, None
    return vals, total


def run(data):
    as_of = date.fromisoformat(data["as_of"]) if data.get("as_of") else date.today()
    market = data.get("market") or {}
    cfg = {**DEFAULTS, **(data.get("portfolio") or {})}
    quick = data.get("mode", "full") == "quick"
    holdings = [dict(h) for h in (data.get("holdings") or [])]
    flags = []

    mv = market_verdict(market)
    flags += mv["flags"]
    _, _, reads = canslim.market_read(market)
    gate_note = canslim.market_regime(reads)[2]

    # ---- canslim read per holding
    results = []
    for h in holdings:
        is_etf = h.get("type", "stock") == "etf"
        sleeve = h.get("sleeve")
        if sleeve not in ("core", "satellite"):
            sleeve = "core" if is_etf else "satellite"
            if is_etf:
                flags.append(f"{h.get('ticker')}: sleeve not given, assumed core ({BROAD_HINT})")
        if sleeve == "core" and not is_etf:
            flags.append(f"{h.get('ticker')}: a single stock can't be core, scored as satellite")
            sleeve = "satellite"
        h["_sleeve"] = sleeve
        h["_held"] = h.get("held", True) and h.get("shares", 1) != 0 and h.get("value", 1) != 0
        t = dict(h)
        if quick and not is_etf:
            t["type"], t["etf_class"] = "etf", "equity"  # trend-only read, fundamentals skipped
        r = canslim.score_ticker(t, market, as_of)
        r["type"] = "etf" if is_etf else "stock"
        results.append(r)
        flags += [f"{h.get('ticker')}: {f}" for f in r["flags"]]

    vals, total = weights(holdings)
    if vals is None and any(h["_held"] for h in holdings):
        flags.append("weights unknown (shares or value missing on a held position): drift checks and size caps skipped")
    wt = {k: v / total * 100 for k, v in vals.items()} if vals else {}
    sat_wt = sum(wt.get(h["ticker"], 0) for h in holdings if h["_sleeve"] == "satellite") if vals else None
    sat_target, band = cfg["satellite_target_pct"], cfg["band_pp"]
    sat_over = sat_wt is not None and sat_wt > sat_target + band
    # Core targets are each fund's share of the core, so a satellite sleeve that is under or over
    # its target doesn't make every core fund look off.
    core_tk = [h["ticker"] for h in holdings if h["_sleeve"] == "core"]
    raw_t = {h["ticker"]: h.get("target_pct") for h in holdings if h["_sleeve"] == "core"}
    core_tgt = {}
    if core_tk and all(v is not None for v in raw_t.values()) and sum(raw_t.values()) > 0:
        if abs(sum(raw_t.values()) - 100) > 0.5:
            flags.append(f"core target_pct values sum to {sum(raw_t.values()):g}, not 100: rescaled to 100")
        core_tgt = {k: v * 100 / sum(raw_t.values()) for k, v in raw_t.items()}
    elif any(v is not None for v in raw_t.values()):
        flags.append("target_pct missing on some core funds: core drift check skipped, new money split evenly")
    core_total = sum(vals.get(k, 0.0) for k in core_tk) if vals else 0.0
    core_wt = {k: vals.get(k, 0.0) / core_total * 100 for k in core_tk} if vals and core_total > 0 else {}

    rows = []
    for h, r in zip(holdings, results):
        tk, sleeve, held = h["ticker"], h["_sleeve"], h["_held"]
        stage = r.get("weekly") or {}
        w = wt.get(tk)
        notes = []
        if sleeve == "core":
            v, do = mv["verdict"], {"Buy More": "Usual amount + reserve", "Buy": "Usual amount",
                                    "Exercise Caution": "Half the usual amount",
                                    "Pause": "No new money; hold"}[mv["verdict"]]
            if mv["kind"] == "repair":
                do = "Usual amount + half the reserve"
            if stage.get("stage") == 4 and RANK[v] > RANK["Pause"]:
                v, do = "Pause", "No new money; hold"
                notes.append(f"{tk} itself below a falling 40-wk MA ({money(stage['ma40'])})")
            elif stage and not stage.get("above40") and RANK[v] > RANK["Exercise Caution"]:
                v, do = "Exercise Caution", "Half the usual amount"
                notes.append(f"{tk} below its own 40-wk MA ({money(stage['ma40'])})")
            cw, tgt = core_wt.get(tk), core_tgt.get(tk)
            if cw is not None and tgt is not None and cw > tgt + band and RANK[v] > RANK["Pause"]:
                v, do = "Pause", "No new money; hold"
                notes.append(f"{cw:.1f}% of the core vs {tgt:.0f}% target: new money goes to the underweight funds")
            own = stage.get("label", "no weekly read")
            rs = (r.get("details") or {}).get("L", {}).get("rs_delta_pp")
            own += "" if rs is None else f", RS {rs:+.0f}pp vs S&P"
            why = "; ".join(notes) if notes else f"Follows the market; own chart: {own}"
        else:
            v, do, why = satellite_from_canslim(r, held, quick)
            why = strip_gate(why, gate_note)
            if v not in ("Sell", "Avoid") and RANK[mv["verdict"]] <= RANK["Exercise Caution"] \
                    and RANK[v] > RANK[mv["verdict"]]:
                v = mv["verdict"]
                do = "Hold; no new money" if held else "Not yet"
                notes.append(f"market verdict is {mv['verdict']}")
            if held and w is not None and v != "Sell":
                if w > cfg["trim_position_pct"]:
                    v = "Sell"
                    do = f"Trim to {cfg['max_position_pct']:g}%"
                    if vals:
                        do += f" (≈{dollars(vals[tk] - cfg['max_position_pct'] / 100 * total)})"
                    notes.append(f"{w:.1f}% of the portfolio, over the {cfg['trim_position_pct']:g}% trim line")
                elif w > cfg["max_position_pct"] and RANK[v] > RANK["Exercise Caution"]:
                    v, do = "Exercise Caution", "Hold; no adds"
                    notes.append(f"{w:.1f}% of the portfolio, at the {cfg['max_position_pct']:g}% position cap")
            if sat_over and v not in ("Sell", "Avoid") and RANK[v] > RANK["Exercise Caution"]:
                v, do = "Exercise Caution", "Hold; no adds" if held else "Not yet"
                notes.append(f"satellite sleeve {sat_wt:.1f}% vs {sat_target:g}% target: new money goes to the core")
            if quick and r["type"] == "stock" and v == "Sell" and r["holder"]["action"] == "Reduce":
                notes.append("quick run: the full check decides Reduce vs Exit")
            if notes:
                why = cap_first(why) + "; " + "; ".join(notes)
        rows.append({"ticker": tk, "sleeve": sleeve, "held": held, "verdict": v, "do": do,
                     "why": cap_first(why), "read": read_cell(r, quick), "weight_pct": None if w is None else round(w, 1),
                     "target_pct": core_tgt.get(tk) if sleeve == "core" else None,
                     "core_weight_pct": None if core_wt.get(tk) is None else round(core_wt[tk], 1),
                     "price": h.get("price"),
                     "value": None if not vals else vals.get(tk), "canslim": {
                         "new_money": r["new_money"], "holder": r["holder"], "quality": r["quality"],
                         "timing": r["timing"], "thesis": None if not r.get("thesis") else r["thesis"]["label"],
                         "stage": stage.get("stage"), "confidence": r["confidence"]}})

    plan = make_plan(cfg, mv, rows, vals, total)
    actions = [f"{x['verdict']} {x['ticker']}: {x['do']}" for x in rows if x["verdict"] in ("Sell",)]
    sleeves = None if sat_wt is None else (f"Sleeves: core {100 - sat_wt:.1f}% · satellite {sat_wt:.1f}% "
                                           f"(target {100 - sat_target:g} / {sat_target:g})")
    return render(as_of, market, mv, rows, plan, actions, sleeves, quick, flags)


# ------------------------------------------------------------------------------- plan
def make_plan(cfg, mv, rows, vals, total):
    """Dollar split of this period's amount. None when no amount is given."""
    amount = cfg.get("amount") or cfg.get("contribution")
    if not amount:
        return None
    reserve = float(cfg.get("cash_reserve") or 0)
    new_in = amount * mv["contrib"]
    from_reserve = reserve * mv["deploy"]
    pool = new_in + from_reserve
    to_reserve = amount - new_in

    sat_ok = {"Buy More": 2.0, "Buy": 1.0}
    sat = {r["ticker"]: sat_ok[r["verdict"]] for r in rows if r["sleeve"] == "satellite" and r["verdict"] in sat_ok}
    sat_pool = pool * cfg["satellite_target_pct"] / 100 if sat else 0.0
    alloc = {}
    if sat:
        split = {k: sat_pool * v / sum(sat.values()) for k, v in sat.items()}
        if vals:  # never push a position past the per-position cap
            after = total + pool
            for k in split:
                room = max(0.0, cfg["max_position_pct"] / 100 * after - (vals.get(k) or 0.0))
                split[k] = min(split[k], room)
        alloc.update(split)
    core_pool = pool - sum(alloc.values())

    core_ok = ("Buy More", "Buy", "Exercise Caution")
    core = [r for r in rows if r["sleeve"] == "core" and r["verdict"] in core_ok]
    if core and core_pool > 0:
        tg = {r["ticker"]: (r["target_pct"] if r["target_pct"] is not None else 1.0) for r in core}
        if vals:
            base = sum(vals.get(k, 0.0) for k in tg) + core_pool
            gaps = {k: max(0.0, base * tg[k] / sum(tg.values()) - vals.get(k, 0.0)) for k in tg}
            shares = gaps if sum(gaps.values()) > 0 else tg
        else:
            shares = tg
        alloc.update({k: core_pool * v / sum(shares.values()) for k, v in shares.items()})
    elif core_pool > 0:
        to_reserve += core_pool
        pool -= core_pool
    split = round_split(sum(alloc.values()), alloc)
    split = {k: v for k, v in split.items() if v > 0}
    return {"amount": amount, "invest": int(round(sum(split.values()))), "from_reserve": round(from_reserve),
            "to_reserve": round(to_reserve), "reserve_after": round(reserve - from_reserve + to_reserve),
            "split": split}


# ----------------------------------------------------------------------------- render
def render(as_of, market, mv, rows, plan, actions, sleeves, quick, flags):
    head = f"**Portfolio verdict {as_of.isoformat()}: {mv['verdict']}**" + (" (quick run)" if quick else "")
    order = {"core": 0, "satellite": 1}
    rows.sort(key=lambda r: (order[r["sleeve"]], -1 if r["weight_pct"] is None else -r["weight_pct"], r["ticker"]))

    def esc(s):
        return str(s).replace("|", "/")

    core = [r for r in rows if r["sleeve"] == "core"]
    sat = [r for r in rows if r["sleeve"] == "satellite"]
    tables = []
    if core:
        t = ["| Core fund | Of core / target | Verdict | Do | Why |", "|---|---|---|---|---|"]
        for r in core:
            w = "n/a" if r["core_weight_pct"] is None else f"{r['core_weight_pct']:.1f}%"
            if r["target_pct"] is not None:
                w += f" / {r['target_pct']:.0f}%"
            t.append(f"| {r['ticker']} | {w} | **{r['verdict']}** | {esc(r['do'])} | {esc(r['why'])} |")
        tables.append("\n".join(t))
    if sat:
        t = ["| Satellite | Of portfolio | Verdict | Do | Read | Why |", "|---|---|---|---|---|---|"]
        for r in sat:
            w = "—" if not r["held"] else ("n/a" if r["weight_pct"] is None else f"{r['weight_pct']:.1f}%")
            t.append(f"| {r['ticker']} | {w} | **{r['verdict']}** | {esc(r['do'])} | {esc(r['read'])} | {esc(r['why'])} |")
        tables.append("\n".join(t))

    plan_line = None
    if plan:
        parts = [f"{k} {dollars(v)}" for k, v in sorted(plan["split"].items(), key=lambda kv: (-kv[1], kv[0]))]
        plan_line = (f"Plan for {dollars(plan['amount'])}: invest {dollars(plan['invest'])}"
                     + (f" (incl. {dollars(plan['from_reserve'])} from the reserve)" if plan["from_reserve"] else "")
                     + (": " + " · ".join(parts) if parts else "")
                     + (f" · to reserve {dollars(plan['to_reserve'])}" if plan["to_reserve"] else "")
                     + f" · reserve after {dollars(plan['reserve_after'])}")
    return {
        "as_of": as_of.isoformat(),
        "verdict": mv["verdict"],
        "headline": head,
        "market_line": "Market: " + market_line(market, mv),
        "why_line": "Why: " + cap_first(mv["why"]),
        "do_line": core_do(mv),
        "next_line": "Changes: " + mv["next"],
        "sleeve_line": sleeves,
        "tables_md": tables,
        "actions": actions,
        "plan_line": plan_line,
        "market": {k: v for k, v in mv.items() if k != "flags"},
        "holdings": rows,
        "plan": plan,
        "flags": flags,
    }


def main(argv):
    src = open(argv[1]) if len(argv) > 1 else sys.stdin
    with src:
        data = json.load(src)
    try:
        out = run(data)
    except ValueError as e:
        sys.exit(f"verdict.py: {e}")
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main(sys.argv)
