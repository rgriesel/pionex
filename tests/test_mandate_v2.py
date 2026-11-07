"""CLO-239: temporary configurations only; no network or credentials."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pionex_lab.mandate import PolicyError, check_mandate, load_mandate
from test_live_gate import mk_mandate
from tools import owner_enable_live_v2 as owner


class MandateV2(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "config").mkdir()
        (self.root / "var").mkdir()
        mk_mandate(self.root / "config")
        self.source = load_mandate(self.root / "config")
        self.candidate = owner.proposal(self.source, authorization="fixture owner", account_scope="test")

    def test_v1_still_loads_and_v2_roundtrips(self):
        self.assertEqual(self.source.schema_version, 1)
        old = self.source.path.read_bytes()
        owner.write_once(self.root, self.candidate, ["fixture-strategy"], "nonexistent-key-file")
        loaded = load_mandate(self.root / "config")
        self.assertEqual(loaded.schema_version, 2)
        self.assertEqual(loaded.max_leverage, 1)
        self.assertFalse(loaded.futures_allowed)
        self.assertEqual(old, self.source.path.read_bytes())
        live = json.loads((self.root / "var/live.json").read_text())
        self.assertEqual(live["approved_mandate_sha256"], loaded.sha256)
        self.assertEqual(live["strategy_allowlist"], ["fixture-strategy"])
        with self.assertRaises(PolicyError):
            owner.write_once(self.root, self.candidate, ["fixture-strategy"], "unused")

    def test_new_fields_fail_closed(self):
        for key, bad in (("max_leverage", "Infinity"), ("max_leverage", True),
                         ("max_leverage", 2), ("max_leverage", "NaN"),
                         ("max_leverage", 1.5), ("max_leverage", 0),
                         ("per_bot_tp_sl_required", False),
                         ("gross_margin_fraction", 0.51), ("position_margin_fraction", 0),
                         ("position_margin_fraction", "NaN"), ("gross_margin_fraction", True),
                         ("agent_may_raise_limits", True)):
            with self.subTest(key=key, bad=bad):
                m = copy.deepcopy(self.candidate)
                m.raw["risk"][key] = bad
                with self.assertRaises(PolicyError):
                    check_mandate(m)
        for types in ([], ["spot_grid", "spot_grid"], ["futures_grid"], ["FUTURES_GRID"],
                      [""], [None], "spot_grid"):
            m = copy.deepcopy(self.candidate)
            m.raw["allowed_bot_types"] = types
            with self.assertRaises(PolicyError):
                check_mandate(m)

    def test_failed_evidence_cannot_grant_leverage(self):
        for report in ({}, {"verdict": "FAIL", "selected_leverage": 5},
                       {"verdict": "PASS", "selected_leverage": 5, "gates": {}}):
            with self.assertRaises(PolicyError):
                owner.proposal(self.source, authorization="owner", account_scope="test", futures_report=report)

    def test_futures_use_selected_leverage_and_optional_legacy_spot_flag(self):
        report = {"verdict": "PASS", "selected_leverage": 2,
                  "gates": {k: True for k in ("G1_windows", "G2_mean_pos", "G3_boot_lower_pos",
                                             "G4_dd_liq", "G5_thirds", "G6_stressed", "G7_total_pos")},
                  "by_leverage": {"2": {"max_dd": 0.1, "liquidations": 0}}}
        m = owner.proposal(self.source, authorization="fixture", account_scope="test", futures_report=report)
        self.assertTrue(m.futures_allowed)
        self.assertEqual(m.max_leverage, 2)
        del m.raw["risk"]["spot_only"]
        del m.raw["risk"]["leverage"]
        check_mandate(m)
        report["by_leverage"]["2"]["max_dd"] = 0.36
        with self.assertRaises(PolicyError):
            owner.proven_leverage(report)

    def test_confirmed_write_uses_gate_and_revocation_refuses(self):
        result = owner.gate.GateResult("fixture", "grid", [owner.gate.Check("fixture", True, 1, "1")])
        for revoke in (True, False):
            with patch.object(owner.gate, "evaluate_all", side_effect=[[result], [] if revoke else [result]]), \
                 patch("builtins.input", side_effect=["owner", "test", "key-path-never-opened", owner.CONFIRM]), \
                 contextlib.redirect_stdout(io.StringIO()):
                if revoke:
                    with self.assertRaises(PolicyError):
                        owner.main(["--root", str(self.root), "--write"])
                    self.assertFalse((self.root / "var/live.json").exists())
                else:
                    self.assertEqual(owner.main(["--root", str(self.root), "--write"]), 0)
        self.assertEqual(json.loads((self.root / "var/live.json").read_text())["strategy_allowlist"], ["fixture"])

    def test_default_preview_writes_nothing(self):
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        with patch("builtins.input", side_effect=["owner", "test"]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(owner.main(["--root", str(self.root)]), 0)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_empty_gate_and_bad_confirmation_refuse_write(self):
        result = owner.gate.GateResult("fixture", "grid", [owner.gate.Check("fixture", True, 1, "1")])
        for results, answers in (([], ["owner", "test"]),
                                 ([result], ["owner", "test", "missing-key", "yes"])):
            with patch.object(owner.gate, "evaluate_all", return_value=results), \
                 patch("builtins.input", side_effect=answers), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(PolicyError):
                    owner.main(["--root", str(self.root), "--write"])
            self.assertFalse((self.root / "var/live.json").exists())

    def test_rollback_and_empty_allowlist(self):
        original = (self.root / "config/mandate.lock.json").read_bytes()
        with self.assertRaises(PolicyError):
            owner.write_once(self.root, self.candidate, [], "unused")
        with patch.object(owner, "load_mandate", side_effect=[self.source, PolicyError("fixture failure")]):
            with self.assertRaises(PolicyError):
                owner.write_once(self.root, self.candidate, ["fixture"], "unused")
        self.assertEqual(original, (self.root / "config/mandate.lock.json").read_bytes())
        self.assertFalse((self.root / "config/mandate.v2.json").exists())
        self.assertFalse((self.root / "var/live.json").exists())

    def test_authorization_and_scope_cannot_be_blank(self):
        for auth, scope in ((" ", "test"), ("owner", "\t")):
            with self.assertRaises(PolicyError):
                owner.proposal(self.source, authorization=auth, account_scope=scope)

    def test_interrupted_or_concurrent_setup_preserves_files(self):
        guard = self.root / "config/.owner_enable_live_v2.lock"
        guard.write_text("existing setup")
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        with self.assertRaisesRegex(PolicyError, "SETUP_IN_PROGRESS_OR_INTERRUPTED"):
            owner.write_once(self.root, self.candidate, ["fixture"], "unused")
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_changed_source_refuses_and_cleans_guard(self):
        original = (self.root / "config/mandate.lock.json").read_bytes()
        with self.assertRaisesRegex(PolicyError, "SOURCE_MANDATE_CHANGED"):
            owner.write_once(self.root, self.candidate, ["fixture"], "unused",
                             expected_source_sha256="stale-preview")
        self.assertEqual(original, (self.root / "config/mandate.lock.json").read_bytes())
        self.assertFalse((self.root / "config/mandate.v2.json").exists())
        self.assertFalse((self.root / "config/.owner_enable_live_v2.lock").exists())

    def test_invalid_evidence_rows_refuse(self):
        report = {"verdict": "PASS", "selected_leverage": 2,
                  "gates": {k: True for k in ("G1_windows", "G2_mean_pos", "G3_boot_lower_pos",
                                             "G4_dd_liq", "G5_thirds", "G6_stressed", "G7_total_pos")}}
        for rows in (None, [], {"2": None}, {"2": {"liquidations": False, "max_dd": 0.1}},
                     {"2": {"liquidations": 0, "max_dd": float("nan")}},
                     {"2": {"liquidations": 0, "max_dd": True}}):
            with self.subTest(rows=rows), self.assertRaises(PolicyError):
                owner.proven_leverage({**report, "by_leverage": rows})

    def test_late_live_write_failure_rolls_back(self):
        original = (self.root / "config/mandate.lock.json").read_bytes()
        real_open = Path.open

        def fail_live(path, *args, **kwargs):
            if path == self.root / "var/live.json":
                raise OSError("fixture live write failure")
            return real_open(path, *args, **kwargs)

        with patch.object(Path, "open", fail_live), self.assertRaises(OSError):
            owner.write_once(self.root, self.candidate, ["fixture"], "unused")
        self.assertEqual(original, (self.root / "config/mandate.lock.json").read_bytes())
        self.assertFalse((self.root / "config/mandate.v2.json").exists())
        self.assertFalse((self.root / "config/.owner_enable_live_v2.lock").exists())

    def test_key_path_is_stored_without_opening(self):
        key = self.root / "credentials-must-not-be-read"
        real_open = Path.open

        def reject_key(path, *args, **kwargs):
            if path == key:
                raise AssertionError("setup attempted a credential read")
            return real_open(path, *args, **kwargs)

        with patch.object(Path, "open", reject_key):
            owner.write_once(self.root, self.candidate, ["fixture"], str(key))
        self.assertEqual(json.loads((self.root / "var/live.json").read_text())["key_file"], str(key))
