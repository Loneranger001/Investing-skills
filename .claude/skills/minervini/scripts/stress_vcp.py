#!/usr/bin/env python3
"""How reliably does the VCP reader recognise a known base, and how often does noise fool it?

Usage: python3 stress_vcp.py [seeds]      (default 60)

1. The designed 3-contraction VCP (synth.LEADER_BASE) at several daily noise levels:
   share of seeds where a valid VCP is found (in base or just broken out).
2. Random walks with upward drift (no designed base): share that read as a valid VCP.
Run it after changing anything in analyze_base or find_setup, and update the numbers
in references/methodology.md.
"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sepa  # noqa: E402
import synth  # noqa: E402


def setup_of(bars):
    rows, _ = sepa.parse_bars(bars, "x")
    s = sepa.Series(rows[-sepa.KEEP_BARS:])
    return sepa.find_setup(s, s.n - 1)


def random_walk(seed, n=380):
    rng = random.Random(seed)
    p = prev = 50.0
    out = []
    for d in synth.sessions("2025-04-21", n):
        p *= math.exp(rng.gauss(0.0012, 0.022))
        o = prev * (1 + rng.gauss(0, 0.005))
        h = max(o, p) * (1 + abs(rng.gauss(0, 0.008)))
        lo = min(o, p) * (1 - abs(rng.gauss(0, 0.008)))
        out.append([d, o, h, lo, p, 1e6 * math.exp(rng.gauss(0, 0.35))])
        prev = p
    return out


def main(seeds):
    print("designed VCP (20% -> 9% -> 4%), valid share by daily noise:")
    for noise in (0.003, 0.008, 0.012, 0.018):
        ok = 0
        for seed in range(seeds):
            st = setup_of(synth.bars(synth.LEADER_BASE, vol_mult=synth.LEADER_VOL, seed=seed, noise=noise))
            ok += bool(st["base"] and st["base"]["valid"])
        print(f"  noise {noise * 100:.1f}%: {ok}/{seeds} ({ok / seeds:.0%})")
    walks = seeds * 5
    fp = sum(bool((st := setup_of(random_walk(seed)))["base"] and st["base"]["valid"]) for seed in range(walks))
    print(f"random walks read as a valid VCP: {fp}/{walks} ({fp / walks:.1%})")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
