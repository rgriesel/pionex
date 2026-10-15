"""C2 point-in-time universe: default-off hooks leave v1.1 unchanged, ranking is point-in-time, exclusions and gap splits."""
import unittest

from pionex_lab.swing import cta, pit
from pionex_lab.swing.cta import DAY
from tests.test_overlays import make_data


class HookTests(unittest.TestCase):
    def setUp(self):
        self.data = make_data(days=400)
        self.coins = tuple(self.data)

    def test_defaults_reproduce_v11(self):
        base = cta.simulate(self.data, "tsmom_vote", "vol", coins=self.coins)
        self.assertEqual(base, cta.simulate(self.data, "tsmom_vote", "vol", universe=None, haircut=0.0, coins=self.coins))
        allc = lambda t: set(self.data)
        self.assertEqual(base, cta.simulate(self.data, "tsmom_vote", "vol", universe=allc, coins=self.coins))

    def test_universe_limits_coins_and_closes_leavers(self):
        tr = []
        only_a = lambda t: {"A"}
        cta.simulate(self.data, "tsmom_vote", "vol", universe=only_a, trace=tr, coins=self.coins)
        self.assertTrue(all(set(m) <= {"A"} for _, m in tr))
        tr2 = []
        switch = lambda t: {"A"} if t < 250 * DAY else {"B"}
        cta.simulate(self.data, "hold", "equal", universe=switch, trace=tr2, coins=self.coins)
        late = [m for t, m in tr2 if t >= 252 * DAY]
        self.assertTrue(late and all(set(m) <= {"B"} for m in late))        # A was closed at the open of day 250

    def test_haircut_hits_a_coin_whose_bars_end_once(self):
        d = {k: dict(v) for k, v in self.data.items()}
        end = 300 * DAY
        d["A"] = {t: r for t, r in d["A"].items() if t <= end}
        plain = dict((x[0], x[1]) for x in cta.simulate(d, "hold", "equal", coins=("A", "B")))
        cut = dict((x[0], x[1]) for x in cta.simulate(d, "hold", "equal", coins=("A", "B"), haircut=0.5))
        hit = sorted(t for t in plain if abs(plain[t] - cut[t]) > 1e-9)
        self.assertEqual(hit[0], end)                                        # interval end..end+1d: booked at the first open with no bar
        self.assertLess(cut[end], plain[end])


class RankingTests(unittest.TestCase):
    def mk(self, days, q, t0=0):
        t = [t0 + i * DAY for i in range(days)]
        return {"t": t, "o": [1.0] * days, "c": [1.0 + 0.001 * i for i in range(days)], "q": [q] * days}

    def test_ranking_is_point_in_time(self):
        s = {"BIG_USDT": self.mk(400, 100.0), "SMALL_USDT": self.mk(400, 10.0)}
        m = pit._ms(1970, 1) + 365 * DAY
        first = pit.rank_universe(s, 1)
        s2 = {k: dict(v, q=list(v["q"])) for k, v in s.items()}
        for i in range(len(s2["SMALL_USDT"]["t"])):                          # future volumes flipped
            if s2["SMALL_USDT"]["t"][i] >= 380 * DAY:
                s2["SMALL_USDT"]["q"][i] = 1e9
        second = pit.rank_universe(s2, 1)
        jan = [k for k in first if k >= 150 * DAY and k < 380 * DAY]
        self.assertTrue(jan)
        for k in jan:
            self.assertEqual(first[k], second[k])
        self.assertEqual(first[jan[0]], ["BIG_USDT"])

    def test_needs_history_and_window_bars(self):
        s = {"NEW_USDT": self.mk(100, 5.0), "OLD_USDT": self.mk(400, 1.0)}
        got = pit.rank_universe(s, 5)
        for k, v in got.items():
            if k < 130 * DAY:
                self.assertNotIn("NEW_USDT", v)

    def test_exclusions(self):
        bases = {"ADA", "BTC", "USDC", "ETH", "AAPLB"}
        self.assertTrue(pit.excluded("USDC", 0, bases))
        self.assertTrue(pit.excluded("ADAUP", 0, bases))
        self.assertTrue(pit.excluded("BTCBEAR", 0, bases))
        self.assertTrue(pit.excluded("PAXG", 0, bases))
        self.assertTrue(pit.excluded("AAPLB", pit.EQUITY_FROM, bases))
        self.assertFalse(pit.excluded("BNB", 0, bases))
        self.assertFalse(pit.excluded("SYRUP", 0, bases))
        self.assertFalse(pit._pegged([1.0, 1.01, 0.99, 1.0, 1.02]) is False)
        self.assertFalse(pit._pegged([1.0, 2.0, 3.0, 4.0]))

    def test_costs_and_align(self):
        cm = pit.cost_map(["BTC_USDT", "LUNA_USDT#2"], 4.0)
        self.assertAlmostEqual(cm["BTC_USDT"], 4 * cta.COST["BTC_USDT"])
        self.assertAlmostEqual(cm["LUNA_USDT#2"], 4 * (cta.SIDE + 5e-4))
        a, b = pit.align([(1, .1), (2, .2), (3, .3)], [(2, .5), (3, .6)])
        self.assertEqual([x[0] for x in a], [2, 3])
        self.assertEqual([x[0] for x in b], [2, 3])


if __name__ == "__main__":
    unittest.main()
