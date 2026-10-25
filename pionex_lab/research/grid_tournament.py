"""CLO-129: offline tournament policy for the existing shadow-grid ledger.

Research only. No exchange, account, scheduler, order or live-gate access. This
module prepares audit reports and proposals; it does not run or retire bots.
The forward experiment awaits CLO-128 owner configurations and CLO-37 futures
funding/liquidation accounting. Never substitute leveraged spot returns.
"""
from __future__ import annotations

import math
import sqlite3
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

from ..live.shadow_grid import Config
from ..swing.grid import FEE, MIN_GRID_USDT, step_pct

DAY = 86_400_000
WEEK = 7 * DAY
MAX_GAP = 120_000
LABEL = "SIMULATED research audit; not profit or live eligibility"


def initial_configs():
    """PRE-REGISTERED 2026-10-25 18:37 SAST, before tests or performance reads.

    Fixed spot pilot: BTC_USDT and ETH_USDT; start-centred geometric bands
    +/- {4,8,16}%; rows {20,40,80}; 1,000 simulated USDT each, unleveraged.
    Reuse shadow_grid start, strict trade crossings, 5 bp/side fees and
    bottom*0.97 stop. Count all 18 configurations, including rejected ones,
    before any forward start. No historical replay or re-test of CLO-21/63.
    Owner copies await CLO-128's exact pair/product/direction/band/rows/leverage,
    cost and source identifiers; futures await CLO-37. They need a separate
    timestamped registration before their first observation, never backfill.

    Weekly ranking and neighbour proposals are frozen in evaluate_cohort below.
    Qualification PASS is unavailable: this is infrastructure, not an edge
    test. Forward verdict remains INSUFFICIENT until a board-confirmed
    qualification protocol and the firm's unchanged luck/Red Team/risk gates.
    Synthetic unit tests validate accounting/policy only, not performance.
    """
    return [Config(f"clo129_{sym}_{int(band*100)}_{rows}_g0", sym, band, rows)
            for sym in ("BTC_USDT", "ETH_USDT")
            for band in (0.04, 0.08, 0.16) for rows in (20, 40, 80)]


def _admissible(cfg):
    return (cfg.invest / cfg.rows >= MIN_GRID_USDT and
            step_pct(1-cfg.band, 1+cfg.band, cfg.rows) >= 3 * 2 * FEE)


def _net_value(row):
    # Snapshot equity already includes all paid entry/grid/stop fees. Reserve
    # only the outstanding exit fee plus 5 bp market slippage on residual base.
    return row["equity"] - row["base"] * row["price"] * (FEE + 0.0005)


def evaluate_cohort(db_path, configs, start_ms, now_ms, generation=0):
    """PRE-REGISTERED 2026-10-25 18:37 SAST before any evaluation.

    Offline audit, never a trading decision or an automatic launch. One fixed
    seven-day generation: only supplied immutable configs started in the first
    120 seconds of start_ms. Use ledger rows at or before the seven-day end;
    never peek later. Require an initial mark <=120s after start, a final mark
    <=120s before end and no inter-mark gap >120s, including stopped grids.
    Any tape gap event, changed config, missing/nonfinite/negative balances,
    malformed ledger or insufficient age makes the WHOLE cohort INSUFFICIENT;
    no survivor-only ranking or proposals. Read ledger mode=ro; never repair it.

    Rank descending (final equity minus remaining exit fee/slippage)/initial
    investment - 1, inclusive of inventory losses, with id as tie breaker.
    Record maximum observed liquidation-value drawdown from initial capital
    (sampled, not intratick). Recommend retirement if net return <=0 or observed
    drawdown >35%; preserve every loser in the table. Remaining top TWO may
    propose four one-axis neighbours: band x0.75/x1.25 and rows -10/+10.
    Bounds band [0.02,0.20], rows [10,100], minimum 10 USDT/grid, step >=3x
    round-trip fee. Cap at generation 4; no leverage, capital compounding or
    retroactive variants. New proposals need registration BEFORE first prices,
    fresh Pionex quotes/rules at launch, and a new common seven-day cohort.
    Reports cannot trigger actions: logs are audit evidence only.

    These are descriptive selection rules, NOT profitability pass thresholds.
    Always verdict INSUFFICIENT, pass=false, live_eligible=false. No statistical
    inference from one week, no annualised return or Sharpe. Formal evaluation
    must pre-register untouched forward periods, benchmark, costs/stress,
    bootstrap and all firm-wide multiple-testing gates before it starts.
    """
    if (not configs or len({c.id for c in configs}) != len(configs) or
            not isinstance(generation, int) or not 0 <= generation <= 4):
        raise ValueError("need unique configs and generation 0..4")
    for c in configs:
        if (not math.isfinite(c.invest) or c.invest <= 0 or not math.isfinite(c.band)
                or not 0 < c.band < 1 or not isinstance(c.rows, int) or c.rows < 2
                or c.grid_type not in ("geometric", "arithmetic")):
            raise ValueError("invalid frozen grid config")
    end = start_ms + WEEK
    out = {"label": LABEL, "start_ms": start_ms, "end_ms": end,
           "generation": generation, "verdict": "INSUFFICIENT", "pass": False,
           "live_eligible": False, "ranking": [], "retire_proposals": [],
           "variant_proposals": [], "errors": []}
    if now_ms < end:
        out["errors"].append("seven-day cohort is not mature")
        return out
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as db:
            db.row_factory = sqlite3.Row
            for cfg in configs:
                out["ranking"].append(_audit_grid(db, cfg, start_ms, end))
    except (sqlite3.Error, ValueError, TypeError, KeyError, OverflowError) as exc:
        out["errors"].append(f"cohort unavailable: {exc}")
        out["ranking"] = []
        return out
    out["ranking"].sort(key=lambda r: (-r["net_return"], r["id"]))
    out["retire_proposals"] = [r["id"] for r in out["ranking"]
                               if r["net_return"] <= 0 or r["max_observed_dd"] > 0.35]
    out["cohort_complete"] = True
    if generation < 4:
        by_id = {c.id: c for c in configs}
        winners = [r for r in out["ranking"] if r["id"] not in out["retire_proposals"]][:2]
        for win in winners:
            c = by_id[win["id"]]
            for k, (band, rows) in enumerate(((c.band*0.75, c.rows), (c.band*1.25, c.rows),
                                              (c.band, c.rows-10), (c.band, c.rows+10))):
                if not (0.02 <= band <= 0.20 and 10 <= rows <= 100):
                    continue
                v = Config(f"{c.id}_g{generation+1}n{k}", c.symbol, band, rows, c.invest, c.grid_type)
                if _admissible(v):
                    out["variant_proposals"].append({"parent": c.id, **asdict(v)})
    return out


def _audit_grid(db, cfg, start, end):
    import json
    stored = db.execute("SELECT params,created_ts FROM grids WHERE id=?", (cfg.id,)).fetchone()
    if stored is None or not start <= stored["created_ts"] <= start + MAX_GAP:
        raise ValueError(f"{cfg.id}: missing or different cohort start")
    p = json.loads(stored["params"])
    if not isinstance(p, dict):
        raise ValueError(f"{cfg.id}: malformed frozen parameters")
    for key, value in (("symbol", cfg.symbol), ("band", cfg.band), ("rows", cfg.rows),
                       ("invest", cfg.invest), ("type", cfg.grid_type)):
        if p.get(key) != value:
            raise ValueError(f"{cfg.id}: frozen parameter mismatch: {key}")
    if db.execute("SELECT 1 FROM events WHERE grid_id=? AND kind='gap' AND ts BETWEEN ? AND ? LIMIT 1",
                  (cfg.id, start, end)).fetchone():
        raise ValueError(f"{cfg.id}: tape gap invalidates ranking")
    snaps = db.execute("SELECT ts,price,equity,base,cash,fills,trips,status FROM snaps "
                       "WHERE grid_id=? AND ts BETWEEN ? AND ? ORDER BY ts,id", (cfg.id, start, end)).fetchall()
    if not snaps or snaps[0]["ts"] > start + MAX_GAP or snaps[-1]["ts"] < end - MAX_GAP:
        raise ValueError(f"{cfg.id}: incomplete observation window")
    peak, dd, prev = cfg.invest, 0.0, start
    for s in snaps:
        if s["ts"] - prev > MAX_GAP:
            raise ValueError(f"{cfg.id}: snapshot gap")
        if (any(not math.isfinite(s[k]) or s[k] < -1e-8 for k in ("price", "equity", "base", "cash"))
                or s["price"] <= 0 or s["status"] not in ("running", "stopped")
                or not math.isclose(s["equity"], s["cash"]+s["base"]*s["price"], abs_tol=1e-6)):
            raise ValueError(f"{cfg.id}: invalid or unreconciled snapshot")
        eq = _net_value(s)
        peak = max(peak, eq)
        dd = max(dd, 1 - eq/peak)
        prev = s["ts"]
    last = snaps[-1]
    net = _net_value(last)
    return {"id": cfg.id, "symbol": cfg.symbol, "net_equity": net,
            "net_return": net/cfg.invest - 1, "max_observed_dd": dd,
            "fills": last["fills"], "round_trips": last["trips"], "status": last["status"]}
