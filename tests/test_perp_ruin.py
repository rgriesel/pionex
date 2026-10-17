"""Perp simulator (funding, liquidation, fees), ruin Monte Carlo and leaderboard - synthetic data only."""
import unittest

from pionex_lab.research import leaderboard, ruin
from pionex_lab.swing import perp

H = perp.HOUR_MS
T0 = 1_700_000_000_000 - 1_700_000_000_000 % (8 * H)      # a settlement hour


def flat(n, p=100.0, hi=None, lo=None):
    return [(T0 + i * H, p, hi or p, lo or p, p) for i in range(n)]


class Perp(unittest.TestCase):
    def test_flat_price_costs_scale_with_leverage_and_maker_is_cheaper(self):
        r = perp.simulate_trade(flat(10), 1, 3, 0, 5, [])
        self.assertAlmostEqual(r["return_on_margin"], -2 * 3 * 5e-4)      # 2 taker fees on 3x notional
        self.assertFalse(r["liquidated"])
        m = perp.simulate_trade(flat(10), 1, 1, 0, 5, [], entry_fee_bps=2, exit_fee_bps=2)
        self.assertAlmostEqual(m["net_bps"], -4.0)

    def test_long_pays_and_short_receives_funding_entry_missed_exit_counted(self):
        bars = flat(30)
        fund = [(T0, 0.001), (T0 + 8 * H, 0.001), (T0 + 16 * H, 0.001)]      # T0 is at entry: missed
        long_ = perp.simulate_trade(bars, 1, 1, 0, 16, fund)                # 8h and 16h (exit) counted
        short = perp.simulate_trade(bars, -1, 1, 0, 16, fund)
        self.assertAlmostEqual(long_["funding_on_margin"], -0.002)
        self.assertAlmostEqual(short["funding_on_margin"], 0.002)
        self.assertAlmostEqual(short["return_on_margin"] - long_["return_on_margin"], 0.004)

    def test_funding_scales_with_notional_and_mark(self):
        bars = [(T0 + i * H, 110.0 if i >= 8 else 100.0, 110.0, 100.0, 110.0 if i >= 8 else 100.0)
                for i in range(20)]
        r = perp.simulate_trade(bars, 1, 2, 0, 12, [(T0 + 8 * H, 0.001)])
        self.assertAlmostEqual(r["funding_on_margin"], -0.001 * (2 / 100.0) * 110.0)

    def test_liquidation_price_formula_and_leverage_ordering(self):
        p5 = perp.liquidation_price(100, 1, 5)
        self.assertAlmostEqual(p5, 100 * (1 - 0.1995) / 0.99)
        self.assertLess(p5, 100)
        self.assertGreater(perp.liquidation_price(100, -1, 5), 100)
        self.assertLess(perp.liquidation_price(100, 1, 1), perp.liquidation_price(100, 1, 3))
        self.assertLess(perp.liquidation_price(100, 1, 3), p5)
        self.assertLess(perp.liquidation_price(100, -1, 5), perp.liquidation_price(100, -1, 3))

    def test_long_liquidated_at_wick_loses_whole_margin(self):
        bars = flat(10)
        bars[3] = (bars[3][0], 100, 100, 80.0, 90)                          # wick 80 < 5x liq 80.86
        r = perp.simulate_trade(bars, 1, 5, 0, 8, [])
        self.assertTrue(r["liquidated"])
        self.assertAlmostEqual(r["return_on_margin"], -1.0)
        self.assertEqual(r["exit_time"], bars[3][0])
        self.assertFalse(perp.simulate_trade(bars, 1, 4, 0, 8, [])["liquidated"])   # 4x liq ~ 76.7
        bars[3] = (bars[3][0], 100, 100, 75.0, 90)
        self.assertTrue(perp.simulate_trade(bars, 1, 4, 0, 8, [])["liquidated"])

    def test_short_liquidated_on_spike_and_margin_frac_scales_equity_loss(self):
        bars = flat(10)
        bars[2] = (bars[2][0], 100, 125.0, 100, 110)
        r = perp.simulate_trade(bars, -1, 5, 0, 8, [], margin_frac=0.4)
        self.assertTrue(r["liquidated"])
        self.assertAlmostEqual(r["net_bps"], -4000.0)                        # 40% of equity was margin

    def test_funding_can_tip_a_position_into_liquidation(self):
        bars = flat(30, lo=84.0, hi=100.0)                                   # 5x long liq ~80.86: fine
        self.assertFalse(perp.simulate_trade(bars, 1, 5, 0, 24, [])["liquidated"])
        heavy = [(T0 + 8 * H, 0.03), (T0 + 16 * H, 0.03)]                   # 3% x 5 x 2 = -30% of margin
        self.assertTrue(perp.simulate_trade(bars, 1, 5, 0, 24, heavy)["liquidated"])

    def test_profit_exit_and_input_validation(self):
        bars = flat(10)
        bars[5:] = [(t, 110.0, 110.0, 110.0, 110.0) for t, *_ in bars[5:]]
        r = perp.simulate_trade(bars, 1, 2, 0, 6, [])
        notional_exit_fee = 2 * 1.1 * 5e-4
        self.assertAlmostEqual(r["return_on_margin"], 2 * 0.10 - 2 * 5e-4 - notional_exit_fee)
        with self.assertRaises(ValueError):
            perp.simulate_trade(bars, 1, 6, 0, 6, [])
        with self.assertRaises(ValueError):
            perp.simulate_trade(bars, 0, 2, 0, 6, [])


class Ruin(unittest.TestCase):
    def test_deterministic_and_seeded(self):
        d = [0.01, -0.02, 0.0, 0.015] * 20
        self.assertEqual(ruin.monte_carlo(d, n=500), ruin.monte_carlo(d, n=500))

    def test_zero_vol_positive_drift_never_ruins_and_floor_applies(self):
        r = ruin.monte_carlo([0.01] * 90, n=300)
        self.assertEqual(r["p_ruin"], 0.0)
        self.assertTrue(r["ruin_floor_applied"])
        self.assertAlmostEqual(r["median_30d_return"], 1.01 ** 30 - 1)
        self.assertAlmostEqual(r["return_per_ruin"], r["median_30d_return"] * 300)

    def test_certain_ruin_and_ruin_checked_on_any_day_not_only_the_end(self):
        self.assertEqual(ruin.monte_carlo([-0.05] * 90, n=300)["p_ruin"], 1.0)   # 0.95^30 = 21%
        d = [-0.6, 1.5] + [0.0] * 98          # -60% then back to 100 - 40%*... recovers part, was ruined
        self.assertGreater(ruin.monte_carlo(d, n=2000, block=2)["p_ruin"], 0.0)

    def test_p_ruin_rises_with_volatility(self):
        calm = [0.01, -0.01] * 50
        wild = [0.05, -0.15, -0.15, 0.05, -0.1] * 20
        self.assertLess(ruin.monte_carlo(calm, n=800)["p_ruin"], ruin.monte_carlo(wild, n=800)["p_ruin"])

    def test_insufficient_when_under_60_days(self):
        self.assertEqual(ruin.monte_carlo([0.01] * 59)["verdict"], "INSUFFICIENT")

    def test_daily_returns_include_idle_days_and_ignore_out_of_window(self):
        D = ruin.DAY_MS
        trades = [{"exit_time": 10 * D + 5, "net_bps": 100}, {"exit_time": 10 * D + 9, "net_bps": 50},
                  {"exit_time": 13 * D, "net_bps": -200}, {"exit_time": 50 * D, "net_bps": 999}]
        d = ruin.daily_returns(trades, 10 * D, 14 * D)
        self.assertEqual(len(d), 5)
        self.assertAlmostEqual(d[0], 0.015)
        self.assertEqual(d[1:3], [0.0, 0.0])
        self.assertAlmostEqual(d[3], -0.02)
        rep = ruin.ruin_report(trades, 10 * D, 14 * D)
        self.assertEqual(rep["verdict"], "INSUFFICIENT")
        self.assertEqual(rep["n_trades"], 3)


class Board(unittest.TestCase):
    LOG = ("| Date | Strategy | Hold | Result | Verdict |\n|---|---|---|---|---|\n"
           "| 2026-10-01 | **Alpha** (`a.py`) | 1d | x | FAIL |\n"
           "| 2026-10-02 | **Beta** (`b.py`) | 1d | y | PASS |\n"
           "| 2026-10-03 | Gamma | 1d | z | FAIL |\n| 2026-10-04 | Delta | 1d | w | FAIL |\n")

    def rep(self, match, rpr, verdict="OK"):
        if verdict != "OK":
            ru = {"verdict": verdict, "reason": "few days"}
        else:
            ru = {"verdict": "OK", "p_ruin": 0.1, "median_30d_return": 0.05, "p5_30d_return": -0.2,
                  "p95_30d_return": 0.3, "return_per_ruin": rpr, "n_days": 100, "n_trades": 12}
        return {"title": match, "log_match": match, "ruin": ru}

    def test_ranks_by_return_per_ruin_and_lists_every_logged_test(self):
        md = leaderboard.build(self.LOG, [self.rep("a.py", 0.5), self.rep("b.py", 2.0),
                                          self.rep("Gamma", 0, "INSUFFICIENT")])
        self.assertLess(md.index("Beta"), md.index("Alpha"))
        self.assertIn("Delta", md)
        self.assertIn("| 1 | Beta (b.py) | PASS", md)
        self.assertIn("Ruin run INSUFFICIENT", md)
        self.assertEqual(len(leaderboard.parse_log(self.LOG)), 4)

    def test_unlogged_ruin_report_still_shown(self):
        md = leaderboard.build(self.LOG, [self.rep("zzz", 9.0)])
        self.assertIn("not in STRATEGY_LOG yet", md)


if __name__ == "__main__":
    unittest.main()
