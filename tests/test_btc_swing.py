"""BTC swing rules v1 (synthetic data only)."""
import math
import unittest
from datetime import datetime, timezone

from pionex_lab.swing import btc_swing as sw

from tests.helpers import make_bars, random_walk

H = 3_600_000
T0 = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


def trend_bars(n, drift, seed=1):
    closes = random_walk(n, 40000.0, 0.004, seed=seed, drift=drift)
    b = make_bars("BTC_USDT", "60M", closes, start=T0, spread=0.002, vol=[100.0] * n)
    return b


class Events(unittest.TestCase):
    def test_cpi_and_fomc_times_with_dst(self):
        cpi = sw._ny_ms("2024-03-12", 8, 30)            # DST began 2024-03-10: 12:30 UTC
        self.assertEqual(datetime.fromtimestamp(cpi / 1000, timezone.utc).hour, 12)
        self.assertEqual(datetime.fromtimestamp(sw._ny_ms("2024-01-31", 14, 0) / 1000, timezone.utc).hour, 19)
        self.assertTrue(sw.near_event(cpi + 11 * H))
        self.assertFalse(sw.near_event(cpi + 13 * H))
        self.assertEqual(len(sw.GRID), 16)


class Rules(unittest.TestCase):
    def check_sides(self, drift, forbidden):
        b = trend_bars(24 * 400, drift)
        d = sw.prepare(b, funding=[(T0 + k * 8 * H, 0.0001) for k in range(1200)], elliott=False)
        sides = set()
        for p in sw.GRID[:4]:
            for i in range(210, len(d["b4"]) - 1):
                s = sw.signal(d, i, p)
                if s:
                    sides.add(s[0])
                    side, stop, target = s
                    c = d["b4"].c[i]
                    self.assertTrue((stop < c < target) if side == "LONG" else (target < c < stop))
        self.assertNotIn(forbidden, sides)
        return d

    def test_uptrend_never_shorts_and_downtrend_never_longs(self):
        self.check_sides(0.0004, "SHORT")
        self.check_sides(-0.0004, "LONG")

    def test_simulation_costs_funding_and_stop_first(self):
        d = self.check_sides(0.0004, "SHORT")
        trades = sw.simulate(d, sw.GRID[0], 0, len(d["b4"]))
        for t in trades:
            self.assertLess(t["net_bps"], t["gross_bps"])                   # fees always cost
            self.assertLessEqual(t["exit_time"] - t["entry_time"], (sw.GRID[0]["hold"] * 4) * H + H)
        for a, b2 in zip(trades, trades[1:]):
            self.assertLessEqual(a["exit_time"], b2["entry_time"])          # one position at a time
        self.assertAlmostEqual(sw.funding_between(d, T0 - 1, T0 + 8 * H), 0.0002)
        if trades:
            worse = sw.simulate(d, sw.GRID[0], 0, len(d["b4"]), cost_mult=2.0)
            self.assertLess(sum(t["net_bps"] for t in worse), sum(t["net_bps"] for t in trades) + 1e-9)


if __name__ == "__main__":
    unittest.main()
