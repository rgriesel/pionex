"""CLO-44 luck-proofing suite: synthetic data only, no network, no real var/."""
import json
import random
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pionex_lab.live import gate
from pionex_lab.paths import Paths
from pionex_lab.research import luck

DAY = 86_400_000
T0 = 1_500_000_000_000 // DAY * DAY


def noise(n, mu=0.0, sd=0.01, seed=1):
    rng = random.Random(seed)
    return [rng.gauss(mu, sd) for _ in range(n)]


class Registry(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.reg = Path(self.d.name) / "trials.db"

    def tearDown(self):
        self.d.cleanup()

    def test_append_only_and_idempotent(self):
        self.assertTrue(luck.record_trial(self.reg, "x", "a", weight=3))
        self.assertFalse(luck.record_trial(self.reg, "x", "a", weight=3))
        self.assertEqual(luck.trial_count(self.reg), 3)
        db = sqlite3.connect(self.reg)
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("UPDATE trials SET weight=1")
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("DELETE FROM trials")
        db.close()

    def test_missing_registry_counts_zero(self):
        self.assertEqual(luck.trial_count(self.reg), 0)

    def test_backfill_weights_and_unlogged_reports(self):
        log = Path(self.d.name) / "log.md"
        log.write_text("# log\n## Tested\n| Date | S | R | V |\n|---|---|---|---|\n"
                       "| 2026-10-13 | Strategy zoo: 19 popular, 93 tests | x | FAIL |\n"
                       "| 2026-10-01…12 | Lab research cycles (spot) | x | REJECTED |\n"
                       "| 2026-10-14 | Normal idea, report `named_report.json` | x | FAIL |\n"
                       "## Being tracked forward\n| 2026-10-13 | not a test | x |\n"
                       "## Red Team registry\n| 2026-10-13 | not a test | x | y |\n", encoding="utf-8")
        rep = Path(self.d.name) / "reports"
        rep.mkdir()
        for n in ("named_report.json", "orphan.json", "luck_x.json", "live_gate.json"):
            (rep / n).write_text("{}")
        out = luck.backfill(self.reg, log, rep)
        self.assertEqual(out["count"], 93 + 15 + 1 + 1)               # zoo, lab cycles, normal row, orphan report
        self.assertEqual(luck.backfill(self.reg, log, rep)["count"], out["count"])   # idempotent


class Thresholds(unittest.TestCase):
    def test_tighten_with_count(self):
        a, b, c = luck.thresholds(99), luck.thresholds(400), luck.thresholds(100_000)
        self.assertEqual((a["level"], b["level"]), (0, 2))
        self.assertEqual((a["dsr_prob_min"], a["pbo_max"], a["perm_p_max"]), (0.95, 0.20, 0.01))
        self.assertGreater(b["dsr_prob_min"], a["dsr_prob_min"])
        self.assertLess(b["pbo_max"], a["pbo_max"])
        self.assertLess(b["perm_p_max"], a["perm_p_max"])
        self.assertEqual(c["dsr_prob_min"], 0.99)                      # capped
        self.assertGreaterEqual(c["pbo_max"], 0.05)
        self.assertGreaterEqual(c["perm_p_max"], 0.001)
        self.assertNotEqual(luck.thresholds_sha(99), luck.thresholds_sha(400))


class Stats(unittest.TestCase):
    def test_deflated_sharpe_falls_with_trials(self):
        r = noise(1500, mu=0.0012, seed=2)
        p1, p100, p10k = (luck.deflated_sharpe(r, n)["prob"] for n in (1, 100, 10_000))
        self.assertGreater(p1, p100)
        self.assertGreater(p100, p10k)
        self.assertGreater(p1, 0.95)

    def test_deflated_sharpe_noise_fails(self):
        self.assertLess(luck.deflated_sharpe(noise(1500, seed=3), 200)["prob"], 0.95)

    def test_pbo_noise_is_about_half_and_dominant_is_zero(self):
        rnd = {f"c{i}": noise(800, seed=10 + i) for i in range(12)}
        self.assertTrue(0.25 < luck.pbo_cscv(rnd)["pbo"] < 0.75)
        dom = dict(rnd)
        dom["best"] = [x + 0.004 for x in noise(800, seed=99)]
        self.assertLess(luck.pbo_cscv(dom)["pbo"], 0.05)
        with self.assertRaises(ValueError):
            luck.pbo_cscv({"a": [0.0] * 100})

    def test_timing_null_detects_cheating_and_ignores_noise(self):
        rng = random.Random(5)
        r = [rng.gauss(0, 0.02) for _ in range(600)]
        cheat = [1.0 if x > 0 else 0.0 for x in r]
        self.assertLess(luck.timing_null([cheat], [r], n_perm=300)["p"], 0.01)
        blind = [1.0 if rng.random() < 0.5 else 0.0 for _ in r]
        self.assertGreater(luck.timing_null([blind], [r], n_perm=300)["p"], 0.05)
        self.assertAlmostEqual(luck.timing_null([blind], [r], n_perm=20)["exposure"], sum(blind) / len(blind))
        with self.assertRaises(ValueError):
            luck.timing_null([[1.0] * 10], [[0.0] * 10])

    def test_block_bootstrap_bounds(self):
        self.assertGreater(luck.block_bootstrap(noise(800, mu=0.003, seed=6), n_boot=300)["mean_lower_bps"], 0)
        self.assertLess(luck.block_bootstrap(noise(800, mu=0.0, seed=7), n_boot=300)["mean_lower_bps"], 0)

    def test_monte_carlo(self):
        bad = luck.monte_carlo([-0.08] * 50 + [0.0] * 50, paths=500)
        self.assertGreater(bad["p_lose_50pct"], 0.5)
        flat = luck.monte_carlo([0.001] * 100, paths=200)
        self.assertEqual(flat["p_lose_50pct"], 0.0)
        self.assertAlmostEqual(flat["return_30d"]["p50"], 1.001 ** 30 - 1, places=9)

    def test_regimes_point_in_time(self):
        closes = {T0 + i * DAY: 100.0 for i in range(100)}
        closes.update({T0 + i * DAY: 100.0 * 1.003 ** (i - 100) for i in range(100, 220)})   # steady rise
        lab = luck.regime_labels(closes)
        self.assertNotIn(T0 + 50 * DAY, lab)                           # not enough history
        self.assertEqual(lab[T0 + 99 * DAY], "sideways")
        self.assertEqual(lab[T0 + 215 * DAY], "bull")
        # the crash is labelled only from the close BEFORE a day: the plunge day itself still has the old label
        c2 = {T0 + i * DAY: 100.0 for i in range(100)}
        c2[T0 + 100 * DAY] = 50.0
        c2[T0 + 101 * DAY] = 50.0
        lab2 = luck.regime_labels(c2)
        self.assertEqual(lab2[T0 + 100 * DAY], "sideways")
        self.assertEqual(lab2[T0 + 101 * DAY], "crash")


def synth(n=900, seed=1, drift=0.0008, coins=("BTC_USDT", "ETH_USDT")):
    rng = random.Random(seed)
    data = {}
    for s in coins:
        c, rows, px = [], {}, 100.0
        for i in range(n):
            px *= 1 + rng.gauss(drift, 0.025)
            c.append(px)
        for i in range(n):
            nan = float("nan")
            rows[T0 + i * DAY] = {"o": c[i], "c": c[i], "ema": c[max(0, i - 50)], "vol": 0.6, "age": i,
                                  "r20": c[i] / c[i - 20] - 1 if i >= 20 else nan,
                                  "r60": c[i] / c[i - 60] - 1 if i >= 60 else nan,
                                  "r120": c[i] / c[i - 120] - 1 if i >= 120 else nan}
        data[s] = rows
    return data


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.paths = Paths(Path(self.d.name))
        self.paths.reports.mkdir(parents=True)
        luck.record_trial(self.paths.root / "trials.db", "t", "seed", weight=150)

    def tearDown(self):
        self.d.cleanup()

    def test_report_structure_hash_and_registry(self):
        n0 = luck.trial_count(self.paths.root / "trials.db")
        rep = luck.luck_report("cta_canary", self.paths, n_perm=60, data=synth())
        self.assertEqual(len(rep["tests"]), 9)
        self.assertEqual(rep["registry_count"], n0)                      # computed on the count BEFORE this run
        self.assertGreater(luck.trial_count(self.paths.root / "trials.db"), n0)   # grid configs registered after
        self.assertEqual(rep["sha256"], luck._body_sha(rep))
        saved = json.loads((self.paths.reports / "luck_cta_canary.json").read_text())
        self.assertEqual(saved["sha256"], rep["sha256"])
        self.assertEqual(rep["luck_eligible"], not rep["failed"])
        self.assertIn("cta_canary", luck.render(rep))

    def test_unknown_id(self):
        with self.assertRaises(KeyError):
            luck.luck_report("nope", self.paths)

    def test_short_history_cannot_pass(self):
        rep = luck.luck_report("cta_canary", self.paths, n_perm=30, data=synth(n=400), record=False, write=False)
        self.assertFalse(rep["tests"]["T1_history"]["pass"])
        self.assertFalse(rep["luck_eligible"])


class VerifyReport(unittest.TestCase):
    NOW = 1_800_000_000_000

    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.var = Path(self.d.name)
        (self.var / "reports").mkdir()
        luck.record_trial(self.var / "trials.db", "t", "seed", weight=120)

    def tearDown(self):
        self.d.cleanup()

    def put(self, mutate=None, n=None, at=None):
        n = luck.trial_count(self.var / "trials.db") if n is None else n
        rep = {"strategy_id": "cta_v1_1", "suite": luck.SUITE, "at_ms": at or self.NOW - DAY, "registry_count": n,
               "level": luck.level(n), "thresholds_sha256": luck.thresholds_sha(n),
               "tests": {f"T{i}": {"pass": True} for i in range(1, 10)}}
        if mutate:
            mutate(rep)
        rep["sha256"] = luck._body_sha(rep)
        (self.var / "reports" / "luck_cta_v1_1.json").write_text(json.dumps(rep))
        return rep

    def check(self, gid="defensive"):
        return luck.verify_report(self.var, gid, self.NOW)

    def test_intact_report_passes(self):
        self.put()
        ok, msg = self.check()
        self.assertTrue(ok, msg)

    def test_each_failure_mode_fails_closed(self):
        self.assertFalse(self.check()[0])                                 # no report
        self.put()
        self.assertFalse(self.check("g1")[0])                             # id with no luck-testable series
        self.put(lambda r: r["tests"]["T3"].__setitem__("pass", False))
        ok, msg = self.check()
        self.assertFalse(ok)
        self.assertIn("T3", msg)
        self.put(lambda r: r["tests"].pop("T9"))
        self.assertFalse(self.check()[0])                                 # incomplete
        self.put(lambda r: r["tests"]["T1"].__setitem__("pass", "yes"))
        self.assertFalse(self.check()[0])                                 # truthy is not True
        self.put(at=self.NOW - 40 * DAY)
        self.assertFalse(self.check()[0])                                 # too old
        self.put(at=self.NOW + 5 * DAY)
        self.assertFalse(self.check()[0])                                 # from the future
        self.put(lambda r: r.update(suite="luck-0"))
        self.assertFalse(self.check()[0])                                 # other suite version

    def test_tampering_and_stale_level(self):
        rep = self.put()
        f = self.var / "reports" / "luck_cta_v1_1.json"
        rep["tests"]["T1"]["pass"] = False
        f.write_text(json.dumps(rep))                                     # edited without re-hashing
        self.assertIn("hash", self.check()[1])
        f.write_text("not json")
        self.assertFalse(self.check()[0])
        self.put()
        luck.record_trial(self.var / "trials.db", "t", "more", weight=300)      # registry grows: level changes
        ok, msg = self.check()
        self.assertFalse(ok)
        self.assertIn("stale", msg)

    def test_empty_registry_fails(self):
        self.put(n=120)
        (self.var / "trials.db").unlink()
        self.assertFalse(self.check()[0])

    def test_gate_reads_it(self):
        self.put()
        self.assertTrue(gate.luck_check(self.var, "defensive", self.NOW)[0])
        self.assertFalse(gate.luck_check(self.var, "BTC_narrow_v1", self.NOW)[0])    # shadow grids: never


if __name__ == "__main__":
    unittest.main()
