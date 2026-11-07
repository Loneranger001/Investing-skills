"""Regression tests for score.py. Run: python3 -m unittest -v test_score.py (from this dir)."""
import copy
import json
import os
import unittest

import score

HERE = os.path.dirname(os.path.abspath(__file__))

HEALTHY_MARKET = {
    "^GSPC": {"price": 110, "ma50": 105, "ma200": 95, "returns": {"3M": 5, "6M": 10, "1Y": 20}},
    "^IXIC": {"price": 110, "ma50": 105, "ma200": 95, "returns": {"3M": 5, "6M": 10, "1Y": 20}},
}
DOWN_MARKET = {
    "^GSPC": {"price": 80, "ma50": 85, "ma200": 100, "returns": {"3M": -15, "6M": -20, "1Y": -25}},
    "^IXIC": {"price": 80, "ma50": 85, "ma200": 100, "returns": {"3M": -15, "6M": -20, "1Y": -25}},
}

# A clean Stage 2 growth leader with Intact thesis: should be a Buy in a healthy market.
LEADER = {
    "ticker": "LEAD", "type": "stock",
    "price": 100, "year_high": 102, "year_low": 55, "ma50": 95, "ma200": 80,
    "returns": {"3M": 25, "6M": 40, "1Y": 80},
    "quarters": [
        {"eps": 0.70, "eps_ya": 0.50, "rev": 55, "rev_ya": 44, "op_inc": 13.0, "op_inc_ya": 9.5},
        {"eps": 0.62, "eps_ya": 0.46, "rev": 50, "rev_ya": 41, "op_inc": 11.5, "op_inc_ya": 8.8},
        {"eps": 0.55, "eps_ya": 0.42, "rev": 46, "rev_ya": 38, "op_inc": 10.2, "op_inc_ya": 8.1},
    ],
    "last4_eps": [0.70, 0.62, 0.55, 0.50],
    "annual": [
        {"eps": 1.0, "rev": 100, "op_inc": 20, "shares": 100, "ebitda": 25},
        {"eps": 1.3, "rev": 125, "op_inc": 26, "shares": 99, "ebitda": 32},
        {"eps": 1.7, "rev": 155, "op_inc": 33, "shares": 98, "ebitda": 40},
        {"eps": 2.2, "rev": 190, "op_inc": 42, "shares": 97, "ebitda": 50},
    ],
    "roe": 0.25, "roic": 0.20, "net_debt_to_ebitda": 0.5, "fcf_yield": 0.03,
    "newness": "ordinary", "institutional": {"trend": "rising", "pct": 0.7},
    "thesis": {"core": "auto", "capital": "pass", "balance": "auto", "moat": "pass"},
    "web_sourced": ["N", "I"],
}


def run_one(ticker, market=HEALTHY_MARKET, as_of="2026-11-07"):
    return score.run({"as_of": as_of, "market": market, "tickers": [ticker]})[0]


def variant(**changes):
    t = copy.deepcopy(LEADER)
    t.update(changes)
    return t


class Helpers(unittest.TestCase):
    def test_interp_clamps_and_interpolates(self):
        pts = [(0, 0), (10, 100)]
        self.assertEqual(score.interp(-5, pts), 0)
        self.assertEqual(score.interp(15, pts), 100)
        self.assertAlmostEqual(score.interp(2.5, pts), 25)
        self.assertIsNone(score.interp(None, pts))

    def test_growth_off_a_loss_is_undefined(self):
        self.assertIsNone(score.yoy(0.5, -0.2))
        self.assertIsNone(score.cagr(-1, 2, 3))

    def test_to99(self):
        self.assertEqual(score.to99(100), 99)
        self.assertEqual(score.to99(80.5), 80)  # 79.695 -> 80
        self.assertEqual(score.to99(80.0), 79)  # 79.2 -> 79


class Golden(unittest.TestCase):
    """Locks calibration against a real snapshot. If you change breakpoints, update these on purpose."""

    def setUp(self):
        with open(os.path.join(HERE, "example_input.json")) as f:
            self.data = json.load(f)

    def test_nvda_snapshot(self):
        r = score.run(self.data)[0]
        self.assertEqual(r["quality"], 90)
        self.assertEqual(r["timing"], 32)
        self.assertEqual(r["new_money"]["action"], "Watchlist")
        self.assertEqual(r["holder"]["action"], "Hold, re-check")
        self.assertEqual(r["thesis"]["label"], "At Risk")
        self.assertEqual(r["weekly"]["label"], "Stage 2 correction below 40-wk")
        self.assertEqual(r["market"]["weakest"], "^IXIC")
        self.assertIn("Nasdaq below its 40-wk MA", r["new_money"]["note"])
        self.assertNotIn("half size", r["new_money"]["note"])  # not a Buy, so no sizing advice

    def test_deterministic(self):
        self.assertEqual(json.dumps(score.run(self.data)), json.dumps(score.run(self.data)))


class WeeklyStage(unittest.TestCase):
    def test_stage2_uptrend(self):
        st = score.weekly_stage(110, 105, 95, {"6M": 10, "1Y": 20})
        self.assertEqual((st["stage"], st["label"], st["slope_40w"]), (2, "Stage 2 uptrend", "rising"))

    def test_stage4_downtrend(self):
        st = score.weekly_stage(80, 85, 100, {"6M": -20, "1Y": -25})
        self.assertEqual(st["stage"], 4)

    def test_slope_falls_back_to_cross_without_returns(self):
        st = score.weekly_stage(110, 105, 95, {})
        self.assertTrue(st["slope_approx"])
        self.assertEqual(st["slope_40w"], "rising")


class Actions(unittest.TestCase):
    def test_leader_in_healthy_market_is_buy(self):
        r = run_one(LEADER)
        self.assertGreaterEqual(r["quality"], 70)
        self.assertGreaterEqual(r["timing"], 70)
        self.assertEqual(r["thesis"]["label"], "Intact")
        self.assertEqual(r["new_money"]["action"], "Buy")
        self.assertEqual(r["holder"]["action"], "Hold")
        self.assertEqual(r["confidence"], "High")

    def test_earnings_soon_adds_sizing_note_to_buy(self):
        r = run_one(variant(next_earnings="2026-11-12"))
        self.assertEqual(r["new_money"]["action"], "Buy")
        self.assertIn("earnings in 5d, start half size", r["new_money"]["note"])

    def test_extended_leader_is_buy_on_pullback(self):
        r = run_one(variant(price=125, year_high=126, ma50=95))
        self.assertEqual(r["new_money"]["action"], "Buy on pullback")
        self.assertIn("$95.00", r["new_money"]["note"])

    def test_downtrend_market_caps_timing_and_blocks_buys(self):
        r = run_one(LEADER, market=DOWN_MARKET)
        self.assertLessEqual(r["timing"], 49)
        self.assertEqual(r["new_money"]["action"], "Watchlist")
        self.assertIn("Stage 4 downtrend, no new buys", r["new_money"]["note"])
        self.assertEqual(r["holder"]["action"], "Hold")  # market timing never forces a 2-5 yr holder out

    def test_stage4_stock_with_intact_thesis_is_reduce(self):
        r = run_one(variant(price=70, ma50=75, ma200=90, year_high=110,
                            returns={"3M": -20, "6M": -25, "1Y": -30}))
        self.assertEqual(r["weekly"]["stage"], 4)
        self.assertEqual(r["holder"]["action"], "Reduce")
        self.assertEqual(r["new_money"]["action"], "Avoid")

    def test_broken_thesis_exits_regardless_of_score(self):
        r = run_one(variant(thesis={"core": "auto", "capital": "pass", "balance": "auto", "moat": "fail"}))
        self.assertEqual(r["thesis"]["label"], "Broken")
        self.assertEqual(r["new_money"]["action"], "Avoid")
        self.assertEqual(r["holder"]["action"], "Exit")


class Thesis(unittest.TestCase):
    def label(self, **answers):
        t = variant(thesis={"core": "pass", "capital": "pass", "balance": "pass", "moat": "pass", **answers})
        return score.thesis_read(t, t["quarters"], t["annual"])

    def test_rules(self):
        self.assertEqual(self.label()["label"], "Intact")
        self.assertEqual(self.label(core="fail")["label"], "Broken")
        self.assertEqual(self.label(moat="watch")["label"], "At Risk")
        self.assertEqual(self.label(balance="fail")["label"], "At Risk")
        self.assertEqual(self.label(capital="watch")["label"], "Intact")  # one soft watch is tolerated
        self.assertEqual(self.label(capital="watch", balance="watch")["label"], "At Risk")

    def test_two_unknowns_is_low_confidence(self):
        self.assertTrue(self.label(capital=None, moat=None)["low_confidence"])

    def test_core_auto_fails_on_two_shrinking_quarters(self):
        qs = [{"rev": 90, "rev_ya": 100}, {"rev": 92, "rev_ya": 100}]
        self.assertEqual(score.core_auto(qs, LEADER["annual"]), "fail")


class FactorEdgeCases(unittest.TestCase):
    def test_c_turnaround_from_a_loss(self):
        flags = []
        s, _ = score.factor_C([{"eps": 0.3, "eps_ya": -0.1, "rev": 120, "rev_ya": 100}], flags)
        self.assertIsNotNone(s)
        self.assertTrue(any("turnaround" in f for f in flags))

    def test_c_gaap_distortion_switches_to_operating_income(self):
        flags = []
        _, d = score.factor_C([{"eps": 3.0, "eps_ya": 1.0, "rev": 110, "rev_ya": 100,
                                "op_inc": 11, "op_inc_ya": 10}], flags)
        self.assertEqual(d["basis"], "op_inc")

    def test_r_negative_equity_uses_roic(self):
        flags = []
        _, d = score.factor_R({"roe": -2.5, "roic": 0.30}, LEADER["annual"], flags)
        self.assertEqual(d["returns_basis"], "ROIC")

    def test_s_unadjusted_split_is_not_scored_as_dilution(self):
        flags = []
        annual = [{"shares": 100, "ebitda": 1}, {"shares": 1000, "ebitda": 1}]
        s, d = score.factor_S({"net_debt_to_ebitda": 0.5}, annual, flags)
        self.assertIsNone(d["shares_chg_pct_yr"])
        self.assertTrue(any("split" in f for f in flags))
        self.assertIsNotNone(s)  # leverage still scored

    def test_missing_quarterlies_reweights_caps_and_lowers_confidence(self):
        r = run_one(variant(quarters=[]))
        self.assertIsNone(r["factors"]["C"])
        self.assertLessEqual(r["quality"], 69)
        self.assertEqual(r["confidence"], "Low")
        self.assertNotEqual(r["new_money"]["action"], "Buy")

    def test_stretched_valuation_penalises_quality(self):
        cheap = run_one(LEADER)["quality"]
        dear = run_one(variant(last4_eps=[0.2, 0.2, 0.2, 0.2]))  # P/E 125 on ~30% growth
        self.assertLess(dear["quality"], cheap)
        self.assertTrue(any("PEG" in f for f in dear["flags"]))


class ETF(unittest.TestCase):
    def test_bond_etf_drops_rs(self):
        etf = {"ticker": "TLT", "type": "etf", "etf_class": "bond", "price": 90, "ma50": 88,
               "ma200": 85, "year_high": 95, "returns": {"3M": 2, "6M": 4, "1Y": 6}}
        r = run_one(etf)
        self.assertIsNone(r["factors"]["L"])
        self.assertIsNone(r["quality"])
        self.assertIsNone(r["thesis"])

    def test_equity_etf_buy(self):
        etf = {"ticker": "XYZ", "type": "etf", "price": 100, "ma50": 95, "ma200": 80, "year_high": 102,
               "returns": {"3M": 12, "6M": 20, "1Y": 35}}
        self.assertEqual(run_one(etf)["new_money"]["action"], "Buy")


if __name__ == "__main__":
    unittest.main()
