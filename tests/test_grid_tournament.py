"""Synthetic ledger fixtures only; these are not strategy performance tests."""
import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from pionex_lab.live import shadow_grid as sg
from pionex_lab.research import grid_tournament as t


class TournamentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # Exercise SQLite URI escaping for the read-only ledger.
        self.path = Path(self.tmp.name) / "shadow #1.db"
        self.a = sg.Config("a", "BTC_USDT", 0.08, 40)
        self.b = replace(self.a, id="b", symbol="ETH_USDT")
        self.start = 1000
        self.end = self.start + t.WEEK
        self.db = sg.open_db(self.path)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def ledger(self, cfg, final=1010.0, base=0.0, gap=False, hole=False):
        params = {"symbol": cfg.symbol, "band": cfg.band, "rows": cfg.rows,
                  "invest": cfg.invest, "type": cfg.grid_type}
        self.db.execute("INSERT INTO grids VALUES(?,?,?,?,?)",
                        (cfg.id, cfg.symbol, json.dumps(params), self.start, 100.0))
        rows = []
        for ts in range(self.start, self.end+1, 60_000):
            if hole and self.start+120_000 <= ts <= self.start+300_000:
                continue
            equity = cfg.invest + (final-cfg.invest)*(ts-self.start)/t.WEEK
            rows.append((ts, cfg.id, 100.0, equity, 50, equity-cfg.invest-50,
                         0, equity-base*100, base, 20, 10, "running", ts, "[]"))
        self.db.executemany("INSERT INTO snaps(ts,grid_id,price,equity,grid_profit,float_profit,b,cash,base,"
                            "fills,trips,status,cursor_ts,cursor_ids) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        if gap:
            self.db.execute("INSERT INTO events(ts,grid_id,kind) VALUES(?,?,?)", (self.start+1000, cfg.id, "gap"))
        self.db.commit()

    def evaluate(self, configs=None, **kwargs):
        return t.evaluate_cohort(self.path, configs or [self.a], self.start, self.end, **kwargs)

    def test_frozen_grid_and_no_leverage(self):
        cfgs = t.initial_configs()
        self.assertEqual(len(cfgs), 18)
        self.assertEqual(len({c.id for c in cfgs}), 18)
        self.assertEqual({c.invest for c in cfgs}, {1000.0})
        self.assertIn("PRE-REGISTERED", t.evaluate_cohort.__doc__)

    def test_economic_pnl_not_realised_grid_profit(self):
        self.ledger(self.a, 980)
        self.ledger(self.b, 1010)
        rep = self.evaluate([self.a, self.b])
        self.assertEqual([r["id"] for r in rep["ranking"]], ["b", "a"])
        self.assertEqual(rep["retire_proposals"], ["a"])
        self.assertEqual({v["parent"] for v in rep["variant_proposals"]}, {"b"})
        self.assertEqual(rep["verdict"], "INSUFFICIENT")
        self.assertFalse(rep["pass"])
        self.assertFalse(rep["live_eligible"])

    def test_exit_fee_and_slip_only_on_residual_inventory(self):
        self.ledger(self.a, 1010, base=5)
        self.ledger(self.b, 1010)
        rep = self.evaluate([self.a, self.b])
        self.assertAlmostEqual(rep["ranking"][1]["net_equity"], 1009.5)
        self.assertAlmostEqual(rep["ranking"][0]["net_equity"], 1010)

    def test_maturity_and_absent_database_do_not_create_file(self):
        rep = t.evaluate_cohort(self.path, [self.a], self.start, self.end-1)
        self.assertIn("not mature", rep["errors"][0])
        missing = self.path.with_name("absent.db")
        rep = t.evaluate_cohort(missing, [self.a], self.start, self.end)
        self.assertTrue(rep["errors"])
        self.assertFalse(missing.exists())

    def test_gap_invalidates_entire_cohort_not_only_loser(self):
        self.ledger(self.a, 980, gap=True)
        self.ledger(self.b, 1010)
        rep = self.evaluate([self.b, self.a])
        self.assertEqual(rep["ranking"], [])
        self.assertEqual(rep["variant_proposals"], [])
        self.assertIn("tape gap", rep["errors"][0])

    def test_restart_or_observation_hole_is_insufficient(self):
        self.ledger(self.a, hole=True)
        self.assertIn("snapshot gap", self.evaluate()["errors"][0])

    def test_changed_config_and_missing_peer_fail_closed(self):
        self.ledger(self.a)
        self.assertIn("parameter mismatch", self.evaluate([replace(self.a, rows=20)])["errors"][0])
        self.assertTrue(self.evaluate([self.a, self.b])["errors"])

    def test_deterministic_bounded_variants_and_generation_cap(self):
        self.ledger(self.a)
        before = self.db.total_changes
        rep = self.evaluate()
        self.assertEqual(rep, self.evaluate())
        self.assertEqual(self.db.total_changes, before)
        self.assertEqual(len(rep["variant_proposals"]), 4)
        for v in rep["variant_proposals"]:
            self.assertEqual(v["invest"], 1000)
            self.assertTrue(0.02 <= v["band"] <= 0.20)
            self.assertTrue(10 <= v["rows"] <= 100)
        self.assertEqual(self.evaluate(generation=4)["variant_proposals"], [])

    def test_no_peek_at_later_snapshots(self):
        self.ledger(self.a)
        self.db.execute("INSERT INTO snaps(ts,grid_id,price,equity,base,cash,status) VALUES(?,?,?,?,?,?,?)",
                        (self.end+1, self.a.id, 100, 5000, 0, 5000, "running"))
        self.db.commit()
        self.assertAlmostEqual(self.evaluate()["ranking"][0]["net_equity"], 1010)

    def test_bad_config_rejected(self):
        for cfg in (replace(self.a, invest=float("nan")), replace(self.a, rows=0), replace(self.a, invest=0)):
            with self.assertRaises(ValueError):
                self.evaluate([cfg])
        with self.assertRaises(ValueError):
            self.evaluate([self.a, self.a])


if __name__ == "__main__":
    unittest.main()
