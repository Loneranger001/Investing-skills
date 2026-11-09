"""Synthetic daily bars for tests and the schema example. Deterministic (seeded).

A path is a list of (session, price) anchors joined log-linearly, with small seeded noise
around it, so the rules can be exercised on charts whose shape is known in advance.
"""
import math
import random
from datetime import date, timedelta


def sessions(start, n):
    d, out = date.fromisoformat(start), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def path(anchors, n):
    pts = sorted(anchors)
    out = []
    for i in range(n):
        if i <= pts[0][0]:
            out.append(pts[0][1])
            continue
        if i >= pts[-1][0]:
            out.append(pts[-1][1])
            continue
        for (i0, p0), (i1, p1) in zip(pts, pts[1:]):
            if i0 <= i <= i1:
                w = (i - i0) / (i1 - i0)
                out.append(math.exp(math.log(p0) + w * (math.log(p1) - math.log(p0))))
                break
    return out


def bars(anchors, n=380, start="2025-04-21", seed=7, noise=0.003, vol=1_000_000, vol_mult=None):
    """[[date, open, high, low, close, volume], ...] oldest first.

    vol_mult: list of (from_session, to_session, multiplier) applied to the volume.
    """
    rng = random.Random(seed)
    ds, base = sessions(start, n), path(anchors, n)
    out, prev = [], base[0]
    for i, (d, p) in enumerate(zip(ds, base)):
        c = p * (1 + rng.gauss(0, noise))
        o = prev * (1 + rng.gauss(0, noise / 2))
        h = max(o, c) * (1 + abs(rng.gauss(0, noise)))
        lo = min(o, c) * (1 - abs(rng.gauss(0, noise)))
        m = 1.0
        for a, b, k in vol_mult or []:
            if a <= i <= b:
                m = k
        v = vol * m * (1 + rng.gauss(0, 0.08))
        out.append([d, round(o, 2), round(h, 2), round(lo, 2), round(c, 2), int(v)])
        prev = c
    return out


def closes(anchors, n=380, start="2025-04-21", seed=11, noise=0.002):
    return [[d, c] for d, _, _, _, c, _ in bars(anchors, n, start, seed, noise)]


# Reusable shapes (n = 380 sessions, the last one is 2026-10-02 with the default start).
SP500_UP = [(0, 5000), (120, 5400), (250, 5900), (379, 6500)]
SP500_DOWN = [(0, 6500), (150, 6600), (250, 5600), (379, 4700)]

# Stage 2 leader: a 4-month advance, then a 3-contraction VCP (20%, ~9%, ~4%) with
# volume drying up into the right side. Ends below the ~94 pivot.
LEADER_BASE = [(0, 48), (200, 58), (300, 100), (315, 80), (330, 96), (340, 87.5),
               (350, 94), (357, 90.8), (366, 93.2), (379, 92.6)]
LEADER_VOL = [(200, 300, 1.4), (300, 315, 1.2), (330, 350, 0.8), (351, 379, 0.55)]

FUNDAMENTALS_STRONG = {
    "quarters": [
        {"label": "Q3 FY26", "eps": 1.30, "eps_ya": 0.90, "rev": 520, "rev_ya": 400,
         "op_inc": 160, "op_inc_ya": 108, "net_inc": 130, "net_inc_ya": 88},
        {"label": "Q2 FY26", "eps": 1.10, "eps_ya": 0.82, "rev": 470, "rev_ya": 380,
         "op_inc": 138, "op_inc_ya": 100, "net_inc": 110, "net_inc_ya": 80},
        {"label": "Q1 FY26", "eps": 0.95, "eps_ya": 0.76, "rev": 430, "rev_ya": 365,
         "op_inc": 120, "op_inc_ya": 94, "net_inc": 95, "net_inc_ya": 74},
    ],
    "surprise": {"eps_actual": 1.30, "eps_estimate": 1.21},
}
