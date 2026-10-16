"""CLO-21 grid simulator: levels, fills, profit split identity, stop-loss, close on exit."""
import unittest

from pionex_lab.swing import grid


def bar(t, o, h, l, c):
    return (t, o, h, l, c)


class GridTests(unittest.TestCase):
    def test_levels(self):
        a = grid.levels(100, 200, 4, "arithmetic")
        self.assertEqual([round(x, 6) for x in a], [100, 125, 150, 175, 200])
        g = grid.levels(100, 400, 2, "geometric")
        self.assertEqual([round(x, 6) for x in g], [100, 200, 400])
        self.assertAlmostEqual(grid.step_pct(100, 400, 2, "geometric"), 1.0)
        with self.assertRaises(ValueError):
            grid.levels(100, 100, 4)

    def test_one_round_trip_no_costs(self):
        # levels 100,110,120,130,140 ; start at 120 -> 2 cells hold base (120-130,130-140), 2 hold quote
        bars = [bar(0, 120, 120, 110, 110), bar(1, 110, 120, 110, 120), bar(2, 120, 120, 120, 120)]
        r = grid.simulate(bars, 100, 140, 4, 1000.0, "arithmetic", fee=0, mark_every=1)
        # the 110->120 cell bought at 110 and sold at 120: one pair worth q*10; q = 1000/(2*120+100+110)
        q = 1000.0 / (2 * 120 + 100 + 110)
        self.assertEqual(r["round_trips"], 1)
        self.assertAlmostEqual(r["grid_profit"], q * 10, places=9)
        self.assertAlmostEqual(r["grid_profit"] + r["float_profit"], r["total_profit"], places=9)
        # price ends where it started and the initial inventory was bought at 120 -> total == grid profit
        self.assertAlmostEqual(r["total_profit"], q * 10, places=9)
        self.assertEqual(r["exit"], "window_end")

    def test_costs_reduce_profit_and_identity_holds(self):
        bars = [bar(0, 120, 125, 105, 110), bar(1, 110, 125, 108, 124), bar(2, 124, 124, 118, 120)]
        free = grid.simulate(bars, 100, 140, 8, 1000.0, "arithmetic", fee=0)
        paid = grid.simulate(bars, 100, 140, 8, 1000.0, "arithmetic", fee=0.0005, slip=0.0002, slip_market=0.0005)
        self.assertLess(paid["total_profit"], free["total_profit"])
        self.assertLess(paid["grid_profit"], free["grid_profit"])
        for r in (free, paid):
            self.assertAlmostEqual(r["grid_profit"] + r["float_profit"], r["total_profit"], places=9)

    def test_stop_loss_exits_and_sells_inventory(self):
        bars = [bar(0, 120, 121, 120, 121), bar(1, 121, 121, 80, 85), bar(2, 85, 90, 85, 90)]
        r = grid.simulate(bars, 100, 140, 4, 1000.0, "arithmetic", fee=0, stop_price=95)
        self.assertEqual(r["exit"], "stop_loss")
        self.assertTrue(r["closed"])
        self.assertLess(r["return"], 0)
        self.assertAlmostEqual(r["grid_profit"] + r["float_profit"], r["total_profit"], places=9)
        # loss is bounded by the stop: nothing is sold below 95
        self.assertGreater(r["final_equity"], 1000.0 * 0.5)

    def test_breakout_up_sells_everything(self):
        bars = [bar(0, 120, 150, 120, 150)]
        r = grid.simulate(bars, 100, 140, 4, 1000.0, "arithmetic", fee=0, close_on_exit=False)
        # all base sold at the levels above the start, only quote left
        self.assertAlmostEqual(r["return"], r["grid_profit"] / 1000.0 + r["float_profit"] / 1000.0)
        self.assertGreater(r["return"], 0)

    def test_breakdown_leaves_inventory_marked(self):
        bars = [bar(0, 120, 120, 70, 75)]
        held = grid.simulate(bars, 100, 140, 4, 1000.0, "arithmetic", fee=0, close_on_exit=False)
        self.assertLess(held["return"], -0.2)
        self.assertGreater(held["float_profit"] - 0, held["total_profit"] - held["grid_profit"] - 1e-9)

    def test_take_profit_ratio(self):
        bars = [bar(i, 120, 125, 110, 120) for i in range(20)]
        r = grid.simulate(bars, 100, 140, 8, 1000.0, "arithmetic", fee=0, take_profit_ratio=0.001)
        self.assertEqual(r["exit"], "take_profit")


if __name__ == "__main__":
    unittest.main()
