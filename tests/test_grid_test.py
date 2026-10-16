"""CLO-21 sideways grid test: screen, config rule (step >= 3x round-trip cost), bootstrap, drawdown, book chaining."""
import math
import unittest

from pionex_lab.swing import grid, grid_test as gt

DAY = gt.DAY


def flat_days(n, price=100.0, rng=1.0):
    return {i * DAY: [price, price + rng / 2, price - rng / 2, price, 24] for i in range(n)}


class GridTestTests(unittest.TestCase):
    def test_screen_needs_history_and_uses_only_prior_days(self):
        d = flat_days(40)
        self.assertIsNone(gt.screen(d, 10 * DAY))
        s = gt.screen(d, 30 * DAY)
        self.assertAlmostEqual(s["atr"], 1.0)
        self.assertAlmostEqual(s["bw"], 0.0)
        d[30 * DAY] = [100, 500, 1, 400, 24]                         # the decision day itself must not matter
        self.assertEqual(gt.screen(d, 30 * DAY), s)
        self.assertTrue(gt.passes(s))

    def test_wide_market_is_screened_out(self):
        d = flat_days(40, rng=12.0)                                   # ATR 12% of price
        self.assertFalse(gt.passes(gt.screen(d, 30 * DAY)))

    def test_config_step_at_least_three_round_trip_costs(self):
        s = {"atr": 2.0, "upper": 110.0, "lower": 90.0}
        cfg = gt.config(s)
        self.assertGreaterEqual(cfg["step_pct"], gt.STEP_MULT * gt.RT - 1e-12)
        self.assertLessEqual(cfg["rows"], 100)
        self.assertEqual((round(cfg["top"], 6), round(cfg["bottom"], 6)), (111.0, 89.0))
        self.assertAlmostEqual(cfg["stop_price"], 87.0)

    def test_config_too_narrow_gives_none(self):
        self.assertIsNone(gt.config({"atr": 0.0, "upper": 100.2, "lower": 100.0}))
        self.assertIsNone(gt.config({"atr": 50.0, "upper": 10.0, "lower": 5.0}))      # bottom <= 0

    def test_max_drawdown(self):
        self.assertAlmostEqual(gt.max_drawdown([1.0, 1.2, 0.9, 1.3, 1.0]), 0.25)

    def test_cluster_bootstrap_lower_sign(self):
        up = {i: [0.01, 0.02] for i in range(30)}
        lb, med = gt.cluster_bootstrap_lower(up, n=500)
        self.assertGreater(lb, 0)
        mixed = {i: [0.05 if i % 2 else -0.05] for i in range(30)}
        lb2, _ = gt.cluster_bootstrap_lower(mixed, n=500)
        self.assertLess(lb2, 0)

    def test_book_curves_idle_slot_is_cash(self):
        hold = {(0, "A"): [1.0 + 0.01 * k for k in range(14)], (0, "B"): [1.0] * 14}
        win = {(0, "A"): [1.0] * 13 + [1.05]}
        gc, hc = gt.book_curves([0], {0: ["A", "B"]}, win, hold)
        self.assertEqual(len(gc), 14)
        self.assertAlmostEqual(gc[-1], (1.05 + 1.0) / 2)
        self.assertAlmostEqual(hc[-1], (1.13 + 1.0) / 2)

    def test_run_window_pads_marks_after_stop(self):
        bars = [(i * gt.HOUR, 100.0, 100.5, 99.5, 100.0) for i in range(5)] + \
               [(5 * gt.HOUR, 100.0, 100.0, 50.0, 55.0)] + [(6 * gt.HOUR, 55.0, 56.0, 54.0, 55.0)]
        cfg = {"top": 105.0, "bottom": 95.0, "rows": 20, "grid_type": "geometric", "stop_price": 90.0}
        r = gt.run_window(bars, cfg)
        self.assertEqual(r["exit"], "stop_loss")
        self.assertEqual(len(r["marks"]), gt.SLOT_DAYS)
        self.assertAlmostEqual(r["marks"][-1], r["final_equity"] / gt.INVEST)


if __name__ == "__main__":
    unittest.main()
