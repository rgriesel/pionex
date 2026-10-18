import unittest

from pionex_lab.research import perp_grid_test as t


def bars(prices):
    return [(i * 3_600_000, p, p * 1.001, p * 0.999, p) for i, p in enumerate(prices)]


class PerpGrid(unittest.TestCase):
    def test_flat_market_costs_only(self):
        r = t.run_window(bars([100.0] * t.WINDOW_BARS), 3)
        self.assertFalse(r["liq"])
        self.assertLess(r["ret"], 0.02)

    def test_crash_stops_out(self):
        r = t.run_window(bars([100.0 - 0.1 * i for i in range(t.WINDOW_BARS)]), 3)
        self.assertTrue(r["stop"])
        self.assertLess(r["ret"], 0)

    def test_path_drawdown(self):
        p = t.path([{"ret": 0.1, "trough": 1.0}, {"ret": -0.2, "trough": 0.7}])
        self.assertAlmostEqual(p["max_dd"], 0.3, places=6)


if __name__ == "__main__":
    unittest.main()
