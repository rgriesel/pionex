"""C1 Donchian ensemble: channel state machine, default-off hooks leave v1.1 unchanged, no look-ahead."""
import random
import unittest

from pionex_lab.swing import cta, donchian
from tests.test_overlays import make_data


class ChannelTests(unittest.TestCase):
    def test_enters_on_new_high_and_exits_at_ratcheted_midline(self):
        closes = [10, 10, 10, 11, 12, 13, 12.5, 12.0, 11.0, 9.0]
        st = donchian.channel_states(closes, 3)
        self.assertEqual(st[:2], [None, None])
        self.assertEqual(st[2], 1)                      # 10 == max of [10,10,10]: a (tied) new high
        # stop = mid at entry, then ratchets with Mid; once a close is <= stop the position ends
        self.assertEqual(st[5], 1)
        self.assertEqual(st[-1], 0)

    def test_stop_never_falls(self):
        closes = [1, 2, 3, 4, 5, 6, 5.9, 5.8, 5.95, 6.5]
        st = donchian.channel_states(closes, 3)
        self.assertEqual(st[-1], 1)

    def test_share_long_counts_only_eligible_channels(self):
        closes = [float(i) for i in range(1, 30)]       # monotone up
        sh = donchian.share_long(closes, (5, 10, 20, 360))
        self.assertEqual(sh[3], 0.0)                    # nothing eligible yet
        self.assertEqual(sh[-1], 1.0)                   # 360 not eligible, the other three long

    def test_no_lookahead(self):
        rng = random.Random(3)
        closes = [100 * (1 + rng.gauss(0, 0.02)) for _ in range(200)]
        full = donchian.share_long(closes)
        part = donchian.share_long(closes[:120])
        self.assertEqual(full[:120], part)


class HookTests(unittest.TestCase):
    def test_default_simulate_unchanged_and_trace_is_passive(self):
        data = make_data()
        a = cta.simulate(data, "tsmom_vote", "vol", coins=tuple(data))
        tr = []
        b = cta.simulate(data, "tsmom_vote", "vol", coins=tuple(data), trace=tr)
        self.assertEqual(a, b)
        self.assertTrue(tr)

    def test_donchian_rule_bounded_and_runs(self):
        data = donchian.add_dc(make_data())
        out = cta.simulate(data, "donchian", "vol", coins=tuple(data))
        self.assertTrue(out)
        self.assertTrue(all(0 <= x[2] <= 1 + 1e-9 for x in out))

    def test_coin_shares_sum_to_one(self):
        sh = donchian.coin_shares([(0, {"A": 0.01, "B": 0.03}), (1, {"A": 0.02})])
        self.assertAlmostEqual(sum(sh.values()), 1.0)
        self.assertAlmostEqual(sh["A"], 0.5)


if __name__ == "__main__":
    unittest.main()
