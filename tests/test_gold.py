"""C3 gold sleeve: helpers behave, the 11-coin run and the control cover identical days (synthetic data only)."""
import unittest

from pionex_lab.swing import cta, gold
from pionex_lab.swing.cta import DAY
from tests.test_overlays import make_data


class GoldTests(unittest.TestCase):
    def setUp(self):
        self.data = make_data(days=420, coins=("A", "B", "C", "G"))
        self.coins = ("A", "B", "C")

    def test_load_default_symbols_unchanged(self):
        import inspect
        self.assertEqual(inspect.signature(cta.load).parameters["symbols"].default, cta.UNIVERSE)

    def test_costs_gold_like_btc_and_multiplier(self):
        self.assertAlmostEqual(gold.costs()[gold.GOLD], cta.COST["BTC_USDT"])
        self.assertAlmostEqual(gold.costs(4.0)["ETH_USDT"], 4 * cta.COST["ETH_USDT"])

    def test_start_day_is_after_120th_bar(self):
        self.assertEqual(gold.start_day(self.data, "G"), sorted(self.data["G"])[120] + DAY)

    def test_trim_cuts_to_common_last_day(self):
        d = {"A": {1 * DAY: {}, 2 * DAY: {}}, "G": {1 * DAY: {}, 2 * DAY: {}, 3 * DAY: {}}}
        out = gold.trim(d)
        self.assertEqual(sorted(out["G"]), [1 * DAY, 2 * DAY])
        self.assertEqual(sorted(out["A"]), [1 * DAY, 2 * DAY])

    def test_corr(self):
        self.assertAlmostEqual(gold.corr([1, 2, 3, 4], [2, 4, 6, 8]), 1.0)
        self.assertAlmostEqual(gold.corr([1, 2, 3, 4], [8, 6, 4, 2]), -1.0)
        self.assertEqual(gold.corr([1, 1, 1], [1, 2, 3]), 0.0)

    def test_sleeve_series_alignment(self):
        trace = [(10 * DAY, {"G": 0.01}), (11 * DAY, {"A": 0.5})]
        self.assertEqual(gold.sleeve_series(trace, [9 * DAY, 10 * DAY, 20 * DAY], "G"), [0.01, 0.0, 0.0])

    def test_same_days_and_per_coin_budget(self):
        start = gold.start_day(self.data, "G")
        tr = []
        basket = cta.simulate(self.data, "tsmom_vote", "vol", start, coins=self.coins + ("G",), target=0.44, trace=tr)
        control = cta.simulate(self.data, "tsmom_vote", "vol", start, coins=self.coins, target=0.40)
        self.assertEqual([x[0] for x in basket], [x[0] for x in control])
        self.assertTrue(basket and basket[0][0] >= start)
        s = gold.sleeve_series(tr, [x[0] for x in basket], "G")
        self.assertEqual(len(s), len(basket))

    def test_in_days_and_decide(self):
        days = [x * DAY for x in range(130, 400)]
        ins = gold.in_days(self.data, days, "G")
        self.assertTrue(set(ins) <= set(days))
        start = gold.start_day(self.data, "G")
        b = cta.simulate(self.data, "tsmom_vote", "vol", start, coins=self.coins + ("G",), target=0.44)
        c = cta.simulate(self.data, "tsmom_vote", "vol", start, coins=self.coins, target=0.40)
        out = gold.decide(b, c, 0.1, 5)
        self.assertEqual(set(out["checks"]), {"sharpe_higher", "max_dd_not_worse_by_more_than_1_point",
                                              "sharpe_higher_in_2_of_3_thirds", "bootstrap_lower_bound_ok",
                                              "sleeve_corr_below_0.4"})
        self.assertFalse(gold.decide(b, c, 0.9, 5)["checks"]["sleeve_corr_below_0.4"])
        self.assertFalse(gold.decide(b, c, 0.9, 5)["all_hold"])


if __name__ == "__main__":
    unittest.main()
