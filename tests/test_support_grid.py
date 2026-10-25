"""Synthetic bars only. No performance experiment or external data access."""
import unittest

from pionex_lab.research import support_grid as s


def history():
    return [(i*s.HOUR, 104.0, 105.0, 100.0 if i == 50 else 103.0, 104.0)
            for i in range(168)]


class SupportGridTest(unittest.TestCase):
    def test_fixed_family_and_absolute_support_anchor(self):
        r = s.support_family("BTC_USDT", history(), 168*s.HOUR)
        self.assertEqual(len(r["plans"]), 3)
        self.assertEqual([p["leverage"] for p in r["plans"]], [1, 2, 3])
        for p in r["plans"]:
            self.assertEqual(p["bottom"], 100)
            self.assertAlmostEqual(p["top"], 116)
            self.assertEqual(p["stop"], 97)
            self.assertEqual(p["support_bar_ms"], 50*s.HOUR)
            self.assertFalse(p["launch_eligible"])
            self.assertIsNone(p["liquidation_price"])
        self.assertFalse(r["pass"])

    def test_causal_no_unfinished_or_future_bar_anchor(self):
        h = history() + [(168*s.HOUR, 104.0, 105.0, 1.0, 104.0)]
        r = s.support_family("BTC_USDT", h, 168*s.HOUR+5000)
        self.assertEqual(r["plans"][0]["bottom"], 100)

    def test_missing_stale_or_duplicate_input_not_zero_success(self):
        for h in (history()[:-1], history()[1:]):
            self.assertEqual(s.support_family("BTC_USDT", h, 168*s.HOUR)["plans"], [])
        with self.assertRaises(ValueError):
            s.support_family("BTC_USDT", history()+history()[:1], 168*s.HOUR)

    def test_outside_support_distance_and_unregistered_pair(self):
        h = [(t, o, 120.0, low, 120.0) for t, o, high, low, c in history()]
        self.assertEqual(s.support_family("ETH_USDT", h, 168*s.HOUR)["plans"], [])
        with self.assertRaises(ValueError):
            s.support_family("SOL_USDT", history(), 168*s.HOUR)

    def test_separate_wick_close_episodes_and_strict_touch(self):
        bars = [(0, 101, 102, 100, 101), (s.HOUR, 101, 102, 99, 101),
                (2*s.HOUR, 101, 102, 98, 99), (3*s.HOUR, 101, 102, 100, 101),
                (4*s.HOUR, 101, 102, 99, 99)]
        r = s.support_breaks(bars, 100, 0, 5*s.HOUR, 5*s.HOUR)
        self.assertEqual(r["coverage"], "COMPLETE")
        self.assertEqual((r["wick_hours"], r["close_hours"]), (3, 2))
        self.assertEqual((r["wick_episodes"], r["close_episodes"]), (2, 2))
        self.assertEqual(r["first_wick_ms"], s.HOUR)
        self.assertEqual(r["first_close_ms"], 2*s.HOUR)

    def test_missing_or_unfinished_break_bar_is_unknown(self):
        h = [(0, 101, 102, 99, 101)]
        for end, asof in ((2*s.HOUR, 2*s.HOUR), (s.HOUR, s.HOUR-1)):
            r = s.support_breaks(h, 100, 0, end, asof)
            self.assertIsNone(r["wick_hours"])
        complete = s.support_breaks(h, 100, 0, s.HOUR, s.HOUR)
        self.assertEqual(complete["wick_hours"], 1)

    def test_after_end_does_not_count_and_first_hour_break_is_episode(self):
        h = [(0, 99, 102, 98, 99), (s.HOUR, 99, 102, 1, 99)]
        r = s.support_breaks(h, 100, 0, s.HOUR, 2*s.HOUR)
        self.assertEqual(r["wick_hours"], 1)
        self.assertEqual(r["close_episodes"], 1)
        self.assertEqual(r["first_close_ms"], 0)

    def test_invalid_ohlc_support_and_interval_rejected(self):
        with self.assertRaises(ValueError):
            s.support_family("BTC_USDT", [(0, 100, 99, 101, 100)], s.HOUR)
        with self.assertRaises(ValueError):
            s.support_breaks([], float("nan"), 0, s.HOUR, s.HOUR)
        with self.assertRaises(ValueError):
            s.support_breaks([], 100, 1, s.HOUR, s.HOUR)


if __name__ == "__main__":
    unittest.main()
