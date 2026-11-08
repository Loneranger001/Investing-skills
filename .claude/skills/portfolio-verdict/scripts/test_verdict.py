"""Regression tests for verdict.py. Run: python3 -m unittest -v test_verdict.py (from this dir)."""
import copy
import json
import os
import tempfile
import unittest

import verdict
import backtest_dca as bt
import build_stats
import render_dashboard

HERE = os.path.dirname(os.path.abspath(__file__))


def idx(price, ma50, ma200, high, r3=0, r6=5, r1=10):
    return {"price": price, "ma50": ma50, "ma200": ma200, "year_high": high,
            "returns": {"3M": r3, "6M": r6, "1Y": r1}}


# Both indexes confirmed above a rising 40-wk, near their highs.
OK = {"^GSPC": idx(110, 106, 95, 111, 5, 10, 20), "^IXIC": idx(110, 106, 95, 112, 5, 10, 20)}
# Same trend, S&P 7% off its high: a pullback in an uptrend.
PULLBACK = {"^GSPC": idx(104, 106, 95, 111.8, -3, 6, 15), "^IXIC": idx(108, 109, 95, 115, -2, 8, 18)}
# S&P fine, Nasdaq 24% off its high but still above a 40-wk lifted by a parabolic run (2000).
NDX_BEAR = {"^GSPC": idx(110, 106, 95, 113, 2, 8, 18), "^IXIC": idx(120, 140, 100, 158, -15, 10, 60)}
# Nasdaq below its still-rising 40-wk: a correction.
BELOW40 = {"^GSPC": idx(100, 104, 97, 108, -4, 2, 12), "^IXIC": idx(93, 100, 95, 106, -5, 2, 15)}
# Both below a falling 40-wk.
STAGE4 = {"^GSPC": idx(80, 85, 100, 112, -15, -20, -25), "^IXIC": idx(80, 85, 100, 115, -15, -20, -25)}
# Back above a 40-wk that is still falling.
REPAIR = {"^GSPC": idx(100, 96, 97, 125, 8, 5, -15), "^IXIC": idx(100, 96, 97, 130, 8, 5, -15)}

ETF = {"type": "etf", "etf_class": "equity", "sleeve": "core",
       "price": 100, "year_high": 102, "ma50": 97, "ma200": 90,
       "returns": {"3M": 5, "6M": 10, "1Y": 20}, "benchmark_returns": {"3M": 5, "6M": 10, "1Y": 20}}

# Clean Stage 2 leader with an Intact thesis (canslim: Buy in a healthy market).
LEADER = {
    "ticker": "LEAD", "type": "stock", "sleeve": "satellite",
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


def etf(tk, **kw):
    e = copy.deepcopy(ETF)
    e["ticker"] = tk
    e.update(kw)
    return e


def stock(**kw):
    s = copy.deepcopy(LEADER)
    s.update(kw)
    return s


def run(holdings, market=OK, mode="full", **portfolio):
    return verdict.run({"as_of": "2026-11-07", "mode": mode, "market": market,
                        "portfolio": portfolio, "holdings": holdings})


def row(out, tk):
    return next(r for r in out["core"] + out["satellite"] if r["ticker"] == tk)


class Market(unittest.TestCase):
    def mv(self, m):
        return verdict.market_verdict(m)

    def test_ok_is_buy(self):
        v = self.mv(OK)
        self.assertEqual((v["verdict"], v["contrib"], v["deploy"]), ("Buy", 1.0, 1.0))

    def test_pullback_in_uptrend_is_buy_more(self):
        v = self.mv(PULLBACK)
        self.assertEqual((v["verdict"], v["kind"], v["deploy"]), ("Buy More", "pullback", 1.0))

    def test_pullback_needs_5pct(self):
        m = copy.deepcopy(PULLBACK)
        m["^GSPC"]["year_high"] = 104 / 0.951  # 4.9% off
        self.assertEqual(self.mv(m)["verdict"], "Buy")

    def test_index_in_bear_while_above_40wk_is_caution(self):
        v = self.mv(NDX_BEAR)
        self.assertEqual(v["regime"], "ok")
        self.assertEqual(v["verdict"], "Exercise Caution")
        self.assertIn("Nasdaq", v["why"])

    def test_below40_is_caution_half(self):
        v = self.mv(BELOW40)
        self.assertEqual((v["verdict"], v["contrib"], v["deploy"]), ("Exercise Caution", 0.5, 0.0))

    def test_stage4_is_pause(self):
        v = self.mv(STAGE4)
        self.assertEqual((v["verdict"], v["contrib"], v["deploy"]), ("Pause", 0.0, 0.0))

    def test_repair_is_buy_more_half_reserve(self):
        v = self.mv(REPAIR)
        self.assertEqual((v["verdict"], v["kind"], v["contrib"], v["deploy"]), ("Buy More", "repair", 1.0, 0.5))

    def test_one_index_is_not_enough(self):
        with self.assertRaises(ValueError):
            self.mv({"^GSPC": OK["^GSPC"]})

    def test_missing_year_high_flags_and_still_scores(self):
        m = copy.deepcopy(OK)
        del m["^IXIC"]["year_high"]
        v = self.mv(m)
        self.assertEqual(v["verdict"], "Buy")
        self.assertTrue(v["flags"])


class History(unittest.TestCase):
    """Pinned weeks and backtest results on 2000-2023 weekly closes (fixtures/weekly_1999_2023.csv)."""

    @classmethod
    def setUpClass(cls):
        cls.dates, cls.spx, cls.ndx = bt.load()
        cls.weeks = bt.verdicts(cls.dates, cls.spx, cls.ndx)
        cls.by_date = {d: bt.label(mv) for _, d, mv in cls.weeks}

    def test_key_weeks(self):
        expect = {
            "2000-03-24": "Buy",                  # S&P's top week: the gate doesn't call tops
            "2000-04-20": "Exercise Caution",     # Nasdaq -28% while still above its 40-wk
            "2000-12-01": "Pause",
            "2002-10-11": "Pause",                # the low
            "2003-04-25": "Buy More (repair)",
            "2007-11-09": "Exercise Caution",
            "2008-10-10": "Pause",
            "2009-03-06": "Pause",                # the low
            "2009-06-05": "Buy More (repair)",
            "2010-02-05": "Buy More",             # pullback in an uptrend
            "2020-03-20": "Exercise Caution",     # crash below a still-rising 40-wk: half, not zero
            "2020-04-17": "Pause",
            "2020-06-05": "Buy More (repair)",
            "2020-09-25": "Buy More",
            "2022-06-17": "Pause",
            "2023-02-03": "Buy More (repair)",
        }
        for d, v in expect.items():
            self.assertEqual(self.by_date[d], v, d)

    def test_never_buy_from_final_close_to_the_low_in_long_bears(self):
        for start, low in (("2000-12-01", "2002-10-11"), ("2008-01-04", "2009-03-06"), ("2022-01-07", "2022-10-14")):
            vs = {v for d, v in self.by_date.items() if start <= d <= low}
            self.assertFalse(vs & {"Buy", "Buy More"}, (start, low, vs))

    def test_plan_vs_plain_dca(self):
        res = {name: bt.simulate(self.weeks, self.spx, self.ndx, a, b)["diff"] for name, a, b in bt.PERIODS}
        self.assertGreater(res["2000-23 full"], 2.0)
        self.assertGreater(res["2000-03 dot-com bust"], 8.0)
        self.assertGreater(res["2007-10 GFC"], 2.0)
        for name in ("2004-07 bull", "2011-19 bull + corrections", "2020-21 COVID V", "2022-23 bear + recovery"):
            self.assertGreater(res[name], -2.5, name)  # the cost of the insurance stays small


class Core(unittest.TestCase):
    def test_core_follows_market(self):
        for m, v in ((OK, "Buy"), (PULLBACK, "Buy More"), (BELOW40, "Exercise Caution"),
                     (STAGE4, "Pause"), (REPAIR, "Buy More")):
            self.assertEqual(row(run([etf("QQQ")], m), "QQQ")["verdict"], v)

    def test_core_never_sells(self):
        out = run([etf("QQQ", price=70, ma50=80, ma200=100, returns={"3M": -20, "6M": -25, "1Y": -30})], STAGE4)
        self.assertEqual(row(out, "QQQ")["verdict"], "Pause")
        self.assertEqual(out["actions"], [])

    def test_own_stage4_caps_at_pause(self):
        q = etf("ARKX", price=70, ma50=80, ma200=100, returns={"3M": -20, "6M": -25, "1Y": -30})
        r = row(run([q]), "ARKX")
        self.assertEqual(r["verdict"], "Pause")
        self.assertIn("falling 40-wk", r["why"])

    def test_own_below_40wk_caps_at_caution(self):
        q = etf("SPMO", price=95, ma50=98, ma200=97, returns={"3M": -3, "6M": 2, "1Y": 12})
        self.assertEqual(row(run([q]), "SPMO")["verdict"], "Exercise Caution")

    def test_overweight_within_core_pauses(self):
        h = [etf("QQQ", target_pct=40, shares=500), etf("SCHG", target_pct=60, shares=500)]
        out = run(h)
        self.assertEqual(row(out, "QQQ")["verdict"], "Pause")       # 50% of core vs 40% target
        self.assertEqual(row(out, "SCHG")["verdict"], "Buy")

    def test_satellite_underweight_does_not_make_core_overweight(self):
        h = [etf("QQQ", target_pct=50, shares=500), etf("SCHG", target_pct=50, shares=500),
             stock(shares=10)]
        out = run(h)
        self.assertEqual(row(out, "QQQ")["verdict"], "Buy")
        self.assertEqual(row(out, "QQQ")["core_weight_pct"], 50.0)

    def test_targets_rescaled_and_flagged(self):
        out = run([etf("QQQ", target_pct=30, shares=1), etf("SCHG", target_pct=25, shares=1)])
        self.assertEqual(row(out, "QQQ")["target_pct"], 54.5)
        self.assertTrue(any("rescaled" in f for f in out["flags"]))


class Satellite(unittest.TestCase):
    def test_leader_buy_is_buy_more_when_held(self):
        r = row(run([stock()]), "LEAD")
        self.assertEqual(r["canslim"]["new_money"]["action"], "Buy")
        self.assertEqual(r["verdict"], "Buy More")

    def test_leader_not_held_is_buy(self):
        self.assertEqual(row(run([stock(held=False)]), "LEAD")["verdict"], "Buy")

    def test_quick_mode_caps_at_buy(self):
        r = row(run([stock()], mode="quick"), "LEAD")
        self.assertEqual(r["verdict"], "Buy")
        self.assertIsNone(r["canslim"]["quality"])

    def test_extended_leader_is_caution(self):
        r = row(run([stock(price=125, year_high=126)]), "LEAD")
        self.assertEqual(r["canslim"]["new_money"]["action"], "Buy on pullback")
        self.assertEqual(r["verdict"], "Exercise Caution")

    def test_repair_starter_is_buy(self):
        r = row(run([stock()], REPAIR), "LEAD")
        self.assertEqual(r["canslim"]["new_money"]["action"], "Buy (starter)")
        self.assertEqual(r["verdict"], "Buy")

    def test_broken_thesis_is_sell(self):
        r = row(run([stock(thesis={"core": "auto", "capital": "pass", "balance": "auto", "moat": "fail"})]), "LEAD")
        self.assertEqual((r["verdict"], r["do"]), ("Sell", "Exit"))

    def test_broken_thesis_not_held_is_avoid(self):
        s = stock(held=False, thesis={"core": "auto", "capital": "pass", "balance": "auto", "moat": "fail"})
        self.assertEqual(row(run([s]), "LEAD")["verdict"], "Avoid")

    def test_stage4_is_sell_reduce(self):
        s = stock(price=70, ma50=78, ma200=85, returns={"3M": -20, "6M": -25, "1Y": -10})
        r = row(run([s]), "LEAD")
        self.assertEqual((r["verdict"], r["do"]), ("Sell", "Reduce by half"))

    def test_at_risk_is_pause(self):
        s = stock(thesis={"core": "auto", "capital": "pass", "balance": "auto", "moat": "watch"})
        r = row(run([s]), "LEAD")
        self.assertEqual(r["canslim"]["holder"]["action"], "Hold, re-check")
        self.assertEqual(r["verdict"], "Pause")

    def test_market_pause_caps_satellite(self):
        r = row(run([stock()], STAGE4), "LEAD")
        self.assertEqual(r["verdict"], "Pause")

    def test_position_cap_and_trim(self):
        core = etf("QQQ", target_pct=100, shares=100)              # $10,000
        r = row(run([core, stock(shares=6)], max_position_pct=5, trim_position_pct=8), "LEAD")  # 5.7%
        self.assertEqual(r["verdict"], "Exercise Caution")
        out = run([core, stock(shares=12)], max_position_pct=5, trim_position_pct=8)          # 10.7%
        r = row(out, "LEAD")
        self.assertEqual(r["verdict"], "Sell")
        self.assertTrue(r["do"].startswith("Trim to 5%"))
        self.assertEqual(len(out["actions"]), 1)

    def test_sleeve_over_target_stops_adds(self):
        h = [etf("QQQ", target_pct=100, shares=10), stock(shares=4)]  # satellite 28.6% vs 20 + 5
        r = row(run(h, max_position_pct=50, trim_position_pct=60), "LEAD")
        self.assertEqual(r["verdict"], "Exercise Caution")
        self.assertIn("satellite sleeve", r["why"])


class Plan(unittest.TestCase):
    H = [etf("QQQ", target_pct=40, shares=40), etf("SCHG", target_pct=60, shares=60), stock(shares=1)]

    def test_no_amount_no_plan(self):
        self.assertIsNone(run(self.H)["plan"])

    def test_buy_splits_everything(self):
        p = run(self.H, contribution=1000, cash_reserve=500)["plan"]
        self.assertEqual(p["invest"], 1500)
        self.assertEqual(sum(p["split"].values()), 1500)
        self.assertEqual(p["reserve_after"], 0)
        self.assertIn("LEAD", p["split"])

    def test_caution_halves(self):
        p = run(self.H, BELOW40, contribution=1000, cash_reserve=500)["plan"]
        self.assertEqual((p["invest"], p["to_reserve"], p["reserve_after"]), (500, 500, 1000))
        self.assertNotIn("LEAD", p["split"])  # no adds to satellites under Caution

    def test_pause_invests_nothing(self):
        p = run(self.H, STAGE4, contribution=1000, cash_reserve=500)["plan"]
        self.assertEqual((p["invest"], p["to_reserve"], p["reserve_after"], p["split"]), (0, 1000, 1500, {}))

    def test_repair_deploys_half_the_reserve(self):
        p = run(self.H, REPAIR, contribution=1000, cash_reserve=600)["plan"]
        self.assertEqual((p["from_reserve"], p["invest"], p["reserve_after"]), (300, 1300, 300))

    def test_new_money_goes_to_the_underweight_fund(self):
        h = [etf("QQQ", target_pct=50, shares=30), etf("SCHG", target_pct=50, shares=70)]
        p = run(h, contribution=1000)["plan"]
        self.assertEqual(p["split"], {"QQQ": 1000})

    def test_satellite_add_respects_position_cap(self):
        h = [etf("QQQ", target_pct=100, shares=100), stock(shares=4)]  # LEAD $400 of $10,400
        p = run(h, contribution=10000, max_position_pct=5)["plan"]
        self.assertLessEqual(p["split"]["LEAD"], round(0.05 * 20400 - 400) + 1)
        self.assertEqual(sum(p["split"].values()), 10000)


class Helpers(unittest.TestCase):
    def test_round_split_is_exact(self):
        out = verdict.round_split(1000, {"a": 1, "b": 1, "c": 1})
        self.assertEqual(sum(out.values()), 1000)
        self.assertEqual(sorted(out.values()), [333, 333, 334])

    def test_ranks(self):
        self.assertEqual(verdict.VERDICTS, ["Sell", "Pause", "Exercise Caution", "Buy", "Buy More"])
        self.assertEqual(verdict.RANK["Avoid"], verdict.RANK["Sell"])


class Golden(unittest.TestCase):
    def test_example_input(self):
        with open(os.path.join(HERE, "example_input.json")) as f:
            out = verdict.run(json.load(f))
        self.assertEqual(out["verdict"]["label"], "Exercise Caution")
        self.assertEqual({r["ticker"]: r["verdict"] for r in out["core"] + out["satellite"]},
                         {"QQQ": "Exercise Caution", "SCHG": "Exercise Caution",
                          "SPMO": "Exercise Caution", "NVDA": "Pause"})
        self.assertEqual(out["plan"]["split"], {"QQQ": 1000})
        self.assertEqual((out["plan"]["to_reserve"], out["plan"]["reserve_after"]), (1000, 4000))
        self.assertEqual(out["flags"], [])


class Entry(unittest.TestCase):
    def state(self, price, ma10, ma40, high, r6=5, r1=15):
        return verdict.entry_state(price, ma10, ma40, high, {"6M": r6, "1Y": r1})["bucket"]

    def test_buckets(self):
        self.assertEqual(self.state(100, 98, 90, 102), "up_lt5")
        self.assertEqual(self.state(100, 103, 90, 107), "up_5_10")
        self.assertEqual(self.state(100, 110, 90, 125), "up_ge10")
        self.assertEqual(self.state(100, 96, 97, 125, r6=5, r1=-15), "repair")
        self.assertEqual(self.state(93, 100, 95, 106), "test_10_20")
        self.assertEqual(self.state(80, 85, 100, 112, r6=-20, r1=-25), "down_ge20")

    def test_missing_high_is_none(self):
        self.assertIsNone(verdict.entry_state(100, 98, 90, None, {"6M": 5, "1Y": 15}))

    def test_buy_levels(self):
        lv = verdict.buy_levels(110, 105, 90, 112)
        self.assertEqual((lv["zone_low"], lv["zone_high"]), (100.8, 106.4))  # max(112*0.9, 90*1.02), 112*0.95
        self.assertAlmostEqual(lv["to_zone_pct"], -3.3, places=1)
        self.assertIsNone(verdict.buy_levels(110, 108, 106, 112)["zone_low"])  # 40-wk confirm above the zone

    def test_fund_in_its_buy_zone_is_buy_more_when_market_says_buy(self):
        q = etf("SPMO", price=100, ma50=103, ma200=90, year_high=107)
        r = row(run([q]), "SPMO")
        self.assertEqual(r["entry"]["bucket"], "up_5_10")
        self.assertEqual(r["verdict"], "Buy More")
        self.assertIn("buy zone", r["why"])
        self.assertTrue(r["zone"].startswith("In the zone now"))

    def test_buy_zone_does_not_override_a_cautious_market(self):
        q = etf("SPMO", price=100, ma50=103, ma200=90, year_high=107)
        self.assertEqual(row(run([q], BELOW40), "SPMO")["verdict"], "Exercise Caution")

    def test_plan_tilts_toward_the_buy_zone_fund(self):
        h = [etf("SPMO", target_pct=50, price=100, ma50=103, ma200=90, year_high=107),
             etf("QQQ", target_pct=50)]
        p = run(h, contribution=900)["plan"]
        self.assertEqual(p["split"], {"SPMO": 600, "QQQ": 300})

    def test_core_rows_carry_history(self):
        r = row(run([etf("QQQ")]), "QQQ")
        self.assertEqual(r["stats"]["episodes"], build_stats.build()["entry"]["up_lt5"]["episodes"])
        self.assertIn("fwd_26w", r["stats"])


class Health(unittest.TestCase):
    FULL = {"^RUT": idx(110, 106, 95, 112, 5, 10, 20), "pct_above_200d": 70, "rsp_spy_3m_pp": 0.5,
            "vix": 14, "vix3m": 16, "hy_oas": 3.0, "hy_oas_3m_ago": 3.1, "us10y": 4.5, "us3m": 3.6,
            "fwd_pe": 17, "fwd_pe_10y_avg": 18, "cape": 28, "fear_greed": 50, "aaii_bull_bear": 5,
            "sectors_3m": {"XLK": 6, "XLY": 5, "XLC": 4, "XLF": 3, "XLI": 3, "XLP": 1, "XLU": 0, "XLV": 1, "XLRE": 0}}

    def health(self, h, market=OK):
        return verdict.run({"as_of": "2026-11-07", "market": market, "health": h, "holdings": []})

    def test_trend_only_when_nothing_else(self):
        out = self.health({})
        self.assertEqual(out["health"]["coverage"], "1/5")
        self.assertEqual(out["health"]["score"], 92)
        self.assertTrue(any("health: no data" in f for f in out["flags"]))

    def test_strong_market_is_healthy(self):
        hl = self.health(self.FULL)["health"]
        self.assertEqual((hl["coverage"], hl["label"]), ("5/5", "Healthy"))
        ctx = {c["key"]: c["status"] for c in hl["context"]}
        self.assertEqual(ctx, {"valuation": "fair", "sentiment": "neutral", "leadership": "risk-on"})

    def test_stressed_market(self):
        h = {"pct_above_200d": 18, "rsp_spy_3m_pp": -9, "vix": 42, "vix3m": 35, "hy_oas": 7.5,
             "hy_oas_3m_ago": 4.5, "us10y": 3.5, "us3m": 4.8}
        hl = self.health(h, STAGE4)["health"]
        self.assertEqual(hl["label"], "Stressed")
        cats = {c["key"]: c["score"] for c in hl["categories"]}
        self.assertEqual((cats["volatility"], cats["credit"], cats["participation"]), (0, 0, 0))
        self.assertEqual(hl["internals_score"], 2)  # only the inverted curve (10) scores above 0

    def test_inverted_vix_curve_caps_volatility(self):
        cats = {c["key"]: c for c in self.health({"vix": 16, "vix3m": 15})["health"]["categories"]}
        self.assertEqual(cats["volatility"]["score"], 20)
        calm = {c["key"]: c for c in self.health({"vix": 16, "vix3m": 18})["health"]["categories"]}
        self.assertEqual(calm["volatility"]["score"], 85)  # term structure shown, not averaged in

    def test_credit_widening_penalty(self):
        calm = self.health({"hy_oas": 3.5, "hy_oas_3m_ago": 3.4})["health"]["categories"][3]["score"]
        wide = self.health({"hy_oas": 3.5, "hy_oas_3m_ago": 2.5})["health"]["categories"][3]["score"]
        self.assertEqual(calm - wide, 30)

    def test_extra_index_is_health_not_gate(self):
        m = dict(OK, **{"^RUT": idx(80, 85, 100, 112, -15, -20, -25)})  # small caps in Stage 4
        out = verdict.run({"as_of": "2026-11-07", "market": m, "holdings": []})
        self.assertEqual(out["verdict"]["label"], "Buy")
        part = out["health"]["categories"][1]
        self.assertEqual(part["items"][0]["key"], "^RUT")
        self.assertEqual(part["status"], "weak")

    def test_divergence_notes(self):
        weak = {"pct_above_200d": 18, "vix": 42, "hy_oas": 7.5, "us10y": 3.5, "us3m": 4.8}
        self.assertIn("skip spare cash", self.health(weak)["verdict"]["divergence"])
        self.assertIn("quick reclaim", self.health(self.FULL, STAGE4)["verdict"]["divergence"])
        self.assertIsNone(self.health(self.FULL)["verdict"]["divergence"])


class Output(unittest.TestCase):
    def test_schema(self):
        out = run([etf("QQQ"), stock()], contribution=1000)
        self.assertEqual(out["schema_version"], 2)
        for k in ("as_of", "mode", "verdict", "market", "health", "core", "satellite", "plan", "actions",
                  "flags", "text"):
            self.assertIn(k, out)
        self.assertEqual(set(out["market"]["indexes"]), {"^GSPC", "^IXIC"})
        self.assertIn("stats", out["verdict"])
        for k in ("headline", "market_line", "health_table_md", "tables_md", "plan_line"):
            self.assertIn(k, out["text"])
        json.dumps(out)  # serializable

    def test_out_dir_upserts_history(self):
        with tempfile.TemporaryDirectory() as d:
            for as_of, m in (("2026-11-01", OK), ("2026-11-08", STAGE4), ("2026-11-08", BELOW40)):
                out = verdict.run({"as_of": as_of, "market": m, "holdings": [etf("QQQ")]})
                verdict.write_out(out, d)
            with open(os.path.join(d, "history.jsonl")) as f:
                hist = [json.loads(x) for x in f]
            self.assertEqual([(h["as_of"], h["verdict"]) for h in hist],
                             [("2026-11-01", "Buy"), ("2026-11-08", "Exercise Caution")])
            with open(os.path.join(d, "latest.json")) as f:
                self.assertEqual(json.load(f)["verdict"]["label"], "Exercise Caution")


class Stats(unittest.TestCase):
    def test_committed_stats_are_current(self):
        with open(verdict.STATS_PATH) as f:
            committed = json.load(f)
        self.assertEqual(committed, build_stats.build(), "re-run build_stats.py")

    def test_every_bucket_has_history(self):
        stats = verdict.load_stats()
        self.assertEqual(set(stats["entry"]), set(verdict.ENTRY_LABELS))
        for k, r in stats["entry"].items():
            self.assertGreaterEqual(r["episodes"], 8, k)


class Dashboard(unittest.TestCase):
    def page(self, out, hist=None):
        out = dict(out, _verdict_stats=verdict.load_stats()["verdict"])
        return render_dashboard.render(out, hist or [])

    def test_full_page(self):
        with open(os.path.join(HERE, "example_input.json")) as f:
            out = verdict.run(json.load(f))
        hist = [verdict.history_record(out)]
        page = self.page(out, hist)
        for section in ("Market health", "Indexes", "Core funds", "Satellite", "This period", "History",
                        "What followed each verdict"):
            self.assertIn(section, page)
        self.assertIn("In the zone now", page)       # SPMO's buy zone
        self.assertEqual(page.count('class="lad"'), 5)  # 2 indexes + 3 funds

    def test_minimal_page(self):
        page = self.page(verdict.run({"as_of": "2026-11-07", "market": OK, "holdings": [etf("QQQ")]}))
        self.assertIn("History builds up", page)
        self.assertIn("Add a contribution", page)
        self.assertNotIn("<h2>Satellite</h2>", page)

    def test_text_is_escaped(self):
        page = self.page(verdict.run({"as_of": "2026-11-07", "market": OK,
                                      "holdings": [etf("<img src=x onerror=alert(1)>")]}))
        self.assertNotIn("<img src=x", page)
        self.assertIn("&lt;img src=x", page)


if __name__ == "__main__":
    unittest.main()
