#!/usr/bin/env python3
"""Render a self-contained HTML dashboard from verdict.py's output.

Usage:
    python3 render_dashboard.py DIR                 # DIR/latest.json (+ DIR/history.jsonl) -> DIR/dashboard.html
    python3 render_dashboard.py DIR --out page.html

No network, no CDN, no dependencies: inline SVG and ~60 lines of vanilla JS for tooltips,
the history crosshair and the theme toggle. Light and dark themes follow the OS, with a
toggle. Works as a local file, behind any static server, or published as a page.

Palette: the dataviz reference palette (categorical slots validated for both modes; status
colours reserved for verdict and health states, always with an icon and a label).
"""
from __future__ import annotations

import html
import json
import os
import sys


STATUS = {  # verdict -> (status token, icon)
    "Buy More": ("good", "▲▲"), "Buy": ("good", "▲"), "Exercise Caution": ("warning", "!"),
    "Pause": ("serious", "❚❚"), "Sell": ("critical", "▼"), "Avoid": ("critical", "▼"),
}
HEALTH_STATUS = {"good": ("good", "✓"), "neutral": ("warning", "–"), "weak": ("critical", "!")}
SERIES = 7  # categorical slots used for plan segments; more entities fold into "Other"


def e(s):
    return html.escape("" if s is None else str(s), quote=True)


def num(x, d=0):
    return "n/a" if x is None else f"{x:,.{d}f}"


def money(x, d=2):
    return "n/a" if x is None else f"${x:,.{d}f}"


def pct(x, d=1, signed=True):
    if x is None:
        return "n/a"
    return f"{x:+.{d}f}%" if signed else f"{x:.{d}f}%"


# ------------------------------------------------------------------------- components
def chip(verdict, size=""):
    tok, icon = STATUS.get(verdict, ("warning", "?"))
    return (f'<span class="chip {size}"><span class="dot s-{tok}" aria-hidden="true">{icon}</span>'
            f'<span>{e(verdict)}</span></span>')


def hchip(status):
    if not status:
        return '<span class="chip"><span>n/a</span></span>'
    tok, icon = HEALTH_STATUS[status]
    return f'<span class="chip"><span class="dot s-{tok}" aria-hidden="true">{icon}</span><span>{e(status)}</span></span>'


def meter(score, status):
    if score is None:
        return '<div class="meter" role="img" aria-label="no data"><div class="track"></div></div>'
    tok = HEALTH_STATUS.get(status, ("warning", ""))[0]
    return (f'<div class="meter" role="img" aria-label="{score} out of 100"><div class="track">'
            f'<div class="fill s-{tok}" style="width:{max(2, min(100, score))}%"></div></div></div>')


def table(head, rows, cls=""):
    th = "".join(f"<th>{e(h)}</th>" for h in head)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>'


def details(summary, inner):
    return f'<details><summary>{e(summary)}</summary>{inner}</details>'


def stats_cells(s, horizon="fwd_26w"):
    if not s or not s.get(horizon):
        return ["n/a"] * 4
    h = s[horizon]
    return [pct(h["median"]), f"{h['pct_positive']}%", pct(h["p10"]), str(s["episodes"])]


# ---------------------------------------------------------------------------- ladder
# Charts are positioned HTML (left: x%), not scaled SVG, so text stays a fixed, readable size
# at any card width. Label collisions are resolved for the narrowest card (LADDER_MIN_PX).
LADDER_MIN_PX = 280


def _anchor(x, width_pct):
    """CSS class keeping a label inside the track: centred, or pinned to an edge."""
    if x - width_pct / 2 < 0:
        return "a-start"
    if x + width_pct / 2 > 100:
        return "a-end"
    return "a-mid"


def ladder(price, levels, zone=None, label_fmt=money):
    """Horizontal price line: levels as ticks, the buy zone as a wash, the price as a dot."""
    pts = [(k, v) for k, v in levels if v is not None]
    if price is None or not pts:
        return ""
    vals = [v for _, v in pts] + [price] + ([z for z in zone if z] if zone else [])
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.05 or hi * 0.02
    lo, hi = lo - pad, hi + pad

    def X(v):
        return (v - lo) / (hi - lo) * 100

    out = ['<div class="lad" role="img" aria-label="Price ladder: price against its key levels"><div class="lad-axis"></div>']
    if zone and zone[0] and zone[1]:
        za, zb = X(zone[0]), X(zone[1])
        out.append(f'<div class="lad-zone tip" tabindex="0" style="left:{za:.2f}%;width:{max(0.6, zb - za):.2f}%" '
                   f'data-tip="Buy zone {e(label_fmt(zone[0]))}–{e(label_fmt(zone[1]))}"></div>')
    rows_end = [-1e9, -1e9]
    for k, v in sorted(pts, key=lambda kv: kv[1]):
        x = X(v)
        out.append(f'<div class="lad-tick tip" tabindex="0" style="left:{x:.2f}%" data-tip="{e(k)}: {e(label_fmt(v))} '
                   f'(price {e(pct((price / v - 1) * 100))} vs it)"></div>')
        wpct = (len(k) * 6.6 + 10) / LADDER_MIN_PX * 100
        cls = _anchor(x, wpct)
        left = x if cls == "a-mid" else (x if cls == "a-start" else x)
        span = (x - wpct / 2, x + wpct / 2) if cls == "a-mid" else ((x, x + wpct) if cls == "a-start" else (x - wpct, x))
        for r in (0, 1):
            if span[0] > rows_end[r]:
                out.append(f'<div class="lad-lbl r{r} {cls}" style="left:{left:.2f}%">{e(k)}</div>')
                rows_end[r] = span[1] + 1
                break
    px = X(price)
    txt = f"now {label_fmt(price)}"
    out.append(f'<div class="lad-now tip" tabindex="0" style="left:{px:.2f}%" data-tip="Now {e(label_fmt(price))}"></div>'
               f'<div class="lad-nowlbl {_anchor(px, (len(txt) * 7 + 8) / LADDER_MIN_PX * 100)}" '
               f'style="left:{px:.2f}%">{e(txt)}</div></div>')
    return "".join(out)


def ladder_table(price, levels, zone, fmt=money):
    rows = [[e(k), e(fmt(v)), e(pct((price / v - 1) * 100))] for k, v in levels if v is not None]
    if zone and zone[0]:
        rows.append(["Buy zone", e(f"{fmt(zone[0])}–{fmt(zone[1])}"), ""])
    return details("Table view", table(["Level", "Price", "Now vs level"], rows, "num"))


# --------------------------------------------------------------------------- history
def history_chart(hist):
    if not hist:
        return '<p class="muted">History builds up with each run (verdict.py --out keeps history.jsonl).</p>'
    n = len(hist)

    def X(i):
        return 50.0 if n == 1 else i / (n - 1) * 100

    pts = [(X(i), h["health"]) for i, h in enumerate(hist) if h.get("health") is not None]
    data = [{"x": round(X(i), 2), "d": h["as_of"], "v": h["verdict"], "h": h.get("health")} for i, h in enumerate(hist)]
    out = [f'<div class="hc" data-points="{e(json.dumps(data))}"><div class="hc-plot">']
    for v in (100, 50, 0):
        out.append(f'<div class="hc-grid" style="top:{100 - v}%"></div><div class="hc-y" style="top:{100 - v}%">{v}</div>')
    if len(pts) > 1:
        d = "M" + " L".join(f"{x:.2f},{100 - y:.2f}" for x, y in pts)
        out.append(f'<svg class="hc-svg" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">'
                   f'<path class="line" d="{d}" vector-effect="non-scaling-stroke"/></svg>')
    if pts:
        lx, ly = pts[-1]
        out.append(f'<div class="hc-dot" style="left:{lx:.2f}%;top:{100 - ly:.2f}%"></div>'
                   f'<div class="hc-end {"a-end" if lx > 90 else "a-mid"}" style="left:{lx:.2f}%;top:{100 - ly:.2f}%">'
                   f'{e(hist[-1].get("health"))}</div>')
    out.append('<div class="hc-xh" hidden></div><div class="hc-ov"></div></div><div class="hc-strip">')
    for h in hist:
        tok = STATUS.get(h["verdict"], ("warning", ""))[0]
        out.append(f'<div class="cell s-{tok}" title="{e(h["as_of"])}: {e(h["verdict"])}"></div>')
    out.append(f'</div><div class="hc-x"><span>{e(hist[0]["as_of"])}</span>'
               + (f'<span>{e(hist[-1]["as_of"])}</span>' if n > 1 else "") + "</div></div>")
    legend = "".join(f'<span class="key"><span class="sw s-{tok}"></span>{e(v)}</span>'
                     for v, (tok, _) in STATUS.items() if v != "Avoid")
    rows = [[e(h["as_of"]), chip(h["verdict"]), e(num(h.get("health"))), e(h.get("health_label") or "")]
            for h in reversed(hist)]
    return ("".join(out) + f'<div class="legend"><span class="key"><span class="lk"></span>Market health (0–100)</span>'
            f'{legend}</div>' + details("Table view", table(["Run", "Verdict", "Health", ""], rows, "num")))


# -------------------------------------------------------------------------- dumbbell
def verdict_stats_chart(vstats, current):
    rows = [(k, v) for k, v in (vstats or {}).items() if v and v.get("fwd_26w")]
    if not rows:
        return ""
    lo = min(v["fwd_26w"]["p10"] for _, v in rows)
    hi = max(v["fwd_26w"]["median"] for _, v in rows)
    lo, hi = (int(lo // 10)) * 10 if lo < 0 else 0, (int(hi // 10) + 1) * 10
    ticks = list(range(lo, hi + 1, 10))

    def X(v):
        return (v - lo) / (hi - lo) * 100

    grid = "".join(f'<div class="{"db-zero" if t == 0 else "db-grid"}" style="left:{X(t):.2f}%"></div>' for t in ticks)
    out = ['<div class="db" role="img" aria-label="Median and worst-decile 26-week return after each verdict">']
    for k, v in rows:
        f = v["fwd_26w"]
        cur = k == current
        a, b = sorted((X(f["p10"]), X(f["median"])))
        tip = (f"{k}: median {f['median']:+.1f}%, {f['pct_positive']}% up, worst 10% {f['p10']:+.1f}% or worse "
               f"({v['episodes']} episodes)")
        vals = ""
        if cur:
            vals = (f'<span class="db-val a-endout" style="left:{X(f["p10"]):.2f}%">{f["p10"]:+.1f}%</span>'
                    f'<span class="db-val a-startout" style="left:{X(f["median"]):.2f}%">{f["median"]:+.1f}%</span>')
        out.append(f'<div class="db-row{" cur" if cur else ""} tip" tabindex="0" data-tip="{e(tip)}">'
                   f'<div class="db-lbl">{e(k)}</div><div class="db-plot">{grid}'
                   f'<div class="db-conn" style="left:{a:.2f}%;width:{b - a:.2f}%"></div>'
                   f'<div class="db-dot p10" style="left:{X(f["p10"]):.2f}%"></div>'
                   f'<div class="db-dot med" style="left:{X(f["median"]):.2f}%"></div>{vals}</div></div>')
    out.append('<div class="db-row db-axis"><div class="db-lbl"></div><div class="db-plot">'
               + "".join(f'<span style="left:{X(t):.2f}%">{t:+d}%</span>' for t in ticks) + "</div></div></div>")
    legend = ('<div class="legend"><span class="key"><span class="sw c-med"></span>Median next 26 weeks</span>'
              '<span class="key"><span class="sw c-p10"></span>Worst 10% (10th percentile)</span></div>')
    trows = [[(f"<strong>{e(k)}</strong>" if k == current else e(k))] + [e(c) for c in stats_cells(v)] for k, v in rows]
    return legend + "".join(out) + details("Table view", table(["Verdict", "Median 26w", "% up", "Worst 10%", "Episodes"], trows, "num"))


# --------------------------------------------------------------------------- sectors
def sector_bars(items):
    """Diverging bars around 0: sector 3-month returns, best first."""
    if not items:
        return ""
    m = max(abs(i["value"]) for i in items) or 1
    rows = []
    for i in items:
        v = i["value"]
        w = abs(v) / m * 50
        side = "pos" if v >= 0 else "neg"
        left = 50 if v >= 0 else 50 - w
        rows.append(f'<div class="sb-row tip" tabindex="0" data-tip="{e(i["label"])}: {e(pct(v))} over 3 months">'
                    f'<span class="sb-lbl">{e(i["label"])}</span><span class="sb-plot"><span class="sb-zero"></span>'
                    f'<span class="sb-bar {side}" style="left:{left:.2f}%;width:{max(w, 0.8):.2f}%"></span></span>'
                    f'<span class="sb-val">{e(pct(v))}</span></div>')
    return ('<div class="sb">' + "".join(rows) + '</div><div class="legend"><span class="key"><span class="sw c-pos">'
            '</span>Up over 3 months</span><span class="key"><span class="sw c-neg"></span>Down</span></div>')


# --------------------------------------------------------------------------- plan bar
def plan_bar(plan, tickers):
    if not plan:
        return '<p class="muted">Add a contribution (or pass an amount) to get a dollar plan.</p>'
    slots = {t: i % SERIES + 1 for i, t in enumerate(sorted(tickers))}
    parts = sorted(plan["split"].items(), key=lambda kv: (-kv[1], kv[0]))
    if plan.get("to_reserve"):
        parts.append(("Reserve", plan["to_reserve"]))
    total = sum(v for _, v in parts) or 1
    blocks, legend, rows = [], [], []
    for k, v in parts:
        cls = "c-res" if k == "Reserve" else f"c-{slots.get(k, SERIES)}"
        share = v / total * 100
        lbl = f"${v:,.0f}" if share >= 12 else ""
        blocks.append(f'<div class="seg {cls} tip" tabindex="0" style="flex:{v} 1 0" '
                      f'data-tip="{e(k)}: ${v:,.0f} ({share:.0f}%)"><span>{e(lbl)}</span></div>')
        legend.append(f'<span class="key"><span class="sw {cls}"></span>{e(k)}</span>')
        rows.append([e(k), e(f"${v:,.0f}"), e(f"{share:.0f}%")])
    head = (f'<p class="lead">Invest <strong>${plan["invest"]:,.0f}</strong> of ${plan["amount"]:,.0f}'
            + (f' (incl. ${plan["from_reserve"]:,.0f} from the reserve)' if plan["from_reserve"] else "")
            + (f' · <strong>${plan["to_reserve"]:,.0f}</strong> to the reserve' if plan["to_reserve"] else "")
            + f' · reserve after: ${plan["reserve_after"]:,.0f}</p>')
    return (head + f'<div class="segbar" role="img" aria-label="Where this period\'s money goes">{"".join(blocks)}</div>'
            + f'<div class="legend">{"".join(legend)}</div>'
            + details("Table view", table(["Where", "Amount", "Share"], rows, "num")))


# ------------------------------------------------------------------------------ page
def render(out, hist):
    v = out["verdict"]
    hl = out["health"]
    ix = out["market"]["indexes"]
    vtok = STATUS.get(v["label"], ("warning", ""))[0]
    tickers = [r["ticker"] for r in out["core"] + out["satellite"]]

    # KPI row
    kpis = []
    for k, d in ix.items():
        kpis.append(f'<div class="tile"><div class="tl">{e(d["name"])}</div><div class="tv">{e(num(d["price"]))}</div>'
                    f'<div class="td">{e(pct(d["pct_vs_40"]))} vs 40-wk · {e(pct(d["off_high_pct"], 1, False))} off high</div>'
                    f'<div class="td muted">{e(d["stage_label"])}</div></div>')
    kpis.append(f'<div class="tile"><div class="tl">Market health</div><div class="tv">{e(num(hl["score"]))}'
                f'<span class="unit">/100</span></div>{meter(hl["score"], "good" if (hl["score"] or 0) >= 70 else "neutral" if (hl["score"] or 0) >= 50 else "weak")}'
                f'<div class="td">{e(hl["label"] or "n/a")} · {e(hl["coverage"])} areas · internals {e(num(hl.get("internals_score")))}</div></div>')
    if out.get("plan"):
        p = out["plan"]
        kpis.append(f'<div class="tile"><div class="tl">This period</div><div class="tv">${p["invest"]:,.0f}</div>'
                    f'<div class="td">invest · ${p["to_reserve"]:,.0f} to reserve</div>'
                    f'<div class="td muted">reserve after ${p["reserve_after"]:,.0f}</div></div>')

    # health
    cat_rows = []
    for c in hl["categories"]:
        items = "" if c["key"] == "trend" else " · ".join(
            f'{e(i["label"])} <strong>{e(i["display"])}</strong>' for i in c["items"])
        cat_rows.append(f'<div class="hrow"><div class="hname">{e(c["name"])}<span class="muted"> {c["weight"]}%</span></div>'
                        f'{meter(c["score"], c["status"])}<div class="hscore">{e(num(c["score"]))} {hchip(c["status"])}</div>'
                        f'<div class="hread">{e(c["read"])}<div class="muted small">{items}</div></div></div>')
    ctx = []
    for c in hl["context"]:
        if c["key"] == "leadership":
            spread = c["read"].split(";")[0] if c["items"] else c["read"]
            body = f'<div class="td">{e(spread)}</div>' + sector_bars(c["items"])
        else:
            body = ("".join(f'<div class="kv"><span>{e(i["label"])}</span><strong>{e(i["display"])}</strong></div>'
                            for i in c["items"]) or f'<div class="td muted">{e(c["read"])}</div>')
        ctx.append(f'<div class="tile"><div class="tl">{e(c["name"])}</div><div class="tv sm">{e(c["status"] or "n/a")}</div>'
                   f'{body}</div>')

    # index cards
    idx_cards = []
    for k, d in ix.items():
        lv = d["levels"]
        levels = [("52-wk high", d["year_high"]), ("10-wk", d["ma10"]), ("40-wk", d["ma40"]),
                  ("40-wk +2%", lv["confirm_40w"]), ("−20% bear line", lv["bear_line"])]
        zone = None
        if k == "^GSPC" and lv["pullback"] and lv["confirm_40w"]:
            zlo = max(lv["confirm_40w"], lv["bear_line"])
            zone = (zlo, lv["pullback"]) if zlo < lv["pullback"] else None
        st = d.get("stats")
        fmt = (lambda x: num(x))
        idx_cards.append(
            f'<div class="card"><div class="ch"><h3>{e(d["name"])}</h3><span class="muted">{e(d["stage_label"])}</span></div>'
            + ladder(d["price"], levels, zone, fmt)
            + (f'<p class="small muted">Shaded: market Buy More zone {e(num(zone[0]))}–{e(num(zone[1]))} (5%+ off the high, '
               f'still 2% above the 40-wk).</p>' if zone else "")
            + f'<p class="small">{e(d["entry"]["label"] if d.get("entry") else "")}. After similar weeks (2000–23): '
            + (f'median {e(pct(st["fwd_26w"]["median"]))} over 26 weeks, {st["fwd_26w"]["pct_positive"]}% up, worst 10% '
               f'{e(pct(st["fwd_26w"]["p10"]))} ({st["episodes"]} episodes).' if st else "n/a.")
            + "</p>" + ladder_table(d["price"], levels, zone, fmt) + "</div>")

    # core cards
    core_cards = []
    for r in out["core"]:
        lv = r.get("levels") or {}
        levels = [("52-wk high", lv.get("high")), ("10-wk", lv.get("ma10")), ("40-wk", lv.get("ma40")),
                  ("−20% bear line", lv.get("bear_line"))]
        zone = (lv.get("zone_low"), lv.get("zone_high")) if lv.get("zone_low") else None
        st = r.get("stats")
        w = "" if r.get("core_weight_pct") is None else f'{r["core_weight_pct"]:.1f}% of core'
        if r.get("target_pct") is not None:
            w += f' · target {r["target_pct"]:.0f}%'
        sc = stats_cells(st)
        why = "" if r["why"].startswith("Follows the market") else f'<p class="small">{e(r["why"])}</p>'
        core_cards.append(
            f'<div class="card"><div class="ch"><h3>{e(r["ticker"])}</h3>{chip(r["verdict"])}</div>'
            f'<p class="lead">{e(r["do"])}<span class="muted"> · {e(w)}</span></p>{why}'
            + ladder(r.get("price"), levels, zone)
            + f'<p class="small"><strong>Buy zone:</strong> {e(r.get("zone"))}</p>'
            f'<p class="small">{e(r["entry"]["label"] if r.get("entry") else r.get("chart") or "")}</p>'
            f'<div class="minis"><div><div class="tl">Median 26w</div><div class="mv">{e(sc[0])}</div></div>'
            f'<div><div class="tl">% up</div><div class="mv">{e(sc[1])}</div></div>'
            f'<div><div class="tl">Worst 10%</div><div class="mv">{e(sc[2])}</div></div>'
            f'<div><div class="tl">Episodes</div><div class="mv">{e(sc[3])}</div></div></div>'
            f'<p class="small muted">What followed weeks when an index was in this same chart state, 2000–23.</p>'
            + ladder_table(r.get("price"), levels, zone) + "</div>")

    # satellite
    sat = ""
    if out["satellite"]:
        rows = []
        for r in out["satellite"]:
            w = "—" if not r["held"] else ("n/a" if r["weight_pct"] is None else f'{r["weight_pct"]:.1f}%')
            rows.append([f"<strong>{e(r['ticker'])}</strong>", e(w), chip(r["verdict"]), e(r["do"]), e(r.get("read")),
                         f'<span class="small">{e(r["why"])}</span>'])
        sat = (f'<section><h2>Satellite</h2><div class="card scroll">'
               + table(["Holding", "Of portfolio", "Verdict", "Do", "Read", "Why"], rows) + "</div></section>")

    sleeve = ""
    if out.get("sleeves"):
        s = out["sleeves"]
        sleeve = (f'<p class="small muted">Sleeves: core {s["core_pct"]:.1f}% · satellite {s["satellite_pct"]:.1f}% '
                  f'(target {100 - s["satellite_target_pct"]:g} / {s["satellite_target_pct"]:g})</p>')
    actions = "".join(f"<li>{e(a)}</li>" for a in out.get("actions") or [])
    flags = "".join(f"<li>{e(f)}</li>" for f in out.get("flags") or [])
    vs = v.get("stats")
    vstats_line = ""
    if vs and vs.get("fwd_26w"):
        f = vs["fwd_26w"]
        vstats_line = (f'<p class="small">After {e(v["label"] if v["kind"] != "repair" else "repair")} weeks in 2000–23, '
                       f'the next 26 weeks: median {e(pct(f["median"]))}, {f["pct_positive"]}% up, worst 10% '
                       f'{e(pct(f["p10"]))} or worse ({vs["episodes"]} episodes).</p>')

    vstats_all = out.get("_verdict_stats")
    body = f"""
<header class="top"><div><h1>Portfolio verdict</h1><span class="muted">{e(out["as_of"])} · {e(out["mode"])} run
· generated {e(out.get("generated_at", ""))}</span></div>
<button id="theme" type="button" aria-label="Toggle light and dark theme">◐</button></header>

<section class="herocard card">
  <div class="hv"><span class="badge s-{vtok}" aria-hidden="true">{STATUS.get(v["label"], ("", "?"))[1]}</span>
  <span class="hero">{e(v["label"])}</span></div>
  <p class="lead">{e(v["do"])}</p>
  <p><strong>Why:</strong> {e(v["why"])}</p>
  <p><strong>Changes:</strong> {e(v["next"])}</p>
  {f'<p class="note">{e(v["divergence"])}</p>' if v.get("divergence") else ""}
  {vstats_line}
  {f'<ul class="actions">{actions}</ul>' if actions else ""}
</section>

<section class="kpis">{"".join(kpis)}</section>

<section><h2>Market health <span class="muted">{e(num(hl["score"]))}/100 · {e(hl["label"] or "n/a")}</span></h2>
<div class="card">{"".join(cat_rows)}
<p class="small muted">Scored areas use practitioner thresholds, not a backtest: health is context and never changes the verdict.
Internals = everything except trend.</p></div>
<div class="grid3">{"".join(ctx)}</div></section>

<section><h2>Indexes</h2><div class="grid2">{"".join(idx_cards)}</div></section>

<section><h2>Core funds</h2>{sleeve}<div class="grid3">{"".join(core_cards)}</div></section>

{sat}

<section><h2>This period's money</h2><div class="card">{plan_bar(out.get("plan"), tickers)}</div></section>

<section><h2>History</h2><div class="card">{history_chart(hist)}</div></section>

<section><h2>What followed each verdict, 2000–23</h2><div class="card">
<p class="small">The verdicts separate risk more than they separate typical returns: medians are close, the bad tail is not.</p>
{verdict_stats_chart(vstats_all, "Buy More (repair)" if v["kind"] == "repair" else v["label"])}</div></section>

<footer>{f'<details><summary>Flags ({len(out.get("flags") or [])})</summary><ul>{flags}</ul></details>' if flags else ""}
<p class="small muted">Automated trend-following analysis, not financial advice. Historical stats: S&amp;P 500 and Nasdaq weekly
closes, {e(out["market"].get("stats_period") or "n/a")}, price only.</p></footer>
<div id="tt" role="tooltip" hidden></div>
"""
    return PAGE.replace("{{BODY}}", body).replace("{{TITLE}}", e(f"Portfolio verdict {out['as_of']}"))


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{TITLE}}</title>
<style>
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;
--baseline:#c3c2b7;--border:rgba(11,11,11,.10);--hl:rgba(42,120,214,.07);--accent:#2a78d6;--zone:rgba(42,120,214,.16);
--c1:#2a78d6;--c2:#eb6834;--c3:#1baf7a;--c4:#eda100;--c5:#e87ba4;--c6:#008300;--c7:#6250d6;--res:#c3c2b7;
--p10:#86b6ef;--pos:#2a78d6;--neg:#e34948;--good:#0ca30c;--warning:#fab219;--serious:#ec835a;--critical:#d03b3b}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;
--ink:#f0efec;--ink2:#c3c2b7;--grid:#2c2c2a;--baseline:#383835;--border:rgba(255,255,255,.10);--hl:rgba(57,135,229,.12);
--accent:#3987e5;--zone:rgba(57,135,229,.22);--c1:#3987e5;--c2:#d95926;--c3:#199e70;--c4:#c98500;--c5:#d55181;--c6:#008300;
--c7:#9085e9;--res:#52514e;--p10:#9ec5f4;--pos:#3987e5;--neg:#e66767}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--grid:#2c2c2a;
--baseline:#383835;--border:rgba(255,255,255,.10);--hl:rgba(57,135,229,.12);--accent:#3987e5;--zone:rgba(57,135,229,.22);
--c1:#3987e5;--c2:#d95926;--c3:#199e70;--c4:#c98500;--c5:#d55181;--c6:#008300;--c7:#9085e9;--res:#52514e;--p10:#9ec5f4;--pos:#3987e5;--neg:#e66767}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;padding:16px;
max-width:1240px;margin-inline:auto}
h1{font-size:20px;margin:0}h2{font-size:16px;margin:28px 0 10px}h3{font-size:15px;margin:0}
.muted{color:var(--muted)}.small{font-size:12.5px;color:var(--ink2)}.lead{font-size:15px;margin:6px 0}
.top{display:flex;justify-content:space-between;align-items:center;gap:12px}
#theme{background:var(--surface);color:var(--ink);border:1px solid var(--border);border-radius:8px;width:36px;height:36px;
font-size:16px;cursor:pointer}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px;min-width:0}
.scroll{overflow-x:auto}
.herocard{margin-top:16px}.hv{display:flex;align-items:center;gap:14px}
.hero{font-size:52px;font-weight:650;letter-spacing:-.01em;line-height:1.05}
.badge{display:inline-grid;place-items:center;width:44px;height:44px;border-radius:50%;color:#fff;font-weight:700;font-size:16px}
.s-good{background:var(--good)}.s-warning{background:var(--warning);color:#0b0b0b}.s-serious{background:var(--serious)}
.s-critical{background:var(--critical)}
.note{border-left:3px solid var(--warning);padding:6px 10px;background:var(--hl);border-radius:4px}
.actions{margin:8px 0 0;padding-left:20px}
.chip{display:inline-flex;align-items:center;gap:6px;white-space:nowrap;font-weight:600}
.chip .dot{display:inline-grid;place-items:center;width:18px;height:18px;border-radius:50%;color:#fff;font-size:9px;font-weight:700}
.chip .dot.s-warning{color:#0b0b0b}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-top:12px}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:14px;min-width:0}
.tl{font-size:12px;color:var(--ink2)}.tv{font-size:28px;font-weight:650;margin:2px 0}.tv.sm{font-size:20px;text-transform:capitalize}
.unit{font-size:14px;color:var(--muted);font-weight:500}.td{font-size:12.5px;color:var(--ink2)}
.meter .track{height:8px;border-radius:4px;background:var(--grid);overflow:hidden;margin:6px 0}
.meter .fill{height:100%;border-radius:4px}
.hrow{display:grid;grid-template-columns:140px 1fr 120px;gap:4px 14px;align-items:center;padding:10px 0;
border-bottom:1px solid var(--grid)}
.hrow:last-of-type{border-bottom:0}.hname{font-weight:600}.hread{grid-column:1/-1;font-size:13px;color:var(--ink2)}
.hscore{font-variant-numeric:tabular-nums;display:flex;gap:8px;align-items:center;justify-content:flex-end}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}
.grid3{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px;margin-top:12px}
.ch{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}
.minis{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:8px 0}.mv{font-size:16px;font-weight:650}
.tip:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.a-mid{transform:translateX(-50%)}.a-start{transform:translateX(-4px)}.a-end{transform:translateX(calc(-100% + 4px))}
.a-startout{transform:translateX(10px)}.a-endout{transform:translateX(calc(-100% - 10px))}
.lad{position:relative;height:88px;margin:8px 6px 4px}
.lad-axis{position:absolute;left:0;right:0;top:40px;height:1px;background:var(--baseline)}
.lad-zone{position:absolute;top:30px;height:20px;border-radius:4px;background:var(--zone)}
.lad-tick{position:absolute;top:31px;width:12px;height:18px;margin-left:-6px;cursor:default}
.lad-tick::before{content:"";position:absolute;left:5px;top:0;width:1.5px;height:18px;background:var(--ink2)}
.lad-tick:hover::before,.lad-tick:focus::before{background:var(--ink);width:2.5px;left:4.5px}
.lad-lbl{position:absolute;font-size:11px;color:var(--muted);white-space:nowrap}
.lad-lbl.r0{top:54px}.lad-lbl.r1{top:69px}
.lad-now{position:absolute;top:33px;width:14px;height:14px;margin-left:-7px;border-radius:50%;background:var(--accent);
border:2px solid var(--surface)}
.lad-nowlbl{position:absolute;top:8px;font-size:12px;font-weight:600;white-space:nowrap}
.hc{margin:4px 0 0 34px}.hc-plot{position:relative;height:150px;margin:8px 0}
.hc-grid{position:absolute;left:0;right:0;height:1px;background:var(--grid)}
.hc-y{position:absolute;left:-34px;width:26px;text-align:right;font-size:11px;color:var(--muted);transform:translateY(-50%);
font-variant-numeric:tabular-nums}
.hc-svg{position:absolute;inset:0;width:100%;height:100%;overflow:visible}
.line{fill:none;stroke:var(--accent);stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.hc-dot{position:absolute;width:10px;height:10px;margin:-5px 0 0 -5px;border-radius:50%;background:var(--accent);
box-shadow:0 0 0 2px var(--surface)}
.hc-end{position:absolute;font-weight:650;font-size:13px;margin-top:-26px}
.hc-xh{position:absolute;top:0;bottom:-26px;width:1px;background:var(--muted)}
.hc-ov{position:absolute;inset:0 0 -26px 0}
.hc-strip{display:flex;gap:2px;height:14px}.hc-strip .cell{flex:1;border-radius:3px;max-width:48px}
.hc-x{display:flex;justify-content:space-between;font-size:11px;color:var(--muted);margin-top:6px}
.db{margin-top:4px}
.db-row{display:grid;grid-template-columns:150px 1fr;align-items:center;height:32px;border-radius:6px}
.db-row.cur{background:var(--hl)}.db-row.cur .db-lbl{color:var(--ink);font-weight:700}
.db-lbl{font-size:12.5px;color:var(--ink2);padding-left:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.db-plot{position:relative;height:100%;margin:0 16px}
.db-grid,.db-zero{position:absolute;top:0;bottom:0;width:1px;background:var(--grid)}.db-zero{background:var(--baseline)}
.db-conn{position:absolute;top:15px;height:2px;background:var(--baseline)}
.db-dot{position:absolute;top:11px;width:10px;height:10px;margin-left:-5px;border-radius:50%;box-shadow:0 0 0 2px var(--surface)}
.db-dot.med{background:var(--accent)}.db-dot.p10{background:var(--p10)}
.db-val{position:absolute;top:8px;font-size:11.5px;font-weight:600;white-space:nowrap}
.db-axis{height:22px}.db-axis span{position:absolute;top:4px;font-size:11px;color:var(--muted);transform:translateX(-50%)}
.kv{display:flex;justify-content:space-between;gap:8px;font-size:12.5px;color:var(--ink2);padding:3px 0;
border-bottom:1px solid var(--grid)}.kv:last-child{border-bottom:0}.kv strong{color:var(--ink);font-variant-numeric:tabular-nums}
.sb{margin-top:8px}.sb-row{display:grid;grid-template-columns:44px 1fr 52px;align-items:center;gap:6px;height:20px}
.sb-lbl{font-size:11.5px;color:var(--ink2)}.sb-val{font-size:11.5px;text-align:right;font-variant-numeric:tabular-nums}
.sb-plot{position:relative;height:100%}.sb-zero{position:absolute;left:50%;top:2px;bottom:2px;width:1px;background:var(--baseline)}
.sb-bar{position:absolute;top:5px;height:10px}.sb-bar.pos{background:var(--pos);border-radius:0 4px 4px 0}
.sb-bar.neg{background:var(--neg);border-radius:4px 0 0 4px}
.c-pos{background:var(--pos)}.c-neg{background:var(--neg)}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12px;color:var(--ink2);margin:8px 0}
.key{display:inline-flex;align-items:center;gap:6px}
.sw{width:10px;height:10px;border-radius:3px;display:inline-block}
.lk{width:16px;height:2px;background:var(--accent);display:inline-block;border-radius:1px}
.c-1{background:var(--c1)}.c-2{background:var(--c2)}.c-3{background:var(--c3)}.c-4{background:var(--c4)}
.c-5{background:var(--c5)}.c-6{background:var(--c6)}.c-7{background:var(--c7)}.c-res{background:var(--res)}
.c-med{background:var(--accent);border-radius:50%}.c-p10{background:var(--p10);border-radius:50%}
.sw.s-good{background:var(--good)}.sw.s-warning{background:var(--warning)}.sw.s-serious{background:var(--serious)}.sw.s-critical{background:var(--critical)}
.segbar{display:flex;gap:2px;height:28px;margin:10px 0}
.seg{border-radius:4px;display:flex;align-items:center;padding:0 8px;font-size:12px;font-weight:600;color:#fff;min-width:2px}
.seg.c-4{color:#0b0b0b}.seg.c-res{color:var(--ink)}
.seg:hover,.seg:focus{filter:brightness(1.08);outline:none}
table{border-collapse:collapse;width:100%;font-size:13px}
th{text-align:left;font-weight:600;color:var(--ink2);border-bottom:1px solid var(--baseline);padding:6px 8px}
td{border-bottom:1px solid var(--grid);padding:6px 8px;vertical-align:top}
table.num td{font-variant-numeric:tabular-nums}
details{margin-top:8px}summary{cursor:pointer;color:var(--ink2);font-size:12.5px}
#tt{position:fixed;z-index:10;pointer-events:none;background:var(--surface);color:var(--ink);border:1px solid var(--border);
border-radius:8px;padding:6px 10px;font-size:12.5px;max-width:300px;box-shadow:0 4px 16px rgba(0,0,0,.12)}
footer{margin-top:28px}
.scroll table{min-width:680px}
@media (max-width:560px){.hv .hero{font-size:40px}.db-row{grid-template-columns:112px 1fr}
.db-axis span:nth-child(even){display:none}.hrow{grid-template-columns:1fr 90px}.hrow .meter{grid-column:1/-1;order:3}
.minis{grid-template-columns:repeat(2,1fr)}.grid2,.grid3{grid-template-columns:1fr}}
@media (forced-colors:active){.badge,.chip .dot{border:1px solid CanvasText}}
</style></head><body>
{{BODY}}
<script>
(function(){
  var tt=document.getElementById('tt');
  function show(text,x,y){tt.textContent=text;tt.hidden=false;
    var r=tt.getBoundingClientRect();var nx=Math.min(x+14,window.innerWidth-r.width-8);var ny=y-r.height-12;
    if(ny<8)ny=y+16;tt.style.left=nx+'px';tt.style.top=ny+'px';}
  function hide(){tt.hidden=true;}
  document.querySelectorAll('[data-tip]').forEach(function(el){
    el.addEventListener('pointermove',function(ev){show(el.getAttribute('data-tip'),ev.clientX,ev.clientY);});
    el.addEventListener('pointerleave',hide);
    el.addEventListener('focus',function(){var b=el.getBoundingClientRect();show(el.getAttribute('data-tip'),b.left+b.width/2,b.top);});
    el.addEventListener('blur',hide);
  });
  document.querySelectorAll('.hc').forEach(function(hc){
    var pts=JSON.parse(hc.getAttribute('data-points')||'[]');var ov=hc.querySelector('.hc-ov');var xh=hc.querySelector('.hc-xh');
    if(!pts.length||!ov)return;
    ov.addEventListener('pointermove',function(ev){
      var r=ov.getBoundingClientRect();var f=(ev.clientX-r.left)/r.width*100;
      var best=pts[0];pts.forEach(function(q){if(Math.abs(q.x-f)<Math.abs(best.x-f))best=q;});
      xh.style.left=best.x+'%';xh.hidden=false;
      show((best.h==null?'n/a':best.h)+' health · '+best.v+' · '+best.d,ev.clientX,ev.clientY);});
    ov.addEventListener('pointerleave',function(){xh.hidden=true;hide();});
  });
  var root=document.documentElement;
  try{var t=localStorage.getItem('pv-theme');if(t)root.setAttribute('data-theme',t);}catch(e){}
  document.getElementById('theme').addEventListener('click',function(){
    var dark=root.getAttribute('data-theme')?root.getAttribute('data-theme')==='dark':window.matchMedia('(prefers-color-scheme: dark)').matches;
    var next=dark?'light':'dark';root.setAttribute('data-theme',next);try{localStorage.setItem('pv-theme',next);}catch(e){}
  });
})();
</script>
</body></html>
"""


def load(dir_):
    with open(os.path.join(dir_, "latest.json")) as f:
        out = json.load(f)
    hist = []
    hp = os.path.join(dir_, "history.jsonl")
    if os.path.exists(hp):
        with open(hp) as f:
            hist = [json.loads(x) for x in f if x.strip()]
    return out, hist


def main(argv):
    args = argv[1:]
    if not args:
        sys.exit(__doc__)
    dest = None
    if "--out" in args:
        i = args.index("--out")
        dest = args[i + 1]
        del args[i:i + 2]
    out, hist = load(args[0])
    if out.get("schema_version") != 2:
        sys.exit("render_dashboard.py: expects verdict.py schema_version 2 output")
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import verdict  # noqa: E402  (for the per-verdict history table)
        stats = verdict.load_stats()
        out["_verdict_stats"] = None if not stats else stats["verdict"]
    except Exception:  # pragma: no cover - the page still renders without it
        out["_verdict_stats"] = None
    dest = dest or os.path.join(args[0], "dashboard.html")
    with open(dest, "w") as f:
        f.write(render(out, hist))
    print(f"wrote {dest}")


if __name__ == "__main__":
    main(sys.argv)
