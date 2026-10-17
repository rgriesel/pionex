"""Forward-proof gate (CLO-43 part A). Deterministic: decides from the databases, never from a statement.

A strategy is ELIGIBLE for live trading only if ALL hold (thresholds below are code constants; the drawdown
limit comes from the hash-locked mandate, risk.peak_drawdown_fraction):

  1. forward record on live Pionex prices spans >= MIN_DAYS (30) days (first to last snapshot)
  2. >= MIN_TRADES (20) closed trades: grid round trips (var/shadow_grid.db snaps.trips) or completed round
     trips of a CTA book (var/forward_shadow.db fills)
  3. net profit after Pionex fees > 0 (equity already includes the 0.05%/side fees the runners charge)
  4. max drawdown of the forward equity curve <= mandate peak_drawdown_fraction (peak includes the start capital)
  5. the record is fresh: the last snapshot is <= MAX_STALE_H (48) hours old, so a dead runner cannot qualify
  6. docs/STRATEGY_LOG.md has a Red Team registry row for the strategy whose LATEST verdict is exactly HOLDS
     (a later row with any other verdict revokes it)
  7. (F4) that row carries params_sha256 == params_hash() of the strategy's parameters as stored in the forward
     database now, so changing the parameters after the review revokes eligibility
  8. (F5) the record is continuous: no gap between snapshots over MAX_GAP_H (6) hours and >= MIN_COVERAGE (95%) of the
     hourly buckets in the span hold a snapshot, so two snapshots 30 days apart do not count as 30 days.
     Book "closed trades" are completed round trips (position in a symbol back to flat), not partial sells.
  9. (CLO-44) the luck-proofing suite (research/luck.py) passes ALL nine tests: var/reports/luck_<id>.json is intact
     (hash), current (tightening level of the trial registry unchanged, <= 30 days old) and every test passed. Strategies
     with no luck-testable backtest series (the shadow grids) can never pass this rule.

  10. (CLO-45) not RETIRED, and not under a health-monitor stop: after a DRIFT stop (live/health.py) only the forward record
     made AFTER the stop counts for rules 1-9, and requalify() lifts the stop only when all of them pass on it.

Read-only: databases are opened with mode=ro. Unknown strategy ids are never eligible. No order code here.
Residual trust: row 6 is a text table an agent can edit; the executor therefore also needs the owner's
mandate (LIVE + authorization record, checked by mandate.py), the owner-written var/live.json pin of the mandate
hash and mandatory strategy_allowlist, and the owner's key file. The gate is necessary, not sufficient.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import health

MIN_DAYS = 30.0
MIN_TRADES = 20
MAX_STALE_H = 48.0
MAX_GAP_H = 6.0
MIN_COVERAGE = 0.95
DAY_MS = 86_400_000
REGISTRY_HEADING = "## Red Team registry"


@dataclass
class Check:
    rule: str
    ok: bool
    value: object
    need: str


@dataclass
class GateResult:
    strategy_id: str
    kind: str                       # "grid" | "book"
    checks: list = field(default_factory=list)
    params: dict = field(default_factory=dict)

    @property
    def eligible(self) -> bool:
        return bool(self.checks) and all(c.ok for c in self.checks)

    def as_dict(self) -> dict:
        return {"strategy_id": self.strategy_id, "kind": self.kind, "eligible": self.eligible,
                "checks": [{"rule": c.rule, "ok": c.ok, "value": c.value, "need": c.need} for c in self.checks]}


def _ro(path: Path):
    if not Path(path).exists():
        return None
    return sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)


def max_drawdown(equities, start: float) -> float:
    """Peak-to-trough fraction; the start capital is the first peak."""
    peak, dd = start, 0.0
    for e in equities:
        peak = max(peak, e)
        if peak > 0:
            dd = max(dd, (peak - e) / peak)
    return dd


def params_hash(params: dict) -> str:
    """Canonical sha256 of a strategy's parameters; a HOLDS row must quote it (F4)."""
    return hashlib.sha256(json.dumps(params, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def coverage(ts_list, bucket_ms: int = 3_600_000):
    """-> (largest gap in hours between consecutive snapshots, fraction of hourly buckets in the span with a snapshot)."""
    ts = sorted(ts_list)
    if len(ts) < 2:
        return 0.0, 0.0
    gap = max(b - a for a, b in zip(ts, ts[1:])) / 3_600_000
    first = ts[0] // bucket_ms
    n = ts[-1] // bucket_ms - first + 1
    return gap, len({t // bucket_ms for t in ts}) / n


def round_trips(fills) -> int:
    """fills: (symbol, side, qty) in time order. A round trip completes when a symbol's position returns to flat."""
    pos, peak, n = {}, {}, 0
    for sym, side, qty in fills:
        q = float(qty or 0)
        if str(side).upper() == "BUY":
            pos[sym] = pos.get(sym, 0.0) + q
            peak[sym] = max(peak.get(sym, 0.0), pos[sym])
        else:
            pos[sym] = pos.get(sym, 0.0) - q
            if pos[sym] <= max(1e-9, 1e-6 * peak.get(sym, 0.0)):
                n += 1
                pos[sym], peak[sym] = 0.0, 0.0
    return n


def redteam_verdicts(log_path: Path) -> dict:
    """strategy_id -> latest verdict (see redteam_registry)."""
    return {k: v[0] for k, v in redteam_registry(log_path).items()}


def redteam_registry(log_path: Path) -> dict:
    """strategy_id -> (latest verdict, params_sha256) from the registry table under REGISTRY_HEADING. Row format:
    | strategy_id | verdict | date | evidence | params_sha256 |   (verdict compared case-sensitively against HOLDS)."""
    try:
        text = Path(log_path).read_text(encoding="utf-8")
    except OSError:
        return {}
    i = text.find(REGISTRY_HEADING)
    if i < 0:
        return {}
    section = text[i + len(REGISTRY_HEADING):]
    j = re.search(r"^## ", section, re.M)
    if j:
        section = section[:j.start()]
    out = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not line.strip().startswith("|") or len(cells) < 3:
            continue
        sid, verdict = cells[0].strip("`"), cells[1].strip("*` ")
        if sid.lower() in ("strategy_id", "strategy") or set(sid) <= set("-: "):
            continue
        out[sid] = (verdict, cells[4].strip("`") if len(cells) > 4 else "")   # later rows override earlier ones
    return out


def luck_check(var: Path, sid: str, now_ms: int):
    """-> (ok, detail). Wrapper so tests can stand in for the (slow to produce) luck report."""
    from ..research import luck
    return luck.verify_report(var, sid, now_ms)


def _evaluate(sid, kind, ts_list, trades, start_cap, last_eq, eqs, verdicts, dd_limit, now_ms, params, var) -> GateResult:
    r = GateResult(sid, kind, params=params)
    t0, t1 = min(ts_list), max(ts_list)
    days = (t1 - t0) / DAY_MS
    r.checks.append(Check("forward_days", days >= MIN_DAYS, round(days, 2), f">= {MIN_DAYS:g}"))
    r.checks.append(Check("closed_trades", trades >= MIN_TRADES, trades, f">= {MIN_TRADES}"))
    net = last_eq - start_cap
    r.checks.append(Check("net_profit_after_fees", net > 0, round(net, 4), "> 0"))
    dd = max_drawdown(eqs, start_cap)
    r.checks.append(Check("max_drawdown", dd <= dd_limit, round(dd, 4), f"<= {dd_limit}"))
    age_h = (now_ms - t1) / 3_600_000
    r.checks.append(Check("record_fresh", age_h <= MAX_STALE_H, round(age_h, 1), f"<= {MAX_STALE_H:g} h"))
    gap, frac = coverage(ts_list)
    r.checks.append(Check("record_coverage", gap <= MAX_GAP_H and frac >= MIN_COVERAGE,
                          f"max gap {gap:.1f} h, {frac:.0%} of hours", f"gap <= {MAX_GAP_H:g} h and >= {MIN_COVERAGE:.0%}"))
    try:
        lok, ldetail = luck_check(var, sid, now_ms)
    except Exception as exc:                                   # fail closed
        lok, ldetail = False, f"luck check error {type(exc).__name__}"
    r.checks.append(Check("luck_tests", bool(lok), ldetail, "all 9 luck-proofing tests pass (research/luck.py)"))
    v, pin = verdicts.get(sid, (None, ""))
    r.checks.append(Check("redteam_holds", v == "HOLDS", v, "latest registry verdict == HOLDS"))
    if v == "HOLDS":
        r.checks.append(Check("params_pinned", pin == params_hash(params), pin[:12] or None,
                              "registry params_sha256 == hash of current parameters"))
    return r


def evaluate_grids(var: Path, verdicts: dict, dd_limit: float, now_ms: int, since: dict | None = None) -> list:
    db = _ro(Path(var) / "shadow_grid.db")
    if db is None:
        return []
    out = []
    try:
        for gid, params in db.execute("SELECT id, params FROM grids ORDER BY id").fetchall():
            p = json.loads(params)
            rows = db.execute("SELECT ts, equity, trips FROM snaps WHERE grid_id=? AND ts>? ORDER BY ts, id",
                              (gid, (since or {}).get(gid, 0))).fetchall()
            if not rows:
                out.append(GateResult(gid, "grid", [Check("forward_days", False, 0, f">= {MIN_DAYS:g}")], p))
                continue
            out.append(_evaluate(gid, "grid", [r[0] for r in rows], int(rows[-1][2] or 0), float(p["invest"]),
                                 rows[-1][1], [r[1] for r in rows], verdicts, dd_limit, now_ms, p, var))
    finally:
        db.close()
    return out


def evaluate_books(var: Path, verdicts: dict, dd_limit: float, now_ms: int, since: dict | None = None) -> list:
    db = _ro(Path(var) / "forward_shadow.db")
    if db is None:
        return []
    out = []
    try:
        for bid, params in db.execute("SELECT id, params FROM books ORDER BY id").fetchall():
            p = json.loads(params)
            rows = db.execute("SELECT ts, equity FROM equity WHERE book=? AND ts>? ORDER BY ts, id",
                              (bid, (since or {}).get(bid, 0))).fetchall()
            if not rows:
                out.append(GateResult(bid, "book", [Check("forward_days", False, 0, f">= {MIN_DAYS:g}")], p))
                continue
            trips = round_trips(db.execute("SELECT symbol, side, qty FROM fills WHERE book=? ORDER BY ts, id",
                                           (bid,)).fetchall())
            out.append(_evaluate(bid, "book", [r[0] for r in rows], trips, float(p["usdt"]), rows[-1][1],
                                 [r[1] for r in rows], verdicts, dd_limit, now_ms, p, var))
    finally:
        db.close()
    return out


def evaluate_all(var: Path, log_path: Path, mandate, now_ms: int | None = None) -> list:
    """All tracked strategies, eligible or not. dd_limit comes from the (hash-checked) mandate object."""
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    dd_limit = float(mandate.get("risk", "peak_drawdown_fraction"))
    verdicts = redteam_registry(log_path)
    since = health.record_start(var)                     # CLO-45: after a stop only the record made since then counts
    out = evaluate_grids(var, verdicts, dd_limit, now_ms, since) + evaluate_books(var, verdicts, dd_limit, now_ms, since)
    for r in out:
        st = health.status_of(var, r.strategy_id)["status"]
        r.checks.append(Check("not_retired", st != "RETIRED", st, "not RETIRED by the strategy-health monitor"))
        if st == "PAUSED" or health.is_stopped(var, r.strategy_id):
            r.checks.append(Check("stop_cleared", False, st, "stop lifted: requalify() after the gate passes on the post-stop record"))
    return out


def requalify(var: Path, results, now_ms: int) -> list:
    """PROGRAM path (executor daily run): a PAUSED strategy whose every OTHER gate check passes on the post-stop record is
    reactivated (stop marker removed, state ACTIVE). Returns the ids reactivated. Never touches RETIRED."""
    out = []
    for r in results:
        if health.status_of(var, r.strategy_id)["status"] != "PAUSED":
            continue
        if all(c.ok for c in r.checks if c.rule != "stop_cleared") and health.reactivate(var, r.strategy_id, now_ms):
            out.append(r.strategy_id)
    return out


def eligible_ids(results) -> set:
    return {r.strategy_id for r in results if r.eligible}


def render(results) -> str:
    lines = []
    for r in results:
        bad = [f"{c.rule}={c.value} (need {c.need})" for c in r.checks if not c.ok]
        lines.append(f"{'ELIGIBLE' if r.eligible else 'not eligible':12s} {r.strategy_id:16s} " + ("; ".join(bad) or "all rules pass"))
    return "\n".join(lines) or "no strategies tracked"
