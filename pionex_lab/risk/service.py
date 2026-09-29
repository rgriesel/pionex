"""Independent risk service.

* Limits come only from the hash-locked mandate; nothing in the proposal API can
  carry a limit, balance, edge, or qualification flag.
* Entry sizing is delegated unchanged to the skill's tested reference gate
  (risk_gate_ref.py, byte-identical to scripts/risk_gate.py). This service adds the
  production mechanisms the reference lacks: trusted inputs, persisted period
  baselines and high-water mark, latches that survive restarts, atomic
  reservations under a single-writer lease with a fencing token, and exit
  admission that is never blocked by entry halts.
"""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from ..mandate import Mandate, PolicyError, load_mandate
from ..util import canonical_json, utc_day, utc_week
from .risk_gate_ref import evaluate as reference_evaluate

TRANSIENT = {"DATA_STALE", "CLOCK_SKEW", "RECONCILE_PENDING", "QUOTE_DEPEG", "COLLECTOR_DOWN"}
PERIOD = {"DAILY_LOSS": "day", "WEEKLY_LOSS": "week"}
REVIEW = {"PEAK_DRAWDOWN", "ABSOLUTE_LOSS", "POLICY_TAMPER", "UNEXPLAINED_BALANCE",
          "OPERATING_COST_CEILING", "JOURNAL_CORRUPT"}
UNWIND = {"DAILY_LOSS", "WEEKLY_LOSS", "PEAK_DRAWDOWN", "ABSOLUTE_LOSS"}
HEALTHY_CLEAR_MS = 60_000

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS latches(name TEXT PRIMARY KEY, kind TEXT NOT NULL, reason TEXT NOT NULL,
  set_at INTEGER NOT NULL, period_key TEXT, healthy_since INTEGER);
CREATE TABLE IF NOT EXISTS latch_history(id INTEGER PRIMARY KEY, name TEXT NOT NULL, action TEXT NOT NULL,
  reason TEXT NOT NULL, actor TEXT NOT NULL, at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS baselines(key TEXT PRIMARY KEY, period TEXT, equity TEXT NOT NULL, set_at INTEGER NOT NULL,
  late_ms INTEGER);
CREATE TABLE IF NOT EXISTS reservations(id TEXT PRIMARY KEY, decision_id TEXT NOT NULL, symbol TEXT NOT NULL,
  planned_risk TEXT NOT NULL, exposure TEXT NOT NULL, cash TEXT NOT NULL, fencing_token INTEGER NOT NULL,
  status TEXT NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, note TEXT);
CREATE TABLE IF NOT EXISTS lease(id INTEGER PRIMARY KEY CHECK(id=1), holder TEXT NOT NULL, token INTEGER NOT NULL,
  expires_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

PROPOSAL_KEYS = {"decision_id", "strategy", "version", "symbol", "side", "stop", "target",
                 "max_hold_minutes", "reason"}


class LeaseError(RuntimeError):
    pass


class ProposalError(ValueError):
    pass


def validate_proposal(p) -> dict:
    """Narrow strategy -> risk API. Unknown keys (e.g. an attempted limit or
    balance override) are rejected outright."""
    if not isinstance(p, dict):
        raise ProposalError("PROPOSAL_NOT_OBJECT")
    extra = set(p) - PROPOSAL_KEYS
    missing = PROPOSAL_KEYS - set(p)
    if extra or missing:
        raise ProposalError(f"PROPOSAL_SCHEMA extra={sorted(extra)} missing={sorted(missing)}")
    if p["side"] != "BUY":
        raise ProposalError("PROPOSAL_ENTRY_MUST_BE_BUY")
    for k in ("decision_id", "strategy", "version", "symbol", "reason"):
        if not isinstance(p[k], str) or not p[k] or len(p[k]) > 200:
            raise ProposalError(f"PROPOSAL_FIELD_{k.upper()}")
    try:
        stop = Decimal(str(p["stop"]))
        target = None if p["target"] is None else Decimal(str(p["target"]))
    except Exception as exc:  # noqa: BLE001 - any parse failure is a rejection
        raise ProposalError("PROPOSAL_PRICE") from exc
    if not stop.is_finite() or stop <= 0 or (target is not None and (not target.is_finite() or target <= 0)):
        raise ProposalError("PROPOSAL_PRICE")
    hold = p["max_hold_minutes"]
    if isinstance(hold, bool) or not isinstance(hold, int) or not 1 <= hold <= 240:
        raise ProposalError("PROPOSAL_HOLD_OUT_OF_RANGE")  # mandate: 4h maximum intraday holding
    return {**p, "stop": stop, "target": target}


@dataclass
class TrustedContext:
    """Values the engine measures itself (book, market store, reconciliation).
    Never populated from strategy output."""
    mode: str
    health_ok: bool
    reconciled: bool
    fee_verified: bool
    policy_verified: bool
    approved_symbols: list
    book_age_ms: int
    account_age_ms: int
    open_positions: int
    equity_usd: Decimal          # economic equity: liquidation value minus external operating costs
    free_cash_usd: Decimal
    open_planned_risk_usd: Decimal
    open_exposure_usd: Decimal
    operating_spend_usd: Decimal
    strategy_qualified: bool = False


class RiskService:
    def __init__(self, mandate: Mandate, path: Path | str, clock, journal=None, config_dir=None):
        self.mandate = mandate
        self.clock = clock
        self.journal = journal
        self.config_dir = config_dir
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=10, isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.initial = mandate.initial_capital
        r = mandate.raw["risk"]
        self.daily = Decimal(str(r["daily_loss_fraction"]))
        self.weekly = Decimal(str(r["weekly_loss_fraction"]))
        self.peak = Decimal(str(r["peak_drawdown_fraction"]))
        self.absolute = Decimal(str(r["absolute_experiment_loss_usd"]))
        self.max_cost = Decimal(str(r["max_operating_cost_usd"]))
        self.token: int | None = None
        self.holder: str | None = None

    # ------------------------------------------------------------ journal
    def _record(self, kind, payload, now):
        if self.journal is not None:
            self.journal.append(kind, payload, now)

    # ------------------------------------------------------------ lease
    def acquire_lease(self, holder: str, ttl_ms: int = 15_000) -> int:
        now = self.clock.now_ms()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute("SELECT holder, token, expires_at FROM lease WHERE id=1").fetchone()
            if row and row["holder"] != holder and row["expires_at"] > now:
                raise LeaseError(f"lease held by {row['holder']} until {row['expires_at']}")
            token = (row["token"] + 1) if row else 1
            self.conn.execute("INSERT INTO lease(id, holder, token, expires_at) VALUES(1,?,?,?) ON CONFLICT(id) DO "
                              "UPDATE SET holder=excluded.holder, token=excluded.token, expires_at=excluded.expires_at",
                              (holder, token, now + ttl_ms))
            self.conn.execute("COMMIT")
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.token, self.holder = token, holder
        return token

    def renew_lease(self, ttl_ms: int = 15_000) -> None:
        now = self.clock.now_ms()
        cur = self.conn.execute("UPDATE lease SET expires_at=? WHERE id=1 AND holder=? AND token=?",
                                (now + ttl_ms, self.holder, self.token))
        if cur.rowcount != 1:
            raise LeaseError("lease lost; another writer took over")

    def check_token(self, token: int) -> bool:
        row = self.conn.execute("SELECT token, expires_at FROM lease WHERE id=1").fetchone()
        return bool(row) and row["token"] == token and row["expires_at"] > self.clock.now_ms()

    # ------------------------------------------------------------ policy
    def verify_policy(self, journaled_hash: str | None) -> bool:
        """Reload the mandate from disk; any change latches POLICY_TAMPER."""
        now = self.clock.now_ms()
        try:
            fresh = load_mandate(self.config_dir) if self.config_dir else self.mandate
        except PolicyError as exc:
            self.set_latch("POLICY_TAMPER", str(exc), now)
            return False
        if fresh.sha256 != self.mandate.sha256 or (journaled_hash and fresh.sha256 != journaled_hash):
            self.set_latch("POLICY_TAMPER", f"mandate hash changed to {fresh.sha256}", now)
            return False
        return "POLICY_TAMPER" not in self.active_latches()

    # ------------------------------------------------------------ latches
    def active_latches(self) -> dict:
        return {r["name"]: dict(r) for r in self.conn.execute("SELECT * FROM latches")}

    def set_latch(self, name: str, reason: str, now: int, actor: str = "risk_service") -> bool:
        kind = "TRANSIENT" if name in TRANSIENT else "PERIOD" if name in PERIOD else "REVIEW" if name in REVIEW else None
        if kind is None:
            raise ValueError(f"unknown latch {name}")
        period_key = None
        if kind == "PERIOD":
            period_key = utc_day(now) if PERIOD[name] == "day" else utc_week(now)
        cur = self.conn.execute("INSERT OR IGNORE INTO latches(name, kind, reason, set_at, period_key, healthy_since) "
                                "VALUES(?,?,?,?,?,NULL)", (name, kind, reason[:500], now, period_key))
        if cur.rowcount:
            self.conn.execute("INSERT INTO latch_history(name, action, reason, actor, at) VALUES(?,?,?,?,?)",
                              (name, "SET", reason[:500], actor, now))
            self._record("LATCH_SET", {"latch": name, "kind": kind, "reason": reason, "actor": actor,
                                       "policy_hash": self.mandate.sha256}, now)
            return True
        return False

    def _clear(self, name: str, reason: str, actor: str, now: int) -> None:
        self.conn.execute("DELETE FROM latches WHERE name=?", (name,))
        self.conn.execute("INSERT INTO latch_history(name, action, reason, actor, at) VALUES(?,?,?,?,?)",
                          (name, "CLEAR", reason[:500], actor, now))
        self._record("LATCH_CLEARED", {"latch": name, "reason": reason, "actor": actor}, now)

    def observe_health(self, name: str, healthy: bool, reason: str, now: int) -> None:
        """Transient latches: set when unhealthy; clear only after 60 continuous healthy seconds."""
        if name not in TRANSIENT:
            raise ValueError(name)
        latches = self.active_latches()
        if not healthy:
            if name in latches:
                self.conn.execute("UPDATE latches SET healthy_since=NULL WHERE name=?", (name,))
            else:
                self.set_latch(name, reason, now)
            return
        if name in latches:
            since = latches[name]["healthy_since"]
            if since is None:
                self.conn.execute("UPDATE latches SET healthy_since=? WHERE name=?", (now, name))
            elif now - since >= HEALTHY_CLEAR_MS:
                self._clear(name, "60 healthy seconds after resnapshot", "risk_service", now)

    def review_clear(self, name: str, reviewer: str, note: str, now: int) -> None:
        """Human-reviewed clearing for REVIEW latches (CLI only; the engine never calls this)."""
        if name not in REVIEW:
            raise ValueError(f"{name} is not a review latch")
        if not reviewer.strip() or len(note.strip()) < 20:
            raise ValueError("review requires a reviewer and a substantive note")
        if name not in self.active_latches():
            raise ValueError(f"{name} is not set")
        self._clear(name, f"reviewed mandate decision: {note}", f"human:{reviewer}", now)

    def entry_blockers(self) -> list:
        return sorted(self.active_latches())

    def unwind_required(self) -> list:
        return sorted(set(self.active_latches()) & UNWIND)

    # ------------------------------------------------------------ baselines
    def baselines(self) -> dict:
        return {r["key"]: dict(r) for r in self.conn.execute("SELECT * FROM baselines")}

    def _set_baseline(self, key, period, equity, now, late_ms=None):
        self.conn.execute("INSERT INTO baselines(key, period, equity, set_at, late_ms) VALUES(?,?,?,?,?) "
                          "ON CONFLICT(key) DO UPDATE SET period=excluded.period, equity=excluded.equity, "
                          "set_at=excluded.set_at, late_ms=excluded.late_ms", (key, period, str(equity), now, late_ms))

    def observe_equity(self, equity: Decimal, now: int, operating_spend: Decimal = Decimal(0)) -> list:
        """Roll UTC period baselines, update the high-water mark, and latch any breached
        threshold. Dollar ceilings stay fixed; compounding never enlarges them."""
        if not isinstance(equity, Decimal) or not equity.is_finite():
            raise ValueError("equity must be a finite Decimal")
        b = self.baselines()
        day, week = utc_day(now), utc_week(now)
        if b.get("day", {}).get("period") != day:
            late = now - (now // 86_400_000) * 86_400_000
            self._set_baseline("day", day, equity, now, late)
        if b.get("week", {}).get("period") != week:
            self._set_baseline("week", week, equity, now)
        hwm = Decimal(b["hwm"]["equity"]) if "hwm" in b else self.initial
        if equity > hwm or "hwm" not in b:
            self._set_baseline("hwm", None, max(equity, hwm), now)
        f = self.floors()
        new = []
        checks = (("DAILY_LOSS", f["day"]), ("WEEKLY_LOSS", f["week"]),
                  ("PEAK_DRAWDOWN", f["peak"]), ("ABSOLUTE_LOSS", f["absolute"]))
        for name, floor in checks:
            if equity <= floor and self.set_latch(name, f"economic equity {equity} <= floor {floor}", now):
                new.append(name)
        if operating_spend >= self.max_cost and self.set_latch(
                "OPERATING_COST_CEILING", f"operating spend {operating_spend} >= {self.max_cost}", now):
            new.append("OPERATING_COST_CEILING")
        # Period latches clear only after their period ends, all floors pass, and no
        # higher-level (review) latch remains.
        latches = self.active_latches()
        for name, row in latches.items():
            if row["kind"] != "PERIOD":
                continue
            current = day if PERIOD[name] == "day" else week
            if row["period_key"] != current and equity > max(self.floors().values()) \
                    and not (set(latches) & REVIEW):
                self._clear(name, f"period {row['period_key']} ended; checks pass", "risk_service", now)
        return new

    def floors(self) -> dict:
        b = self.baselines()
        day = Decimal(b["day"]["equity"]) if "day" in b else self.initial
        week = Decimal(b["week"]["equity"]) if "week" in b else self.initial
        hwm = Decimal(b["hwm"]["equity"]) if "hwm" in b else self.initial
        return {"day": day * (1 - self.daily), "week": week * (1 - self.weekly),
                "peak": hwm * (1 - self.peak), "absolute": self.initial - self.absolute}

    # ------------------------------------------------------------ reservations
    def active_reservations(self) -> list:
        return [dict(r) for r in self.conn.execute("SELECT * FROM reservations WHERE status='ACTIVE'")]

    def evaluate_entry(self, ctx: TrustedContext, proposal: dict, intent: dict, token: int) -> dict:
        """Run the reference gate on trusted inputs and, if approved, reserve its
        planned risk, exposure, and cash atomically. `intent` holds executable
        prices, costs, the registry edge estimate, and exchange filters."""
        now = self.clock.now_ms()
        p = validate_proposal(proposal)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            if not self.check_token(token):
                self.conn.execute("ROLLBACK")
                return {"approved": False, "reason": "STALE_FENCING_TOKEN"}
            res = [dict(r) for r in self.conn.execute("SELECT * FROM reservations WHERE status='ACTIVE'")]
            reserved_risk = sum((Decimal(r["planned_risk"]) for r in res), Decimal(0))
            reserved_exp = sum((Decimal(r["exposure"]) for r in res), Decimal(0))
            reserved_cash = sum((Decimal(r["cash"]) for r in res), Decimal(0))
            b = self.baselines()
            auth = self.mandate.raw["authority"]
            context = {
                "mode": ctx.mode,
                "halt_latched": bool(self.entry_blockers()),
                "health_ok": ctx.health_ok, "reconciled": ctx.reconciled,
                "fee_verified": ctx.fee_verified, "policy_verified": ctx.policy_verified,
                "live_authorized": auth["live_enabled"] is True and bool(auth.get("authorization_record")),
                "strategy_qualified": ctx.strategy_qualified,
                "account_isolated": False, "native_protection_verified": False,
                "approved_symbols": list(ctx.approved_symbols),
                "book_age_ms": ctx.book_age_ms, "account_age_ms": ctx.account_age_ms,
                "slots_used": ctx.open_positions + len(res),
                "equity_usd": str(ctx.equity_usd), "initial_capital_usd": str(self.initial),
                "day_start_equity_usd": b.get("day", {}).get("equity", str(self.initial)),
                "week_start_equity_usd": b.get("week", {}).get("equity", str(self.initial)),
                "high_water_equity_usd": b.get("hwm", {}).get("equity", str(self.initial)),
                "operating_spend_usd": str(ctx.operating_spend_usd),
                "no_external_cashflows": True,
                "reserved_planned_risk_usd": str(ctx.open_planned_risk_usd + reserved_risk),
                "reserved_gross_exposure_usd": str(ctx.open_exposure_usd + reserved_exp),
                "free_cash_usd": str(max(Decimal(0), ctx.free_cash_usd - reserved_cash)),
            }
            gate_intent = {"market_type": "SPOT", "side": "BUY", "symbol": p["symbol"], **intent}
            gate_intent["stop_usd"] = str(p["stop"])
            result = reference_evaluate({"context": context, "intent": gate_intent})
            if result.get("approved"):
                rid = "rsv-" + uuid.uuid4().hex[:16]
                self.conn.execute(
                    "INSERT INTO reservations(id, decision_id, symbol, planned_risk, exposure, cash, fencing_token, "
                    "status, created_at, updated_at) VALUES(?,?,?,?,?,?,?, 'ACTIVE', ?, ?)",
                    (rid, p["decision_id"], p["symbol"], result["estimated_planned_loss_usd"],
                     result["notional_usd"], result["cash_reservation_usd"], token, now, now))
                result = {**result, "reservation_id": rid}
            self.conn.execute("COMMIT")
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        result["gate_context"] = context
        return result

    def settle_reservation(self, rid: str, status: str, note: str = "") -> None:
        if status not in ("CONSUMED", "RELEASED"):
            raise ValueError(status)
        self.conn.execute("UPDATE reservations SET status=?, updated_at=?, note=? WHERE id=? AND status='ACTIVE'",
                          (status, self.clock.now_ms(), note[:300], rid))

    def state_summary(self) -> dict:
        b = self.baselines()
        return {"latches": self.active_latches(), "floors": {k: str(v) for k, v in self.floors().items()},
                "baselines": {k: {"period": v["period"], "equity": v["equity"], "late_ms": v["late_ms"]}
                              for k, v in b.items()},
                "active_reservations": len(self.active_reservations()),
                "policy_hash": self.mandate.sha256}

    def set_meta(self, key: str, value) -> None:
        self.conn.execute("INSERT INTO meta(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                          (key, canonical_json(value)))


class RiskView:
    """Read-only view of risk state for the dashboard (no writes, no lease)."""

    def __init__(self, mandate: Mandate, path: Path | str):
        self.mandate = mandate
        self.conn = sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA query_only=ON")
        self.initial = mandate.initial_capital
        r = mandate.raw["risk"]
        self.daily = Decimal(str(r["daily_loss_fraction"]))
        self.weekly = Decimal(str(r["weekly_loss_fraction"]))
        self.peak = Decimal(str(r["peak_drawdown_fraction"]))
        self.absolute = Decimal(str(r["absolute_experiment_loss_usd"]))

    active_latches = RiskService.active_latches
    baselines = RiskService.baselines
    floors = RiskService.floors
    active_reservations = RiskService.active_reservations
    state_summary = RiskService.state_summary

    def close(self):
        self.conn.close()
