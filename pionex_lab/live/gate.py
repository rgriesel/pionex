"""Forward-proof gate (CLO-43 part A). Deterministic: decides from the databases, never from a statement.

A strategy is ELIGIBLE for live trading only if ALL hold (thresholds below are code constants; the drawdown
limit comes from the hash-locked mandate, risk.peak_drawdown_fraction):

  1. forward record on live Pionex prices spans >= MIN_DAYS (30) days (first to last snapshot)
  2. >= MIN_TRADES (20) closed trades: grid round trips (var/shadow_grid.db snaps.trips) or sell fills of a
     CTA book (var/forward_shadow.db fills)
  3. net profit after Pionex fees > 0 (equity already includes the 0.05%/side fees the runners charge)
  4. max drawdown of the forward equity curve <= mandate peak_drawdown_fraction (peak includes the start capital)
  5. the record is fresh: the last snapshot is <= MAX_STALE_H (48) hours old, so a dead runner cannot qualify
  6. docs/STRATEGY_LOG.md has a Red Team registry row for the strategy whose LATEST verdict is exactly HOLDS
     (a later row with any other verdict revokes it)

Read-only: databases are opened with mode=ro. Unknown strategy ids are never eligible. No order code here.
Residual trust: row 6 is a text table an agent can edit; the executor therefore also needs the owner's
mandate (LIVE + authorization record), the owner-written var/live.json pin of the mandate hash, and the
owner's key file. The gate is necessary, not sufficient.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

MIN_DAYS = 30.0
MIN_TRADES = 20
MAX_STALE_H = 48.0
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


def redteam_verdicts(log_path: Path) -> dict:
    """strategy_id -> latest verdict from the registry table under REGISTRY_HEADING. Row format:
    | strategy_id | verdict | date | evidence |   (verdict compared case-sensitively against HOLDS)."""
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
        out[sid] = verdict           # later rows override earlier ones
    return out


def _evaluate(sid, kind, t0, t1, trades, start_cap, last_eq, eqs, verdicts, dd_limit, now_ms, params) -> GateResult:
    r = GateResult(sid, kind, params=params)
    days = (t1 - t0) / DAY_MS
    r.checks.append(Check("forward_days", days >= MIN_DAYS, round(days, 2), f">= {MIN_DAYS:g}"))
    r.checks.append(Check("closed_trades", trades >= MIN_TRADES, trades, f">= {MIN_TRADES}"))
    net = last_eq - start_cap
    r.checks.append(Check("net_profit_after_fees", net > 0, round(net, 4), "> 0"))
    dd = max_drawdown(eqs, start_cap)
    r.checks.append(Check("max_drawdown", dd <= dd_limit, round(dd, 4), f"<= {dd_limit}"))
    age_h = (now_ms - t1) / 3_600_000
    r.checks.append(Check("record_fresh", age_h <= MAX_STALE_H, round(age_h, 1), f"<= {MAX_STALE_H:g} h"))
    v = verdicts.get(sid)
    r.checks.append(Check("redteam_holds", v == "HOLDS", v, "latest registry verdict == HOLDS"))
    return r


def evaluate_grids(var: Path, verdicts: dict, dd_limit: float, now_ms: int) -> list:
    db = _ro(Path(var) / "shadow_grid.db")
    if db is None:
        return []
    out = []
    try:
        for gid, params in db.execute("SELECT id, params FROM grids ORDER BY id").fetchall():
            p = json.loads(params)
            rows = db.execute("SELECT ts, equity, trips FROM snaps WHERE grid_id=? ORDER BY ts, id", (gid,)).fetchall()
            if not rows:
                out.append(GateResult(gid, "grid", [Check("forward_days", False, 0, f">= {MIN_DAYS:g}")], p))
                continue
            out.append(_evaluate(gid, "grid", rows[0][0], rows[-1][0], int(rows[-1][2] or 0), float(p["invest"]),
                                 rows[-1][1], [r[1] for r in rows], verdicts, dd_limit, now_ms, p))
    finally:
        db.close()
    return out


def evaluate_books(var: Path, verdicts: dict, dd_limit: float, now_ms: int) -> list:
    db = _ro(Path(var) / "forward_shadow.db")
    if db is None:
        return []
    out = []
    try:
        for bid, params in db.execute("SELECT id, params FROM books ORDER BY id").fetchall():
            p = json.loads(params)
            rows = db.execute("SELECT ts, equity FROM equity WHERE book=? ORDER BY ts, id", (bid,)).fetchall()
            if not rows:
                out.append(GateResult(bid, "book", [Check("forward_days", False, 0, f">= {MIN_DAYS:g}")], p))
                continue
            sells = db.execute("SELECT COUNT(*) FROM fills WHERE book=? AND side IN ('SELL','sell','Sell')",
                               (bid,)).fetchone()[0]
            out.append(_evaluate(bid, "book", rows[0][0], rows[-1][0], int(sells), float(p["usdt"]), rows[-1][1],
                                 [r[1] for r in rows], verdicts, dd_limit, now_ms, p))
    finally:
        db.close()
    return out


def evaluate_all(var: Path, log_path: Path, mandate, now_ms: int | None = None) -> list:
    """All tracked strategies, eligible or not. dd_limit comes from the (hash-checked) mandate object."""
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    dd_limit = float(mandate.get("risk", "peak_drawdown_fraction"))
    verdicts = redteam_verdicts(log_path)
    return evaluate_grids(var, verdicts, dd_limit, now_ms) + evaluate_books(var, verdicts, dd_limit, now_ms)


def eligible_ids(results) -> set:
    return {r.strategy_id for r in results if r.eligible}


def render(results) -> str:
    lines = []
    for r in results:
        bad = [f"{c.rule}={c.value} (need {c.need})" for c in r.checks if not c.ok]
        lines.append(f"{'ELIGIBLE' if r.eligible else 'not eligible':12s} {r.strategy_id:16s} " + ("; ".join(bad) or "all rules pass"))
    return "\n".join(lines) or "no strategies tracked"
