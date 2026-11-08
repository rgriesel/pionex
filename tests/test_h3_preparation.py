"""Synthetic data/mechanics coverage; no historical return evaluation."""
import unittest

from pionex_lab.research import h3_preparation as p
from pionex_lab.research import own_edge_clo247 as f


def rows(n=8):
    return [(i*p.HOUR, "100", "101", "99", "100", "2", 1, 99) for i in range(n)]


class Preparation(unittest.TestCase):
    def test_complete_volume_and_utc_bins(self):
        r = p.prepare_rows(rows(), "BTC_USDT", 0, 8*p.HOUR)
        self.assertTrue(r["continuous"])
        self.assertEqual(r["four_hour_rows"], 2)
        self.assertEqual(r["base_volume_sum_4h"], 16)

    def test_internal_and_boundary_gaps_are_not_bridged(self):
        for missing in (0, 2, 7):
            r = p.prepare_rows([x for i, x in enumerate(rows()) if i != missing],
                               "BTC_USDT", 0, 8*p.HOUR)
            self.assertFalse(r["continuous"])
            self.assertEqual(r["four_hour_rows"], 1)
            self.assertEqual(r["missing_hours"], [missing*p.HOUR])

    def test_no_rows_reports_all_missing(self):
        r = p.prepare_rows([], "ETH_USDT", 0, 8*p.HOUR)
        self.assertEqual(len(r["missing_hours"]), 8)
        self.assertFalse(r["continuous"])

    def test_duplicate_unordered_partial_misaligned_invalid_rejected(self):
        for bad in (rows()+rows()[:1], rows()[::-1],
                    [(1, *rows()[0][1:])],
                    [(0, "100", "90", "99", "100", "2", 1, 99)],
                    [(0, "100", "101", "99", "100", "nan", 1, 99)],
                    [(0, "100", "101", "99", "100", "2", 0, 99)]):
            with self.assertRaises(ValueError):
                p.prepare_rows(bad, "BTC_USDT", 0, 8*p.HOUR)

    def test_frozen_strategy_rejects_missing_4h_instead_of_resetting(self):
        b = {"t": [0, 2*f.BAR_MS], "o": [100.]*2, "h": [101.]*2,
             "l": [99.]*2, "c": [100.]*2, "v": [2.]*2}
        with self.assertRaises(ValueError):
            f.h3_capitulation(b)

    def test_emergency_target_active_before_planned_hold(self):
        n = 35
        b = {"t": [i*f.BAR_MS for i in range(n)], "o": [100.]*n,
             "h": [101.]*n, "l": [99.]*n, "c": [100.]*n, "v": [2.]*n}
        signals = [0]*n
        signals[20] = 1
        b["h"][21] = 110.
        t = f.replay(b, signals)["trades"][0]
        self.assertEqual(t["exit_reason"], "target")
        self.assertEqual(t["entry_time"], t["exit_time"])
