"""Synthetic level sets only; no market tests or profitability inference."""
import unittest
from dataclasses import replace

from pionex_lab.research import confluence_grid as c


def levels():
    return [c.Level("AVWAP_LOW", 90, 10, "low"), c.Level("EMA50", 90.2, 10, "ema"),
            c.Level("AVWAP_HIGH", 110, 10, "high"), c.Level("SR", 110.2, 10, "sr", 3)]


class ConfluenceTest(unittest.TestCase):
    def plan(self, evidence=None):
        return c.confluence_family("BTC_USDT", "4H", levels() if evidence is None else evidence, 100, 2, 20)

    def test_mirrored_plans_and_controls_preserve_risk_geometry(self):
        r = self.plan()
        self.assertEqual(len(r["plans"]), 8)
        for direction in ("long", "short"):
            for mode in ("fade", "grid"):
                p, control = [x for x in r["plans"] if x["direction"] == direction and x["mode"] == mode]
                self.assertEqual(p["arm"], "confluence")
                for field in ("target", "stop", "entry_low", "entry_high"):
                    self.assertAlmostEqual(p[field]-p["entry_reference"], control[field]-control["entry_reference"])
                self.assertEqual(p["pair_key"], control["pair_key"])
                self.assertFalse(p["launch_eligible"])
                self.assertIsNone(p["liquidation_price"])
        self.assertFalse(r["pass"])

    def test_future_evidence_and_fewer_than_three_sr_touches_excluded(self):
        for p in (replace(levels()[-1], known_ms=21), replace(levels()[-1], touches=2)):
            self.assertEqual(self.plan(levels()[:-1]+[p])["plans"], [])

    def test_two_emas_are_not_two_distinct_types(self):
        evidence = [c.Level("EMA50", 90, 10, "a"), c.Level("EMA200", 90.2, 10, "b")]+levels()[2:]
        self.assertEqual(self.plan(evidence)["plans"], [])

    def test_avwap_direction_required_and_missing_target_skips(self):
        swapped = [replace(p, kind="AVWAP_HIGH") if p.kind == "AVWAP_LOW" else p for p in levels()]
        self.assertFalse(any(p["direction"] == "long" for p in self.plan(swapped)["plans"]))
        self.assertEqual(self.plan(levels()[:2])["plans"], [])

    def test_next_target_need_not_have_an_avwap(self):
        evidence = levels()+[c.Level("FIB50", 95, 10, "fib"), c.Level("EMA200", 95.1, 10, "ema200")]
        short = [p for p in self.plan(evidence)["plans"] if p["direction"] == "short" and p["arm"] == "confluence"]
        self.assertTrue(short)
        self.assertAlmostEqual(short[0]["target"], 95.05)

    def test_random_controls_are_reproducible_and_nonconfluent(self):
        r = self.plan()
        self.assertEqual(r, self.plan())
        for p in r["plans"]:
            if p["arm"] == "random":
                self.assertTrue(all(not z["low"]-1 <= p["entry_reference"] <= z["high"]+1 for z in r["zones"]))

    def test_complete_link_does_not_chain_wide_zones(self):
        evidence = [c.Level("EMA50", 90, 10, "a"), c.Level("FIB50", 90.8, 10, "b"),
                    c.Level("SR", 91.6, 10, "c", 3)]
        r = self.plan(evidence)
        self.assertTrue(all(z["high"]-z["low"] <= 1 for z in r["zones"]))
        self.assertTrue(all(len(z["types"]) == 2 for z in r["zones"]))

    def test_no_unmatched_arm_when_control_search_exhausted(self):
        from unittest.mock import patch
        with patch.object(c, "_random_entry", return_value=(None, 1)):
            self.assertEqual(self.plan()["plans"], [])

    def test_invalid_evidence_and_unregistered_frame_rejected(self):
        for p in (replace(levels()[0], price=float("nan")), replace(levels()[0], kind="ELLIOTT"),
                  replace(levels()[0], source_id="")):
            with self.assertRaises(ValueError):
                self.plan([p])
        with self.assertRaises(ValueError):
            c.confluence_family("BTC_USDT", "1M", [], 100, 2, 20)


if __name__ == "__main__":
    unittest.main()
