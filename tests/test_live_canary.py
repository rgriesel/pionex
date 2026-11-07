"""CLO-243 synthetic qualification fixtures; no network, credentials, or orders."""
import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pionex_lab.live import canary, gate

NOW = 1_800_000_000_000


class Mandate:
    def __init__(self):
        self.raw = {"experiment": {"initial_capital": 100}, "risk": {
            "futures_allowed": True, "max_leverage": 2, "daily_loss_fraction": .02,
            "absolute_experiment_loss_usd": 10, "peak_drawdown_fraction": .1}}

    def get(self, section, key):
        return self.raw[section][key]


class CanaryTests(unittest.TestCase):
    def setUp(self):
        self.m = Mandate()
        self.c = {"params": {"symbol": "BTC.PERP_USDT", "trend": "long", "rows": 10,
            "bottom": 90, "top": 110, "loss_stop": 80, "profit_stop": 120, "leverage": 2},
            "evidence": {"method": "owner-method", "observations": 4, "net_expectancy": .01,
                "includes": {k: True for k in ("fees", "slippage", "spread", "funding", "exit", "inventory")},
                "closed_bar_decisions": True, "next_open_fills": True, "venue": "PROXY", "certified_max_leverage": 2}}
        self.pin = canary.review_hash(self.c)
        self.obs = {"source": "PIONEX", "complete": True, "enforced_policy": "CLO-243-v1",
            "account_ts": NOW, "quote_ts": NOW, "rules_ts": NOW, "closed_bots": [],
            "strategy_total_pnl": 0, "committed_margin": 0, "day_peak_pnl": 0,
            "firm_total_pnl": 0, "halted": False}

    def result(self, observer=True, verdict="HOLDS"):
        fn = (lambda *_: self.obs) if observer else None
        return canary.qualify("c1", self.c, {"c1": (verdict, self.pin)}, self.m, NOW, fn)

    def test_loose_screen_initial_five_without_paper_record(self):
        r = self.result()
        self.assertTrue(r.eligible, r.as_dict())
        self.assertEqual(r.params["invest"], 5)
        self.assertEqual(r.as_dict()["tier"], "LIVE_CANARY")
        self.assertEqual(r.kind, "canary_grid")  # legacy executor cannot execute this kind

    def test_no_adapter_never_eligible(self):
        self.assertFalse(self.result(False).eligible)

    def test_scale_and_retire_survive_repeated_evaluation(self):
        self.obs["closed_bots"] = [{"id": str(i), "net_pnl": .25} for i in range(5)]
        self.obs["strategy_total_pnl"] = 1.25
        self.assertEqual(self.result().params["invest"], 10)
        self.obs["closed_bots"].append({"id": "loss", "net_pnl": -.01})
        self.assertFalse(self.result().eligible)
        self.assertFalse(self.result().eligible)

    def test_four_winners_cannot_scale(self):
        self.obs["closed_bots"] = [{"id": str(i), "net_pnl": 1} for i in range(4)]
        self.obs["strategy_total_pnl"] = 4
        self.assertEqual(self.result().params["invest"], 5)

    def test_duplicate_bot_history_rejected(self):
        self.obs["closed_bots"] = [{"id": "a", "net_pnl": 1}] * 5
        self.assertFalse(self.result().eligible)

    def test_every_cost_causality_and_pin_required(self):
        for key in self.c["evidence"]["includes"]:
            c = copy.deepcopy(self.c)
            self.c["evidence"]["includes"][key] = False
            self.pin = canary.review_hash(self.c)
            self.assertFalse(self.result().eligible, key)
            self.c = c
        self.c["evidence"]["next_open_fills"] = False
        self.pin = canary.review_hash(self.c)
        self.assertFalse(self.result().eligible)

    def test_evidence_or_parameter_mutation_revokes_holds(self):
        self.c["evidence"]["net_expectancy"] = .02
        self.assertFalse(self.result().eligible)
        self.pin = canary.review_hash(self.c)
        self.c["params"]["rows"] = 11
        self.assertFalse(self.result().eligible)

    def test_zero_negative_nonfinite_expectancy_and_bad_verdict(self):
        for value in [0, -1, float("nan"), float("inf"), "1", True]:
            self.c["evidence"]["net_expectancy"] = value
            self.pin = canary.review_hash(self.c)
            self.assertFalse(self.result().eligible, value)
        self.setUp()
        for v in ["BREAKS", "HOLDS WITH FIXES", "holds"]:
            self.assertFalse(self.result(verdict=v).eligible)

    def test_stale_future_incomplete_or_wrong_source_rejected(self):
        for key, value in [("quote_ts", NOW-5001), ("account_ts", NOW-300001),
            ("rules_ts", NOW-86400001), ("quote_ts", NOW+1), ("complete", False),
            ("source", "PROXY"), ("enforced_policy", "unknown")]:
            obs = self.obs.copy()
            self.obs[key] = value
            self.assertFalse(self.result().eligible, key)
            self.obs = obs

    def test_margin_counts_extra_and_exact_boundary(self):
        self.c["params"]["extra_margin"] = 2
        self.pin = canary.review_hash(self.c)
        self.obs["committed_margin"] = 95
        r = self.result()
        self.assertTrue(r.eligible)
        self.assertEqual(r.params["invest"], 3)
        self.obs["committed_margin"] = 95.01
        self.assertFalse(self.result().eligible)

    def test_loss_halts_and_stricter_mandate(self):
        for key, value in [("halted", True), ("strategy_total_pnl", -1),
            ("firm_total_pnl", -10), ("day_peak_pnl", 2), ("committed_margin", -1)]:
            obs = self.obs.copy()
            self.obs[key] = value
            self.assertFalse(self.result().eligible, key)
            self.obs = obs
        self.m.raw["risk"]["daily_loss_fraction"] = .005
        self.obs["day_peak_pnl"] = .5
        self.assertFalse(self.result().eligible)

    def test_brackets_leverage_and_short(self):
        for key, value in [("loss_stop", 95), ("profit_stop", 105), ("leverage", 3), ("trend", "no_trend")]:
            c = copy.deepcopy(self.c)
            self.c["params"][key] = value
            self.pin = canary.review_hash(self.c)
            self.assertFalse(self.result().eligible, key)
            self.c = c
        self.c["params"].update(trend="short", loss_stop=120, profit_stop=80)
        self.pin = canary.review_hash(self.c)
        self.assertTrue(self.result().eligible)

    def test_observer_error_rejects(self):
        def failed(*_):
            raise TimeoutError("synthetic")
        r = canary.qualify("c1", self.c, {"c1": ("HOLDS", self.pin)}, self.m, NOW, failed)
        self.assertFalse(r.eligible)

    def test_canary_cannot_clear_existing_health_stop(self):
        from pionex_lab.live import health
        with tempfile.TemporaryDirectory() as tmp:
            var = Path(tmp)
            health.stop_strategy(var, "c1", ["synthetic drift"], NOW)
            r = self.result()
            r.checks.append(gate.Check("stop_cleared", False, "PAUSED", "manual review"))
            self.assertEqual(gate.requalify(var, [r], NOW), [])
            self.assertTrue(health.is_stopped(var, "c1"))

    def test_registry_missing_corrupt_and_latest_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            var = Path(tmp)
            log = var / "log.md"
            log.write_text("## Red Team registry\n| c1 | HOLDS | d | review | " + self.pin + " |\n")
            self.assertEqual(gate.evaluate_all(var, log, self.m, NOW), [])
            db = sqlite3.connect(var / "canary_registry.db")
            db.execute("CREATE TABLE candidates(id TEXT PRIMARY KEY, candidate TEXT)")
            db.execute("INSERT INTO candidates VALUES (?,?)", ("c1", json.dumps(self.c)))
            db.commit()
            db.close()
            results = gate.evaluate_all(var, log, self.m, NOW, canary_observer=lambda *_: self.obs)
            self.assertEqual(gate.eligible_ids(results), {"c1"})
            # Even an otherwise passing canary obeys an existing strategy stop.
            (var / "LIVE_STOP_c1").write_text("synthetic stop")
            self.assertFalse(gate.evaluate_all(var, log, self.m, NOW, canary_observer=lambda *_: self.obs)[0].eligible)
            (var / "LIVE_STOP_c1").unlink()
            with log.open("a") as f:
                f.write("| c1 | BREAKS | d | revoked | " + self.pin + " |\n")
            self.assertFalse(gate.evaluate_all(var, log, self.m, NOW, canary_observer=lambda *_: self.obs)[0].eligible)
            (var / "canary_registry.db").write_bytes(b"invalid sqlite")
            r = gate.evaluate_all(var, log, self.m, NOW)
            self.assertFalse(r[0].eligible)
