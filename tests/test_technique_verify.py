import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    'technique_verify_clo68', Path(__file__).resolve().parents[1] / 'research' / 'technique_verify_clo68.py')
tv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tv)


def bars(closes, rng=1.0):
    return [(i * 3600000, c, c + rng, c - rng, c, 10.0) for i, c in enumerate(closes)]


class TechniqueVerifyTest(unittest.TestCase):
    def test_sim_no_touch(self):
        D = tv.prep(bars([100] * 200))
        self.assertIsNone(tv.sim(D, 1, 10, 50.0, 2.0))

    def test_sim_support_win_and_loss(self):
        # price dips to the level at bar 11, then rallies 1 ATR above -> win
        D = tv.prep(bars([100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 99, 105, 110] + [110] * 100))
        r = tv.sim(D, 1, 10, 98.0, 2.0)
        self.assertEqual(r[0], 1.0)
        # collapse through the level by 1 ATR -> loss
        D = tv.prep(bars([100] * 11 + [98.4, 90, 80] + [80] * 100))
        self.assertEqual(tv.sim(D, 1, 10, 98.0, 2.0)[0], -1.0)

    def test_sim_resistance_is_mirrored(self):
        D = tv.prep(bars([100] * 11 + [101, 95, 90] + [90] * 100))
        self.assertEqual(tv.sim(D, -1, 10, 102.0, 2.0)[0], 1.0)

    def test_levels_are_causal(self):
        closes = [100 + (i % 20) for i in range(700)]
        D = tv.prep(bars(closes))
        a = tv.levels(D, 600)
        D2 = tv.prep(bars(closes[:601] + [1000] * 99))
        self.assertEqual(sorted(a), sorted(tv.levels(D2, 600)))


if __name__ == '__main__':
    unittest.main()
