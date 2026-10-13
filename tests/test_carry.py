"""Funding carry study (synthetic data only)."""
import unittest

from pionex_lab.swing import carry

H = 3_600_000
T0 = 1_700_000_000_000 - 1_700_000_000_000 % (8 * H)


class Carry(unittest.TestCase):
    def rows(self, n, spot=100.0, perp=100.0):
        return [(T0 + i * H, spot, spot, perp, perp) for i in range(n)]

    def test_always_collects_every_settlement_after_entry_minus_costs(self):
        rows = self.rows(24 * 10)
        fund = [(T0 + k * 8 * H, 0.0002) for k in range(40)]             # T0 itself settles before entry
        r = carry.simulate(rows, fund, "always")
        held = sum(1 for t, _ in fund if T0 < t <= rows[-1][0])
        self.assertAlmostEqual(r["funding"], held * 0.0002)
        self.assertAlmostEqual(r["net_per_notional"], held * 0.0002 - 4 * carry.LEG_COST_BPS / 1e4)
        self.assertEqual(r["round_trips"], 1)

    def test_gated_waits_for_three_rates_and_exits_when_funding_turns(self):
        rows = self.rows(24 * 10)
        fund = [(T0 + k * 8 * H, 0.0002 if k < 15 else -0.0003) for k in range(1, 31)]
        r = carry.simulate(rows, fund, "gated")
        self.assertEqual(r["round_trips"], 1)
        # enters at the 3rd settlement (missing it), collects the 4th..14th (positive) and the 15th
        # and 16th (negative), exiting once the 3-rate mean drops below zero at the 16th
        self.assertAlmostEqual(r["funding"], 11 * 0.0002 - 0.0003 - 0.0003)
        self.assertLess(r["time_in"], 1.0)

    def test_basis_moves_count(self):
        rows = self.rows(10)[:-1] + [(T0 + 9 * H, 100.0, 110.0, 100.0, 111.0)]
        r = carry.simulate(rows, [], "always")
        self.assertAlmostEqual(r["basis"], 0.10 - 0.11)
        self.assertAlmostEqual(sum(r["thirds"]), r["net_per_notional"])


if __name__ == "__main__":
    unittest.main()
