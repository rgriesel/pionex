"""Owner-authorized, one-shot v2 setup. Default is a read-only preview.

Quant tests use temporary fixtures only. The CEO may run --write as the owner's
delegate only after CLO-243 is merged, CLO-238/CLO-239 are done, CLO-241 HOLDS,
and the gate has an ELIGIBLE strategy (owner directive, 2026-11-07).
No transport, credential reads, order calls, or proof-gate changes.
The existing executor remains responsible for all runtime checks and loss halts.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pionex_lab.live import gate
from pionex_lab.mandate import Mandate, PolicyError, check_mandate, load_mandate

CONFIRM = "I AM THE OWNER OR AUTHORIZED CEO: WRITE MANDATE V2"


def proven_leverage(report: dict) -> int:
    """Use the frozen perp-grid test's selected result, never its tested maximum.

    A research PASS is necessary evidence here; it does not replace Red Team,
    Risk review or the live forward gate. FAIL/missing evidence grants no futures.
    """
    if not isinstance(report, dict):
        raise PolicyError("NO_PROVEN_LEVERAGE: qualifying leverage study required")
    lev = report.get("selected_leverage")
    gates = report.get("gates")
    expected = {"G1_windows", "G2_mean_pos", "G3_boot_lower_pos", "G4_dd_liq",
                "G5_thirds", "G6_stressed", "G7_total_pos"}
    if (report.get("verdict") != "PASS" or type(lev) is not int or lev not in (2, 3, 4, 5)
            or not isinstance(gates, dict) or set(gates) != expected
            or any(v is not True for v in gates.values())):
        raise PolicyError("NO_PROVEN_LEVERAGE: qualifying leverage study required")
    rows = report.get("by_leverage")
    row = rows.get(str(lev)) if isinstance(rows, dict) else None
    if (not isinstance(row, dict) or type(row.get("liquidations")) is not int
            or row["liquidations"] != 0 or type(row.get("max_dd")) not in (int, float)
            or not 0 <= row["max_dd"] <= 0.35):
        raise PolicyError("NO_PROVEN_LEVERAGE: selected path fails drawdown/liquidation checks")
    return lev


def proposal(source: Mandate, *, authorization: str, account_scope: str,
             futures_report: dict | None = None) -> Mandate:
    if not authorization.strip() or not account_scope.strip():
        raise PolicyError("AUTHORIZATION_RECORD_AND_ACCOUNT_SCOPE_REQUIRED")
    raw = copy.deepcopy(source.raw)
    raw["schema_version"] = 2
    raw["authority"].update(mode="LIVE", live_enabled=True,
                            authorization_record=authorization, account_scope=account_scope)
    risk = raw["risk"]
    futures = futures_report is not None
    risk.update(futures_allowed=futures, spot_only=not futures,
                max_leverage=proven_leverage(futures_report) if futures else 1,
                per_bot_tp_sl_required=True)
    for new, old in (("position_margin_fraction", "position_notional_fraction"),
                     ("canary_position_margin_fraction", "canary_position_notional_fraction"),
                     ("gross_margin_fraction", "gross_exposure_fraction")):
        risk[new] = risk[old]
    raw["allowed_bot_types"] = ["spot_grid"] + (["futures_grid"] if futures else [])
    out = Mandate(raw, "", source.path.parent / "mandate.v2.json")
    check_mandate(out)
    return out


def plain_diff(before, after, prefix=""):
    lines = []
    for key, value in after.items():
        name = f"{prefix}{key}"
        old = before.get(key)
        if isinstance(value, dict) and isinstance(old, dict):
            lines.extend(plain_diff(old, value, name + "."))
        elif old != value:
            lines.append(f"{name}: {old!s} -> {value!s}")
    return lines


def write_once(root: Path, candidate: Mandate, allowlist: list[str], key_path: str,
               *, expected_source_sha256: str | None = None):
    """Publish live config last; roll back on failure. Never open the key path."""
    # An exclusive guard prevents a second setup from rolling back the first
    # writer's lock. A crash leaves the guard for deliberate reconciliation.
    guard = root / "config" / ".owner_enable_live_v2.lock"
    try:
        guard_file = guard.open("x", encoding="utf-8")
    except FileExistsError:
        raise PolicyError("SETUP_IN_PROGRESS_OR_INTERRUPTED: reconcile setup guard") from None
    try:
        with guard_file:
            _write_once_locked(root, candidate, allowlist, key_path, expected_source_sha256)
    finally:
        guard.unlink()


def _write_once_locked(root: Path, candidate: Mandate, allowlist: list[str], key_path: str,
                       expected_source_sha256: str | None):
    cfg, var = root / "config", root / "var"
    target, lock, live = cfg / "mandate.v2.json", cfg / "mandate.lock.json", var / "live.json"
    if any(p.is_symlink() or p.resolve().parent != parent.resolve()
           for p, parent in ((target, cfg), (lock, cfg), (live, var))):
        raise PolicyError("OUTPUT_PATH_UNSAFE")
    if target.exists() or live.exists():
        raise PolicyError("ALREADY_CONFIGURED: reconcile existing files manually")
    if (not isinstance(allowlist, list) or not allowlist
            or any(not isinstance(s, str) or not s.strip() for s in allowlist)
            or not key_path.strip()):
        raise PolicyError("ELIGIBLE_STRATEGIES_AND_KEY_PATH_REQUIRED")
    check_mandate(candidate)
    if candidate.schema_version != 2 or not candidate.live_enabled or candidate.mode != "LIVE":
        raise PolicyError("LIVE_V2_PROPOSAL_REQUIRED")
    data = (json.dumps(candidate.raw, indent=2, default=str) + "\n").encode()
    digest = hashlib.sha256(data).hexdigest()
    original_lock = lock.read_bytes()
    source = load_mandate(cfg)  # Never replace a broken source mandate/lock.
    if expected_source_sha256 is not None and source.sha256 != expected_source_sha256:
        raise PolicyError("SOURCE_MANDATE_CHANGED: preview again before writing")
    created = []
    try:
        with target.open("xb") as f:
            created.append(target)
            f.write(data)
        new_lock = json.dumps({"mandate_file": target.name, "schema_version": 2, "sha256": digest})
        lock.write_text(new_lock + "\n", encoding="utf-8")
        load_mandate(cfg)
        with live.open("x", encoding="utf-8") as f:
            created.append(live)
            json.dump({"approved_mandate_sha256": digest, "key_file": key_path,
                       "strategy_allowlist": sorted(set(allowlist))}, f, indent=2)
    except BaseException:
        lock.write_bytes(original_lock)
        for p in reversed(created):
            p.unlink()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--futures", action="store_true", help="requires the frozen leverage study to PASS")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    source = load_mandate(root / "config")
    report = None
    if args.futures:
        report = json.loads((root / "var/reports/perp_grid_2026-10-18.json").read_text(encoding="utf-8"))
    authorization = input("Owner authorization record (reference, not credentials): ").strip()
    scope = input("Test account scope (label, not credentials): ").strip()
    candidate = proposal(source, authorization=authorization, account_scope=scope, futures_report=report)
    print("Proposed owner authorization (capital stays 100 USDT; loss halts and proof gate still apply):")
    print("\n".join(plain_diff(source.raw, candidate.raw)))
    print("Margin caps include investment plus extra margin; unsupported products remain refused by the executor.")
    eligible = sorted(gate.eligible_ids(gate.evaluate_all(root / "var", root / "docs/STRATEGY_LOG.md",
                                                       candidate, int(time.time() * 1000))))
    print("Currently eligible strategies:", ", ".join(eligible) or "NONE")
    if not args.write:
        print("DRY RUN: no files written. Owner or authorized CEO must use --write for one-shot setup.")
        return 0
    if not eligible:
        raise PolicyError("NO_ELIGIBLE_STRATEGY")
    key_path = input("Key FILE PATH (contents will not be read): ").strip()
    if input(f"Type exactly {CONFIRM!r}: ") != CONFIRM:
        raise PolicyError("OWNER_CONFIRMATION_REQUIRED")
    # Re-evaluate immediately before publishing; the executor evaluates again.
    eligible = sorted(gate.eligible_ids(gate.evaluate_all(root / "var", root / "docs/STRATEGY_LOG.md",
                                                       candidate, int(time.time() * 1000))))
    write_once(root, candidate, eligible, key_path, expected_source_sha256=source.sha256)
    print("Owner setup written. Runtime proof gate remains automatic.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PolicyError, OSError, ValueError) as exc:
        print(f"Setup refused: {exc}", file=sys.stderr)
        raise SystemExit(1)
