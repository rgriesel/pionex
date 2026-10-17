"""Strategy health (CLO-45, "adapt or die"): compare each live/shadow strategy's realised record with its own design and
STOP what has left it. MONITOR path: stop-only power. It reads the forward databases read-only, writes only
var/LIVE_STOP_<strategy_id> (a stop marker the executor honours) and var/strategy_state.json (the program's own
state), and notifies the owner. It never opens, changes or sizes a position and never clears a stop.

FROZEN 2026-10-17 18:10 SAST (machine clock), before any run or backtest:
  Daily returns: last equity snapshot of each COMPLETED UTC day, return = eq_d / eq_{d-1} - 1 (the day-0 base is the start
  capital). The current day is never used.
  Design range per strategy (DESIGN below = the pre-registered backtest numbers in docs/STRATEGY_LOG.md; strategies
  without a backtest, e.g. grids, use the DEFAULT range: no positive expectation assumed, mu = 0, max drawdown = the
  mandate's peak_drawdown_fraction, sigma = the record's own first BURN_IN days):
      mu_daily    from CAGR:   ln(1+CAGR) / 365.25
      sigma_daily from Sharpe: mu_daily * sqrt(365.25) / Sharpe   (floored at MIN_SIGMA)
  DRIFT if ANY of:
    (1) CUSUM (one-sided, losses): z_d = clip((r_d - mu)/sigma, -ZCLIP, ZCLIP); S = max(0, S - z_d - K); alarm when
        S >= H, evaluated only once >= MIN_DAYS_CUSUM completed days exist. K=0.5, H=5, ZCLIP=3 (one wild day can add at
        most 2.5, so it takes at least two bad days and ten days of record; a single noisy week cannot trip it alone
        unless it is a 3-sigma-per-day week).
    (2) drawdown: peak-to-trough of the forward equity curve (start capital is the first peak) > design max drawdown.
    (3) slippage (books): mean signed cost of fills versus the quote mid at the decision, over >= MIN_FILLS fills,
        exceeds design max_slip_bps (15).
  Not evaluated (and reported as such): win rate and hold time. Trend books have a low and strongly regime-dependent
  daily win rate, grids have no hold time; no backtest range exists to compare them with, so any threshold would be a guess.
Response (code, not agents): DRIFT -> write var/LIVE_STOP_<id>, set state PAUSED (second DRIFT after a re-qualification
within RETIRE_WINDOW_DAYS (180) of the first -> RETIRED, permanent), notify the owner (important, once per day per strategy). The allocator may only shift capital among
strategies currently ELIGIBLE per the gate; a PAUSED strategy is eligible again only if the gate passes on the record
made AFTER the stop (gate.py reads `since`), a RETIRED one never (new id, new test).
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

DAY_MS = 86_400_000
K, H, ZCLIP = 0.5, 5.0, 3.0
MIN_DAYS_CUSUM = 10
BURN_IN = 14
MIN_SIGMA = 0.002
MIN_FILLS = 5
RETIRE_WINDOW_DAYS = 180
STATUSES = ("ACTIVE", "PAUSED", "RETIRED")


@dataclass(frozen=True)
class Design:
    mu: float                     # expected daily return
    sigma: float | None           # expected daily sd; None = estimate from the first BURN_IN days
    max_dd: float | None          # None = mandate peak_drawdown_fraction
    max_slip_bps: float = 15.0


def design_from(cagr: float, sharpe: float, max_dd: float) -> Design:
    mu = math.log(1 + cagr) / 365.25
    return Design(mu, max(mu * math.sqrt(365.25) / sharpe, MIN_SIGMA), max_dd)


# CAGR / Sharpe / max drawdown of the pre-registered backtests (docs/STRATEGY_LOG.md, PROXY data).
DESIGN = {
    "defensive": design_from(0.358, 1.37, 0.263),
    "growth": design_from(0.684, 1.26, 0.55),
    "canary": design_from(0.327, 1.15, 0.33),
    "donchian_c1": design_from(0.223, 1.36, 0.205),
}
DEFAULT = Design(0.0, None, None)


# ------------------------------------------------------------------ pure statistics
def daily_returns(points, start_cap, now_ms):
    """points: (ts_ms, equity) in time order -> daily returns of completed UTC days."""
    today = now_ms // DAY_MS
    last = {}
    for ts, eq in points:
        d = ts // DAY_MS
        if d < today:
            last[d] = eq
    out, prev = [], start_cap
    for d in sorted(last):
        out.append(last[d] / prev - 1 if prev else 0.0)
        prev = last[d]
    return out


def cusum_loss(rets, mu, sigma, min_days=MIN_DAYS_CUSUM):
    """-> (alarm, statistic). Downward CUSUM of standardised, clipped daily returns."""
    s = 0.0
    for r in rets:
        z = max(-ZCLIP, min(ZCLIP, (r - mu) / sigma))
        s = max(0.0, s - z - K)
    return (len(rets) >= min_days and s >= H), s


def max_drawdown(points, start_cap):
    peak, dd = start_cap, 0.0
    for _, eq in points:
        peak = max(peak, eq)
        if peak > 0:
            dd = max(dd, (peak - eq) / peak)
    return dd


def judge(sid, points, start_cap, now_ms, dd_limit, fills_bps=(), design=None) -> dict:
    """-> {strategy_id, drift, reasons, ...}. Pure: no I/O."""
    d = design or DESIGN.get(sid, DEFAULT)
    rets = daily_returns(points, start_cap, now_ms)
    sigma = d.sigma
    if sigma is None:
        base = rets[:BURN_IN]
        sd = math.sqrt(sum((x - sum(base) / len(base)) ** 2 for x in base) / len(base)) if len(base) >= 2 else 0.0
        sigma = max(sd, MIN_SIGMA)
        rets = rets[BURN_IN:]                      # the burn-in defines "normal", it is not tested against itself
    alarm, s = cusum_loss(rets, d.mu, sigma)
    dd = max_drawdown(points, start_cap)
    lim = d.max_dd if d.max_dd is not None else dd_limit
    reasons = []
    if alarm:
        reasons.append(f"CUSUM {s:.1f} >= {H:g} over {len(rets)} days (mu {d.mu:.5f}, sigma {sigma:.5f})")
    if dd > lim:
        reasons.append(f"drawdown {dd:.1%} > design {lim:.1%}")
    if len(fills_bps) >= MIN_FILLS and sum(fills_bps) / len(fills_bps) > d.max_slip_bps:
        reasons.append(f"slippage {sum(fills_bps) / len(fills_bps):.1f} bps > {d.max_slip_bps:g}")
    return {"strategy_id": sid, "drift": bool(reasons), "reasons": reasons, "days": len(rets), "cusum": round(s, 3),
            "drawdown": round(dd, 4), "n_fills": len(fills_bps)}


# ------------------------------------------------------------------ state + stop (the only writes)
def state_path(var):
    return Path(var) / "strategy_state.json"


def load_state(var) -> dict:
    try:
        return json.loads(state_path(var).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def status_of(var, sid) -> dict:
    return load_state(var).get(sid, {"status": "ACTIVE", "since_ms": 0, "stops": 0})


def _atomic(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1), encoding="utf-8")
    tmp.replace(path)


def stop_strategy(var, sid, reasons, now_ms) -> dict:
    """Write the stop marker and mark the strategy PAUSED (RETIRED on a repeat). Stop-only: never removes anything."""
    var = Path(var)
    if not re.fullmatch(r"[\w.-]{1,64}", str(sid)):
        raise ValueError(f"bad strategy id {sid!r}")
    st = load_state(var)
    cur = st.get(sid, {"status": "ACTIVE", "since_ms": 0, "stops": 0})
    if cur["status"] == "RETIRED":
        return cur
    recent = cur.get("stops", 0) and now_ms - cur.get("since_ms", 0) <= RETIRE_WINDOW_DAYS * DAY_MS
    stops = (cur.get("stops", 0) + 1) if recent else 1
    new = {"status": "RETIRED" if stops >= 2 else "PAUSED", "since_ms": now_ms, "from_ms": now_ms, "stops": stops,
           "reasons": reasons}
    st[sid] = new
    _atomic(state_path(var), st)
    _atomic(var / f"LIVE_STOP_{sid}", {"strategy_id": sid, "at_ms": now_ms, "reasons": reasons, "by": "health.py"})
    return new


def record_start(var) -> dict:
    """{strategy_id: ms}: only the forward record made after its last stop counts, for the gate and for this monitor."""
    return {sid: v["from_ms"] for sid, v in load_state(var).items() if v.get("from_ms")}


def reactivate(var, sid, now_ms) -> bool:
    """PROGRAM path only (called by the gate/executor after the gate passed on the post-stop record; never by the monitor
    loop): PAUSED -> ACTIVE and remove the stop marker. A RETIRED strategy can never be reactivated."""
    st = load_state(var)
    cur = st.get(sid)
    if not cur or cur.get("status") != "PAUSED":
        return False
    st[sid] = dict(cur, status="ACTIVE", reactivated_ms=now_ms)
    _atomic(state_path(var), st)
    try:
        (Path(var) / f"LIVE_STOP_{sid}").unlink()
    except OSError:
        pass
    return True


def is_stopped(var, sid) -> bool:
    if not re.fullmatch(r"[\w.-]{1,64}", str(sid)):         # an id is never a path
        return True                                          # fail closed
    return (Path(var) / f"LIVE_STOP_{sid}").exists()


# ------------------------------------------------------------------ read the forward databases (read-only)
def _ro(path):
    p = Path(path)
    return sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True) if p.exists() else None


def collect(var, since: dict | None = None):
    """-> list of (sid, kind, points, start_cap, fills_bps). `since` = {sid: ms}: only the record after the stop counts."""
    since = since or {}
    out = []
    db = _ro(Path(var) / "shadow_grid.db")
    if db:
        try:
            for gid, params in db.execute("SELECT id, params FROM grids ORDER BY id").fetchall():
                rows = db.execute("SELECT ts, equity FROM snaps WHERE grid_id=? AND ts>? ORDER BY ts, id",
                                  (gid, since.get(gid, 0))).fetchall()
                out.append((gid, "grid", rows, float(json.loads(params)["invest"]), []))
        finally:
            db.close()
    db = _ro(Path(var) / "forward_shadow.db")
    if db:
        try:
            for bid, params in db.execute("SELECT id, params FROM books ORDER BY id").fetchall():
                rows = db.execute("SELECT ts, equity FROM equity WHERE book=? AND ts>? ORDER BY ts, id",
                                  (bid, since.get(bid, 0))).fetchall()
                bps = []
                for side, price, bid_, ask in db.execute(
                        "SELECT f.side, f.price, q.bid, q.ask FROM fills f JOIN quotes q ON q.book=f.book AND q.day=f.day "
                        "AND q.symbol=f.symbol AND q.purpose=(SELECT purpose FROM quotes WHERE book=f.book AND day=f.day "
                        "AND symbol=f.symbol ORDER BY id LIMIT 1) WHERE f.book=? AND f.ts>?", (bid, since.get(bid, 0))):
                    mid = (float(bid_) + float(ask)) / 2
                    if mid > 0:
                        bps.append((1 if str(side).upper() == "BUY" else -1) * (float(price) - mid) / mid * 1e4)
                out.append((bid, "book", rows, float(json.loads(params)["usdt"]), bps))
        finally:
            db.close()
    return out


def watch(var, dd_limit: float, now_ms=None, notify=None) -> list:
    """Hourly strategy-health pass. Judges every ACTIVE strategy on its whole record, a PAUSED one only on the record
    made after its stop (it cannot be on the allocator anyway until the gate says so). Stops the drifted."""
    var = Path(var)
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    st = load_state(var)
    since = record_start(var)
    results = []
    for sid, kind, pts, cap, bps in collect(var, since):
        s = st.get(sid, {}).get("status", "ACTIVE")
        if s == "RETIRED" or not pts:
            continue
        res = judge(sid, pts, cap, now_ms, dd_limit, bps)
        res["status_before"] = s
        if res["drift"]:
            new = stop_strategy(var, sid, res["reasons"], now_ms)
            res["status_after"] = new["status"]
            if notify:
                notify(f"DRIFT: {sid} left its design ({'; '.join(res['reasons'])[:200]}). Stopped; now {new['status']}. "
                       "It returns only by passing the gate again.", "important", f"drift-{sid}")
        results.append(res)
    return results


# Regime shrink factors for the allocator. EMPTY on purpose: the pre-registered backtest of the regime shrink
# (swing/adapt_test.py rule A, 2026-10-17) FAILED against the same-exposure control, so no regime scaling ships.
# Only a later PASS + Red Team may fill this table (and each factor may only cut, never add exposure).
REGIME_SCALE: dict = {}


def regime_scale(label: str) -> float:
    return min(1.0, max(0.0, REGIME_SCALE.get(label, 1.0)))


# ------------------------------------------------------------------ allocator (shrink/shift among ELIGIBLE only)
def allocate(eligible_ids, capital: float, var, scale: float = 1.0) -> dict:
    """Equal split of `capital * scale` among strategies that are eligible AND ACTIVE AND not stopped. scale in [0,1]
    (a regime shrink; cannot add leverage). Anything not eligible gets nothing, whatever the caller passes."""
    if not 0.0 <= scale <= 1.0:
        raise ValueError("scale must be in [0, 1]")
    ok = sorted(s for s in eligible_ids if status_of(var, s)["status"] == "ACTIVE" and not is_stopped(var, s))
    return {s: capital * scale / len(ok) for s in ok} if ok else {}
