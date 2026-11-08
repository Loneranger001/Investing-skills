"""Regression tests for sepa.py. Run: python3 -m unittest -v test_sepa.py (from this dir).

Charts are synthetic (synth.py): each scenario is built so its correct verdict is known in
advance. If you change a threshold in sepa.py, expect some of these to move and update
them on purpose.
"""
import copy
import json
import os
import unittest
from datetime import datetime, timezone

import sepa
import synth

HERE = os.path.dirname(os.path.abspath(__file__))
N = 380
IDX_UP = synth.closes(synth.SP500_UP, n=N)
IDX_DOWN = synth.closes(synth.SP500_DOWN, n=N)

BASE = synth.LEADER_BASE
BREAKOUT = BASE[:-1] + [(376, 93.0), (377, 93.4), (378, 96.6), (379, 97.2)]
BREAKOUT_VOL = synth.LEADER_VOL + [(378, 379, 2.6)]
LIGHT_BREAKOUT_VOL = synth.LEADER_VOL + [(378, 379, 0.75)]  # ~1.15x the 50-day average
EXTENDED = BASE[:-3] + [(366, 93.2), (370, 93.6), (379, 106.0)]
EXTENDED_VOL = synth.LEADER_VOL[:-1] + [(351, 369, 0.55), (370, 379, 1.8)]
STAGE4 = [(0, 100), (150, 106), (379, 50)]
CLIMAX = [(0, 40), (200, 60), (330, 100), (364, 105), (379, 142)]
CLIMAX_VOL = [(364, 379, 2.0)]
# A Stage 2 stock in a base that is sloppy: the last contraction is deeper than the one before.
LOOSE = [(0, 48), (200, 58), (300, 100), (315, 88), (330, 97), (345, 82), (360, 93), (379, 91)]

WEAK_FUND = {"quarters": [
    {"label": "Q3", "eps": 1.05, "eps_ya": 1.00, "rev": 410, "rev_ya": 400, "op_inc": 100, "op_inc_ya": 96,
     "net_inc": 80, "net_inc_ya": 78},
    {"label": "Q2", "eps": 1.00, "eps_ya": 0.97, "rev": 400, "rev_ya": 395, "op_inc": 98, "op_inc_ya": 95,
     "net_inc": 77, "net_inc_ya": 76},
]}


def make(anchors, vol=None, fund=synth.FUNDAMENTALS_STRONG, idx=IDX_UP, pos=None, intent="buy",
         ttype="stock", earnings=None):
    b = synth.bars(anchors, n=N, vol_mult=vol)
    t = {"ticker": "TEST", "type": ttype, "bars": b, "fundamentals": fund, "position": pos or {}}
    if earnings:
        t["next_earnings"] = earnings
    return {"as_of_close": b[-1][0], "intent": intent,
            "index": {"symbol": "^GSPC", "bars": idx}, "tickers": [t]}


def run(*a, **k):
    return sepa.run(make(*a, **k))[0]


def verdicts(r):
    return r["verdicts"]["buy"]["verdict"], r["verdicts"]["sell"]["verdict"], r["verdicts"]["add"]["verdict"]


class Helpers(unittest.TestCase):
    def test_interp(self):
        pts = [(0, 0), (10, 100)]
        self.assertEqual(sepa.interp(-1, pts), 0)
        self.assertEqual(sepa.interp(11, pts), 100)
        self.assertAlmostEqual(sepa.interp(2.5, pts), 25)

    def test_rs_proxy_anchor_points(self):
        self.assertEqual(sepa.half_up(sepa.interp(10, sepa.RS_PTS)), 70)
        self.assertEqual(sepa.half_up(sepa.interp(0, sepa.RS_PTS)), 50)

    def test_parse_accepts_objects_arrays_and_newest_first(self):
        arr = synth.bars(BASE, n=N)
        objs = [{"date": d, "open": o, "high": h, "low": lo, "close": c, "volume": v}
                for d, o, h, lo, c, v in arr]
        a, _ = sepa.parse_bars(arr, "x")
        b, _ = sepa.parse_bars(list(reversed(objs)), "x")
        self.assertEqual(a, b)

    def test_light_endpoint_price_key(self):
        rows, _ = sepa.parse_bars([{"date": "2026-01-02", "price": 10.0, "volume": 5}], "x")
        self.assertEqual(rows[0][4], 10.0)


class Setups(unittest.TestCase):
    def test_vcp_in_base_is_buy_on_breakout(self):
        r = run(BASE, synth.LEADER_VOL)
        self.assertEqual(verdicts(r), ("BUY ON BREAKOUT", "HOLD", "ADD ON BREAKOUT"))
        self.assertEqual(r["trend_template"]["passed"], 8)
        base = r["setup"]["base"]
        self.assertTrue(base["valid"])
        self.assertEqual(len(base["contractions"]), 3)
        depths = [c["depth_pct"] for c in base["contractions"]]
        self.assertEqual(depths, sorted(depths, reverse=True))
        self.assertAlmostEqual(r["setup"]["pivot"], 94.0, delta=1.0)
        plan = r["verdicts"]["buy"]["plan"]
        self.assertLessEqual(plan["stop_pct"], sepa.MAX_STOP_PCT)
        self.assertAlmostEqual(plan["stop"], base["final_low"], places=6)

    def test_breakout_on_volume_is_buy(self):
        r = run(BREAKOUT, BREAKOUT_VOL)
        self.assertEqual(verdicts(r)[0], "BUY")
        self.assertEqual(r["setup"]["state"], "breakout")
        self.assertTrue(0 < r["setup"]["pct_vs_pivot"] <= sepa.BUY_RANGE_PCT)
        self.assertEqual(verdicts(r)[2], "ADD")

    def test_breakout_on_light_volume_waits(self):
        r = run(BREAKOUT, LIGHT_BREAKOUT_VOL)
        self.assertEqual(verdicts(r)[0], "WAIT")
        self.assertIn("light volume", r["verdicts"]["buy"]["note"])

    def test_extended_past_buy_range_waits(self):
        r = run(EXTENDED, EXTENDED_VOL)
        self.assertEqual(verdicts(r)[0], "WAIT")
        self.assertIn("extended", r["verdicts"]["buy"]["note"])
        self.assertGreater(r["setup"]["pct_vs_pivot"], sepa.BUY_RANGE_PCT)

    def test_loose_base_is_not_a_vcp(self):
        r = run(LOOSE, synth.LEADER_VOL)
        self.assertEqual(verdicts(r)[0], "WAIT")
        self.assertFalse(r["setup"]["base"]["valid"])

    def test_stage4_is_avoid_and_sell(self):
        r = run(STAGE4)
        self.assertEqual(r["stage"]["stage"], 4)
        self.assertEqual(verdicts(r), ("AVOID", "SELL", "DON'T ADD"))


class Gates(unittest.TestCase):
    def test_weak_earnings_avoid(self):
        r = run(BASE, synth.LEADER_VOL, fund=WEAK_FUND)
        self.assertEqual(verdicts(r)[0], "AVOID")
        self.assertIn("EPS +5%", r["verdicts"]["buy"]["note"])

    def test_missing_fundamentals_wait(self):
        r = run(BASE, synth.LEADER_VOL, fund=None)
        self.assertEqual(verdicts(r)[0], "WAIT")

    def test_etf_skips_fundamentals(self):
        r = run(BASE, synth.LEADER_VOL, fund=None, ttype="etf")
        self.assertEqual(verdicts(r)[0], "BUY ON BREAKOUT")

    def test_bear_market_blocks_new_buys_not_holders(self):
        r = run(BASE, synth.LEADER_VOL, idx=IDX_DOWN)
        self.assertEqual(r["market"]["regime"], "downtrend")
        self.assertEqual(verdicts(r)[0], "WAIT")
        self.assertEqual(verdicts(r)[1], "HOLD")

    def test_gaap_distortion_uses_operating_income(self):
        f = copy.deepcopy(synth.FUNDAMENTALS_STRONG)
        f["quarters"][0]["eps"] = 3.50  # one-off gain: +289% EPS vs +48% operating income
        r = run(BASE, synth.LEADER_VOL, fund=f)
        self.assertEqual(r["fundamentals"]["basis"], "op_inc")
        self.assertTrue(any("GAAP" in x for x in r["text"]["flags"]))

    def test_earnings_soon_is_flagged_not_blocking(self):
        r = run(BASE, synth.LEADER_VOL, earnings="2026-10-06")
        self.assertEqual(verdicts(r)[0], "BUY ON BREAKOUT")
        self.assertIn("earnings in 4 days", r["verdicts"]["buy"]["note"])


class Holders(unittest.TestCase):
    def test_stop_hit_is_sell(self):
        r = run(BASE, synth.LEADER_VOL, pos={"entry_price": 104.0, "entry_date": "2026-06-20"}, intent="sell")
        self.assertEqual(verdicts(r)[1], "SELL")
        self.assertIn("stop hit", r["verdicts"]["sell"]["note"])
        self.assertTrue(r["text"]["headline"].startswith("**TEST: SELL**"))

    def test_gain_turned_into_loss_is_sell(self):
        # bought at 80 in the advance, it ran to ~100 (+25%, > 2x a 10% risk); now 92 is fine...
        r = run(BASE, synth.LEADER_VOL, pos={"entry_price": 80.0, "entry_date": "2026-04-01"})
        self.assertEqual(verdicts(r)[1], "HOLD")
        self.assertIn("breakeven", r["verdicts"]["sell"]["note"])
        # ...but bought at 93 after a run to 100 that didn't reach 2R, then at 92: stop not hit.
        r = run(BASE, synth.LEADER_VOL, pos={"entry_price": 93.0, "entry_date": "2026-06-01", "stop": 86.0})
        self.assertEqual(verdicts(r)[1], "HOLD")
        # A 2R gain that has become a loss: entry 75 (stop 70), peak ~100, close forced below 75.
        b = synth.bars(BASE, n=N, vol_mult=synth.LEADER_VOL)
        b[-1] = [b[-1][0], 76.0, 76.5, 73.0, 74.0, 3_000_000]
        data = make(BASE, synth.LEADER_VOL, pos={"entry_price": 75.0, "entry_date": "2026-03-20", "stop": 70.0})
        data["tickers"][0]["bars"] = b
        r = sepa.run(data)[0]
        self.assertEqual(verdicts(r)[1], "SELL")
        self.assertIn("never let a 2R gain become a loss", r["verdicts"]["sell"]["note"])

    def test_never_average_down(self):
        r = run(BASE, synth.LEADER_VOL, pos={"entry_price": 96.0}, intent="add")
        self.assertEqual(verdicts(r)[2], "DON'T ADD")
        self.assertIn("never average down", r["verdicts"]["add"]["note"])
        self.assertTrue(r["text"]["headline"].startswith("**TEST: DON'T ADD**"))

    def test_add_to_winner_on_breakout(self):
        r = run(BREAKOUT, BREAKOUT_VOL, pos={"entry_price": 70.0, "entry_date": "2026-03-01"}, intent="add")
        self.assertEqual(verdicts(r)[2], "ADD")

    def test_climax_run_is_sell_into_strength(self):
        r = run(CLIMAX, CLIMAX_VOL, intent="sell")
        self.assertEqual(verdicts(r)[1], "SELL INTO STRENGTH")
        self.assertGreaterEqual(len(r["signals"]["climax"]), 2)
        self.assertEqual(verdicts(r)[2], "DON'T ADD")


class Determinism(unittest.TestCase):
    def test_same_input_same_output(self):
        data = make(BASE, synth.LEADER_VOL)
        a = json.dumps(sepa.run(copy.deepcopy(data)), sort_keys=True)
        b = json.dumps(sepa.run(copy.deepcopy(data)), sort_keys=True)
        self.assertEqual(a, b)

    def test_row_order_and_format_dont_matter(self):
        data = make(BASE, synth.LEADER_VOL)
        alt = copy.deepcopy(data)
        alt["tickers"][0]["bars"] = [{"date": d, "open": o, "high": h, "low": lo, "close": c, "volume": v}
                                     for d, o, h, lo, c, v in reversed(data["tickers"][0]["bars"])]
        alt["index"]["bars"] = list(reversed(data["index"]["bars"]))
        a, b = sepa.run(data)[0], sepa.run(alt)[0]
        self.assertEqual(a["verdicts"], b["verdicts"])
        self.assertEqual(a["fingerprint"], b["fingerprint"])

    def test_extra_history_doesnt_matter(self):
        """Fetching 18 months or 16 months of bars gives the same verdicts and fingerprint."""
        data = make(BASE, synth.LEADER_VOL)
        short = copy.deepcopy(data)
        short["tickers"][0]["bars"] = short["tickers"][0]["bars"][-sepa.KEEP_BARS:]
        short["index"]["bars"] = short["index"]["bars"][-300:]
        a, b = sepa.run(data)[0], sepa.run(short)[0]
        self.assertEqual(a["verdicts"], b["verdicts"])
        self.assertEqual(a["text"], b["text"])
        self.assertEqual(a["fingerprint"], b["fingerprint"])

    def test_intent_changes_only_the_headline(self):
        a = run(BASE, synth.LEADER_VOL, intent="buy")
        b = run(BASE, synth.LEADER_VOL, intent="sell")
        self.assertEqual(a["verdicts"], b["verdicts"])
        self.assertEqual(a["fingerprint"], b["fingerprint"])
        self.assertNotEqual(a["text"]["headline"], b["text"]["headline"])

    def test_live_bar_is_ignored_until_the_session_is_done(self):
        """Asking at 11:00 and 15:30 New York time on the same day gives the same answer."""
        data = make(BASE, synth.LEADER_VOL)
        del data["as_of_close"]
        bars = data["tickers"][0]["bars"]
        last = bars[-1][0]  # 2026-10-02, a Friday
        morning = copy.deepcopy(data)
        morning["tickers"][0]["bars"].append(["2026-10-05", 92.0, 93.0, 91.5, 92.5, 400_000])
        afternoon = copy.deepcopy(data)
        afternoon["tickers"][0]["bars"].append(["2026-10-05", 92.0, 97.0, 91.5, 96.8, 2_900_000])
        t11 = datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc)   # 11:00 EDT
        t1530 = datetime(2026, 10, 5, 19, 30, tzinfo=timezone.utc)  # 15:30 EDT
        a, b = sepa.run(morning, now_utc=t11)[0], sepa.run(afternoon, now_utc=t1530)[0]
        self.assertEqual(a["as_of_close"], last)
        self.assertEqual(a["verdicts"], b["verdicts"])
        self.assertEqual(a["fingerprint"], b["fingerprint"])
        # After 18:00 New York time the day's bar is final and counts.
        t19 = datetime(2026, 10, 5, 23, 0, tzinfo=timezone.utc)
        c = sepa.run(afternoon, now_utc=t19)[0]
        self.assertEqual(c["as_of_close"], "2026-10-05")
        self.assertEqual(c["verdicts"]["buy"]["verdict"], "BUY")

    def test_dst_fallback_matches_zoneinfo(self):
        for ts in (datetime(2026, 3, 8, 6, 59, tzinfo=timezone.utc), datetime(2026, 3, 8, 7, 1, tzinfo=timezone.utc),
                   datetime(2026, 11, 1, 5, 59, tzinfo=timezone.utc), datetime(2026, 11, 1, 6, 1, tzinfo=timezone.utc),
                   datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)):
            self.assertEqual(sepa.new_york_now(ts).utcoffset(), _fallback_offset(ts), ts)


def _fallback_offset(ts):
    import builtins
    real = builtins.__import__

    def no_zoneinfo(name, *a, **k):
        if name == "zoneinfo":
            raise ImportError
        return real(name, *a, **k)

    builtins.__import__ = no_zoneinfo
    try:
        return sepa.new_york_now(ts).utcoffset()
    finally:
        builtins.__import__ = real


class Example(unittest.TestCase):
    def test_example_input_runs(self):
        with open(os.path.join(HERE, "example_input.json")) as f:
            data = json.load(f)
        r = sepa.run(data)[0]
        self.assertIn(r["verdicts"]["buy"]["verdict"], sepa.BUY_VERDICTS)
        self.assertEqual(r["verdicts"]["buy"]["verdict"], "BUY ON BREAKOUT")


if __name__ == "__main__":
    unittest.main()
