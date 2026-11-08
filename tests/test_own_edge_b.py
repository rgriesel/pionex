import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))
import own_edge_b_clo248 as m  # noqa: E402


def bars(*hl):
    return [(c, h, l, c) for h, l, c in hl]


class RunPathTests(unittest.TestCase):
    def test_stop_before_tp_same_bar_long(self):
        b = bars((100, 100, 100), (112, 90, 100), (100, 100, 100))
        t = m.run_path(b, 0, 0, 1, 100.0, 95.0, 110.0, [], 5, 1)
        self.assertEqual(t["exit_reason"], "stop")
        self.assertLess(t["net_bps"], -160)

    def test_tp_short_and_cost(self):
        b = bars((100, 100, 100), (100, 88, 90), (100, 100, 100))
        t = m.run_path(b, 0, 0, -1, 100.0, 105.0, 90.0, [], 5, 1)
        self.assertEqual(t["exit_reason"], "tp")
        # one third notional, +1000 bps gross on it; costs charged on the filled third only
        self.assertAlmostEqual(t["gross_bps"], 1000 / 3, places=6)
        self.assertLess(t["net_bps"], t["gross_bps"])

    def test_rung_fill_then_time_exit_and_missing_bar(self):
        b = bars((100, 100, 100), (102, 100, 101), (101, 100, 101), (101, 100, 101))
        t = m.run_path(b, 0, 0, 1, 100.0, 90.0, 120.0, [(101.0, 1 / 3)], 1, 1)
        self.assertEqual((t["rungs"], t["exit_reason"]), (2, "time"))
        self.assertIsNone(m.run_path([b[0], None], 0, 0, 1, 100.0, 90.0, 120.0, [], 5, 1))


class LeadStatsTests(unittest.TestCase):
    def test_z_needs_history_and_same_sign(self):
        n = 900
        up = [(100.0 + i * 0.01,) * 4 for i in range(n)]
        lr, z = m.lead_stats([up, up])
        self.assertIsNone(z[100])
        self.assertIsNotNone(lr[800])
        self.assertTrue(all(x is None or x > 0 for x in lr))


if __name__ == "__main__":
    unittest.main()
