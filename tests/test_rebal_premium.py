"""Rebalancing-premium sleeve simulator: bookkeeping on synthetic series."""
import math
import unittest

from pionex_lab.swing import rebal_premium as rp
from pionex_lab.swing.cta import DAY

T0 = 1_514_764_800_000          # 2018-01-01 UTC


def coin(prices, start=0):
    t = [T0 + (start + i) * DAY for i in range(len(prices))]
    return {"t": t, "o": list(prices), "c": list(prices)}


class SimTests(unittest.TestCase):
    def run_sleeve(self, sleeve, series, cost=0.0, days=None, haircut=0.0):
        n = days or len(next(iter(series.values()))["t"])
        return rp.simulate(series, lambda t: set(series), sleeve, {k: cost for k in series}, T0, T0 + (n - 1) * DAY, haircut)

    def test_constant_prices_no_cost_flat(self):
        s = {"A": coin([1.0] * 40), "B": coin([2.0] * 40)}
        rows, _ = self.run_sleeve("threshold", s)
        self.assertTrue(all(abs(r[1]) < 1e-12 for r in rows))

    def test_entry_cost_only_on_first_day(self):
        s = {"A": coin([1.0] * 10), "B": coin([1.0] * 10)}
        rows, _ = self.run_sleeve("drift", s, cost=0.001)
        self.assertAlmostEqual(rows[0][1], -0.001)
        self.assertTrue(all(abs(r[1]) < 1e-12 for r in rows[1:]))

    def test_mean_reversion_rebalancing_beats_drift(self):
        a = [1.0 if i % 2 == 0 else 2.0 for i in range(80)]
        b = [1.0] * 80
        s = {"A": coin(a), "B": coin(b)}
        d, _ = self.run_sleeve("drift", s)
        th, nreb = self.run_sleeve("threshold", s)
        nav = lambda rows: math.prod(1 + r[1] for r in rows)
        self.assertGreater(nav(th), nav(d))
        self.assertGreater(nreb, 0)

    def test_drift_has_no_rebalance_trades(self):
        s = {"A": coin([1.0 + 0.05 * i for i in range(60)]), "B": coin([1.0] * 60)}
        rows, nreb = self.run_sleeve("drift", s)
        self.assertEqual(nreb, 0)
        self.assertTrue(all(r[3] < 1e-9 for r in rows[1:]))

    def test_ended_coin_sold_with_haircut(self):
        s = {"A": coin([1.0] * 30), "B": coin([1.0] * 60)}
        plain, _ = rp.simulate(s, lambda t: set(s), "drift", {"A": 0.0, "B": 0.0}, T0, T0 + 59 * DAY)
        cut, _ = rp.simulate(s, lambda t: set(s), "drift", {"A": 0.0, "B": 0.0}, T0, T0 + 59 * DAY, 0.5)
        self.assertTrue(all(abs(r[1]) < 1e-12 for r in plain))
        hit = [r for r in cut if abs(r[1]) > 1e-12]
        self.assertEqual(len(hit), 1)
        self.assertAlmostEqual(hit[0][1], -0.25)

    def test_monthly_rebalances_on_first_of_month(self):
        s = {"A": coin([1.0 + 0.02 * i for i in range(70)]), "B": coin([1.0] * 70)}
        _, nreb = self.run_sleeve("monthly", s)
        self.assertEqual(nreb, 2)             # 2018-02-01 and 2018-03-01


if __name__ == "__main__":
    unittest.main()
