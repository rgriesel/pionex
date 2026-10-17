"""CLO-29 positioning module: z excludes today, minimum rows, halves split."""
import math
import os
import sqlite3
import tempfile
import unittest

from pionex_lab.swing import positioning as p
from pionex_lab.swing.cta import DAY


class PositioningTests(unittest.TestCase):
    def test_z_excludes_today_and_needs_full_window(self):
        gap = {i * DAY: 0.1 * (i % 3) for i in range(400)}
        gap[399 * DAY] = 5.0
        z = p.divergence_z(gap)
        self.assertNotIn(300 * DAY, z)
        self.assertGreater(z[399 * DAY], 3.0)

    def test_load_gap_requires_min_rows(self):
        f = os.path.join(tempfile.mkdtemp(), "m.db")
        c = sqlite3.connect(f)
        c.execute("CREATE TABLE metrics(symbol TEXT, t INTEGER, top_ls_sum REAL, ls_count REAL)")
        c.executemany("INSERT INTO metrics VALUES('BTC_USDT',?,2.0,1.0)", [(i * 300000,) for i in range(288)])
        c.executemany("INSERT INTO metrics VALUES('BTC_USDT',?,2.0,1.0)", [(DAY + i * 300000,) for i in range(50)])
        c.commit(); c.close()
        gap, span = p.load_gap(f, "BTC_USDT")
        self.assertEqual(list(gap), [0])
        self.assertAlmostEqual(gap[0], math.log(2.0))

    def test_screen_random_has_small_ic_and_halves(self):
        import random
        rng = random.Random(3)
        closes, c = {}, 100.0
        for i in range(700):
            c *= 1 + rng.gauss(0, 0.02)
            closes[i * DAY] = c
        z = {i * DAY: rng.gauss(0, 1) for i in range(10, 690)}
        r = p.screen(z, closes)
        self.assertLess(abs(r["partial_ic"]), 0.2)
        self.assertIn("halves_same_sign", r)

    def test_verdict_insufficient_on_short_history(self):
        self.assertEqual(p.verdict({}, {"BTC_USDT": 500, "ETH_USDT": 2000}), "INSUFFICIENT")


if __name__ == "__main__":
    unittest.main()
