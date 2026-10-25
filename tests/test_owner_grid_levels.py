import unittest

from pionex_lab.research.owner_grid_levels import ema, perm, stats


class T(unittest.TestCase):
    def test_ema_constant(self):
        self.assertAlmostEqual(ema([5.0] * 30, 10), 5.0)

    def test_stats(self):
        s = stats([1.0, -1.0, 3.0])
        self.assertEqual(s["n"], 3)
        self.assertAlmostEqual(s["sum"], 3.0)

    def test_perm_small_none(self):
        self.assertIsNone(perm([1.0], [2.0, 3.0, 4.0]))


if __name__ == "__main__":
    unittest.main()
