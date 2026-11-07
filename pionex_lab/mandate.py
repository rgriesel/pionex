"""Load the dated, hash-locked risk mandate. Any mismatch fails closed.

The runtime never writes the mandate. Tamper detection compares the file hash with
config/mandate.lock.json and with the hash journaled when the experiment started.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .util import PROJECT_ROOT, sha256_bytes

DEFAULT_CONFIG_DIR = PROJECT_ROOT / "config"

# Constants hard-coded in the skill's reference gate (risk/risk_gate_ref.py). The
# mandate must agree with them, otherwise the reference sizing would silently
# enforce different limits than the mandate states.
REFERENCE_GATE_CONSTANTS = {
    ("experiment", "initial_capital"): 100,
    ("risk", "risk_per_trade_fraction"): Decimal("0.005"),
    ("risk", "canary_risk_per_trade_fraction"): Decimal("0.0025"),
    ("risk", "portfolio_risk_fraction"): Decimal("0.01"),
    ("risk", "position_notional_fraction"): Decimal("0.25"),
    ("risk", "canary_position_notional_fraction"): Decimal("0.10"),
    ("risk", "gross_exposure_fraction"): Decimal("0.50"),
    ("risk", "max_positions"): 2,
    ("risk", "daily_loss_fraction"): Decimal("0.02"),
    ("risk", "weekly_loss_fraction"): Decimal("0.04"),
    ("risk", "peak_drawdown_fraction"): Decimal("0.10"),
    ("risk", "absolute_experiment_loss_usd"): 10,
    ("risk", "max_operating_cost_usd"): 3,
    ("execution", "max_book_age_ms"): 2000,
    ("execution", "max_account_state_age_ms"): 5000,
    ("execution", "max_entry_spread_bps"): 10,
    ("execution", "edge_cost_buffer_bps"): 5,
}


class PolicyError(RuntimeError):
    """The mandate is missing, altered, or inconsistent. Entries must stop."""


@dataclass(frozen=True)
class Mandate:
    raw: dict
    sha256: str
    path: Path

    def get(self, section: str, key: str):
        return self.raw[section][key]

    @property
    def live_enabled(self) -> bool:
        return self.raw["authority"]["live_enabled"] is True

    @property
    def mode(self) -> str:
        return self.raw["authority"]["mode"]

    @property
    def initial_capital(self) -> Decimal:
        return Decimal(str(self.raw["experiment"]["initial_capital"]))

    @property
    def duration_days(self) -> int:
        return int(self.raw["experiment"]["duration_days"])

    @property
    def fee_per_side(self) -> Decimal:
        return Decimal(str(self.raw["execution"]["assumed_spot_fee_per_side_for_research_only"]))

    @property
    def schema_version(self) -> int:
        return int(self.raw["schema_version"])

    @property
    def futures_allowed(self) -> bool:
        """Schema 2 only: the owner's explicit permission for futures products. Schema 1 is always spot."""
        return self.schema_version >= 2 and self.raw["risk"].get("futures_allowed") is True

    @property
    def max_leverage(self) -> Decimal:
        """Highest leverage any action may carry. Schema 1: 1 (unlevered)."""
        if self.schema_version < 2:
            return Decimal(1)
        return Decimal(str(self.raw["risk"]["max_leverage"]))

    @property
    def qualification(self) -> dict:
        return dict(self.raw["qualification"])


def _parse_decimal_json(text: str) -> dict:
    return json.loads(text, parse_float=Decimal)


def load_mandate(config_dir: Path | str = DEFAULT_CONFIG_DIR) -> Mandate:
    config_dir = Path(config_dir)
    lock_path = config_dir / "mandate.lock.json"
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        name = lock["mandate_file"]
        expected = lock["sha256"]
    except (OSError, ValueError, KeyError) as exc:
        raise PolicyError(f"MANDATE_LOCK_UNREADABLE: {exc}") from exc
    if "/" in name or "\\" in name or name.startswith("."):
        raise PolicyError("MANDATE_LOCK_INVALID_PATH")
    path = config_dir / name
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise PolicyError(f"MANDATE_UNREADABLE: {exc}") from exc
    digest = sha256_bytes(data)
    if digest != expected:
        raise PolicyError(f"MANDATE_HASH_MISMATCH: file {digest} != lock {expected}")
    try:
        raw = _parse_decimal_json(data.decode("utf-8"))
    except ValueError as exc:
        raise PolicyError(f"MANDATE_INVALID_JSON: {exc}") from exc
    mandate = Mandate(raw=raw, sha256=digest, path=path)
    check_mandate(mandate)
    return mandate


def check_mandate(m: Mandate) -> None:
    raw = m.raw
    if raw.get("schema_version") not in (1, 2):
        raise PolicyError("MANDATE_SCHEMA_UNSUPPORTED")
    for (section, key), expected in REFERENCE_GATE_CONSTANTS.items():
        try:
            actual = raw[section][key]
        except KeyError as exc:
            raise PolicyError(f"MANDATE_MISSING_{section}.{key}") from exc
        if isinstance(actual, bool) or Decimal(str(actual)) != Decimal(str(expected)):
            raise PolicyError(f"REFERENCE_GATE_MISMATCH: {section}.{key}={actual} expected {expected}")
    risk = raw["risk"]
    if raw["schema_version"] == 1:
        if risk["spot_only"] is not True or Decimal(str(risk["leverage"])) != 1:
            raise PolicyError("MANDATE_NOT_SPOT_UNLEVERED")
    else:                       # schema 2 (owner's full authorization): futures and leverage only when stated explicitly
        fa = risk.get("futures_allowed")
        if not isinstance(fa, bool):
            raise PolicyError("MANDATE_V2_NEEDS_futures_allowed_BOOLEAN")
        if "spot_only" in risk and (not isinstance(risk["spot_only"], bool) or fa == risk["spot_only"]):
            raise PolicyError("MANDATE_V2_futures_allowed_CONTRADICTS_spot_only")
        try:
            lev = Decimal(str(risk["max_leverage"]))
        except (KeyError, ArithmeticError, ValueError):
            raise PolicyError("MANDATE_V2_MISSING_max_leverage") from None
        if isinstance(risk["max_leverage"], bool) or not lev.is_finite() or lev < 1 or lev != lev.to_integral_value() or (not fa and lev != 1):
            raise PolicyError("MANDATE_V2_max_leverage_INVALID")
        types = raw.get("allowed_bot_types")
        if (not isinstance(types, list) or not types or
                any(not isinstance(t, str) or not t.strip() for t in types) or len(set(types)) != len(types)):
            raise PolicyError("MANDATE_V2_ALLOWED_BOT_TYPES_INVALID")
        if not fa and any("future" in t.lower() or "perp" in t.lower() for t in types):
            raise PolicyError("MANDATE_V2_FUTURES_BOT_WITHOUT_PERMISSION")
        if risk.get("per_bot_tp_sl_required") is not True:
            raise PolicyError("MANDATE_V2_BOT_PROTECTION_REQUIRED")
        # Margin includes investment and extra margin. These are ceilings, not
        # authority for the existing spot executor to support new products.
        for margin_key, legacy_key in (
            ("position_margin_fraction", "position_notional_fraction"),
            ("canary_position_margin_fraction", "canary_position_notional_fraction"),
            ("gross_margin_fraction", "gross_exposure_fraction"),
        ):
            try:
                value = Decimal(str(risk[margin_key]))
                valid = (not isinstance(risk[margin_key], bool) and value.is_finite()
                         and 0 < value <= Decimal(str(risk[legacy_key])))
            except (KeyError, ArithmeticError, ValueError):
                valid = False
            if not valid:
                raise PolicyError(f"MANDATE_V2_MARGIN_CAP_INVALID: {margin_key}")
    if risk["agent_may_raise_limits"] is not False or risk["agent_may_withdraw_or_transfer"] is not False:
        raise PolicyError("MANDATE_GRANTS_AGENT_AUTHORITY")
    if raw["experiment"]["additional_deposits_allowed"] is not False:
        raise PolicyError("MANDATE_ALLOWS_CASHFLOWS")
    auth = raw["authority"]
    if auth["live_enabled"] is True and (auth.get("authorization_record") in (None, "")
                                         or auth.get("account_scope") in (None, "")):
        raise PolicyError("LIVE_ENABLED_WITHOUT_AUTHORIZATION_RECORD")
