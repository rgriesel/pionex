"""Export the dashboard report (schema v1, references/dashboard.md) from the ledger.

Everything shown is derived from the canonical journal, the risk service state,
the research registry, and the market store. Nothing is interpolated or invented:
missing data stays missing. Monetary values are USD using the journaled FX
evidence (currently an explicitly labeled 1 USDT = 1 USD assumption).
"""
from __future__ import annotations

import math
import re
from decimal import Decimal
from pathlib import Path

from ..execution.live import live_preflight
from ..ledger.journal import Journal
from ..research import metrics
from ..research.registry import Registry
from ..strategies import catalog
from ..util import iso_ms, parse_iso_ms

MAX_SNAPSHOTS = 2000
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$")


def _f(x, nd=6):
    if x is None:
        return None
    v = round(float(Decimal(str(x))), nd)
    return v if math.isfinite(v) else None


def _downsample(rows: list, limit: int) -> list:
    if len(rows) <= limit:
        return rows
    step = (len(rows) - 1) / (limit - 1)
    idx = sorted({int(round(k * step)) for k in range(limit)} | {len(rows) - 1})
    return [rows[i] for i in idx]


def paired_comparison(baseline: dict, challenger: dict, alpha: float = 0.05) -> dict:
    """Matched forward comparison on identical opportunities (shadow outcomes keyed by
    opportunity id). Returns mean challenger-minus-baseline delta with a block
    bootstrap interval; status IMPROVING only with a positive lower bound."""
    common = sorted(set(baseline) & set(challenger))
    if not common:
        return {"status": "UNPROVEN", "paired_observations": 0, "mean_delta_usd": None, "ci95_low_usd": None,
                "ci95_high_usd": None}
    rows = [{"exit_time": challenger[k]["t"], "entry_time": challenger[k]["t"],
             "delta": challenger[k]["pnl"] - baseline[k]["pnl"]} for k in common]
    mean = sum(r["delta"] for r in rows) / len(rows)
    lo = metrics.block_bootstrap_lower(rows, alpha / 2, key="delta")
    neg = [{**r, "delta": -r["delta"]} for r in rows]
    hi_neg = metrics.block_bootstrap_lower(neg, alpha / 2, key="delta")
    hi = -hi_neg if hi_neg is not None else None
    if lo is None or hi is None:
        status = "UNPROVEN"
    elif lo > 0:
        status = "IMPROVING"
    elif hi < 0:
        status = "DECLINING"
    else:
        status = "NO_IMPROVEMENT"
    return {"status": status, "paired_observations": len(rows), "mean_delta_usd": mean,
            "ci95_low_usd": min(lo, mean) if lo is not None else None,
            "ci95_high_usd": max(hi, mean) if hi is not None else None}


def paper_evidence(closed: list, now: int) -> dict:
    """Closed paper episodes by frozen QUALIFIED candidates and hours since the first one opened
    (the 72h AND 50-trade paper gate). Episodes of unqualified strategies do not count."""
    q = [p for p in closed if p.get("qualification") == "QUALIFIED_FOR_PAPER"]
    if not q:
        return {"paper_trades_qualified": 0, "paper_hours_qualified": 0.0}
    first = min(parse_iso_ms(p["opened_at"]) for p in q)
    return {"paper_trades_qualified": len(q), "paper_hours_qualified": max(0.0, (now - first) / 3_600_000)}


READINESS_ORDER = ("NOT_QUALIFIED", "PAPER_TRIAL_NOT_PROFITABLE", "PAPER_TRIAL", "BLOCKED_BY_REVIEW_LATCH",
                   "READY_FOR_REVIEW")


def strategy_readiness(cands: dict, closed: list, now: int, mandate, risk=None) -> dict:
    """How far each strategy is from 'ready for the user's live review'.

    READY_FOR_REVIEW needs a research-qualified frozen candidate, the mandate's paper sample
    (hours AND closed trades) by that candidate, positive net paper P&L, and no review latches.
    It prompts a human decision; it never authorizes anything. Live orders stay impossible in
    this build regardless of this status (see execution/live.py)."""
    q = mandate.qualification
    need_n, need_h = int(q["min_paper_trades"]), float(q["min_paper_hours"])
    review = sorted(n for n, r in risk.active_latches().items() if r["kind"] == "REVIEW") if risk is not None else []
    rows = []
    for name, cls in catalog.ALL.items():
        c = cands.get(f"{name}/{cls.version}")
        row = {"strategy": name, "stage": "NOT_QUALIFIED", "paper_trades": 0, "paper_hours": 0.0,
               "paper_net_usd": 0.0}
        if not c or c["status"] != "QUALIFIED_FOR_PAPER":
            row["detail"] = f"Latest research: {c['status'] if c else 'not researched yet'}."
        else:
            mine = [p for p in closed if p.get("strategy_name") == name and p.get("version") == cls.version
                    and p.get("qualification") == "QUALIFIED_FOR_PAPER"]
            n = len(mine)
            hours = max(0.0, (now - min(parse_iso_ms(p["opened_at"]) for p in mine)) / 3_600_000) if mine else 0.0
            net = sum((Decimal(p["net_pnl_usd"]) for p in mine), Decimal(0))
            row.update(paper_trades=n, paper_hours=round(hours, 1), paper_net_usd=_f(net) or 0.0)
            sample = f"{n}/{need_n} closed paper trades, {hours:.1f}/{need_h:.0f} hours, net {float(net):+.2f} USD (simulated)"
            if n < need_n or hours < need_h:
                row["stage"], row["detail"] = "PAPER_TRIAL", f"Passed research; paper trial in progress: {sample}."
            elif net <= 0:
                row["stage"], row["detail"] = "PAPER_TRIAL_NOT_PROFITABLE", f"Paper sample complete but not profitable: {sample}."
            elif review:
                row["stage"], row["detail"] = "BLOCKED_BY_REVIEW_LATCH", f"{sample}; active review latches: {', '.join(review)}."
            else:
                row["stage"], row["detail"] = "READY_FOR_REVIEW", f"Paper sample complete and net positive: {sample}."
        rows.append(row)
    best = max((r["stage"] for r in rows), key=READINESS_ORDER.index)
    names = [r["strategy"] for r in rows if r["stage"] == best]
    headline = {
        "READY_FOR_REVIEW": f"Ready for your review: {', '.join(names)}. Simulated paper results are not evidence of "
                            "future profit, and live orders remain impossible until the live path is authorized and built.",
        "BLOCKED_BY_REVIEW_LATCH": f"{', '.join(names)} completed a profitable paper sample, but a review latch is active.",
        "PAPER_TRIAL": f"In paper trial: {', '.join(names)}. Not ready yet.",
        "PAPER_TRIAL_NOT_PROFITABLE": f"{', '.join(names)} completed the paper sample without a net profit. Not ready.",
        "NOT_QUALIFIED": "No strategy has passed research after costs. The lab stays in cash (NO_TRADE).",
    }[best]
    return {"stage": best, "headline": headline, "strategies": rows,
            "rule": (f"Ready means: passed research gates, then at least {need_h:.0f} hours AND {need_n} closed paper "
                     "trades with the frozen candidate, net positive after simulated costs, and no review latches.")}


def build_report(paths, mandate, now: int, journal=None, market=None, risk=None, registry=None,
                 universe=("BTC_USDT", "ETH_USDT")) -> dict:
    own = []
    if journal is None:
        journal = Journal(paths.ledger, readonly=True)
        own.append(journal)
    if registry is None and Path(paths.research).exists():
        registry = Registry(paths.research, readonly=True)
        own.append(registry.conn)
    try:
        return _build(paths, mandate, now, journal, market, risk, registry, list(universe))
    finally:
        for o in own:
            o.close()


def _build(paths, mandate, now, journal, market, risk, registry, universe) -> dict:
    started = journal.last("EXPERIMENT_STARTED")
    state_row = journal.last("STATE_TRANSITION")
    state = state_row[2]["to"] if state_row else "SETUP"
    engine_status, engine_at = journal.get_status("engine")
    recon, _ = journal.get_status("reconciliation")
    snapshots, closed, shadows, incidents, decisions = [], [], [], [], {"approved": 0, "rejected": {}}
    preview_sources = {}
    for _, at, kind, p in journal.events(("SNAPSHOT", "POSITION_CLOSED", "SHADOW_CLOSE", "INCIDENT",
                                          "RISK_DECISION", "ORDER_INTENT")):
        if kind == "SNAPSHOT":
            snapshots.append((at, p))
        elif kind == "POSITION_CLOSED":
            closed.append((at, p))
        elif kind == "SHADOW_CLOSE":
            shadows.append((at, p))
        elif kind == "INCIDENT":
            incidents.append((at, p))
        elif kind == "RISK_DECISION":
            if p.get("approved"):
                decisions["approved"] += 1
            else:
                key = str(p.get("reason", "")).split(":")[0]
                decisions["rejected"][key] = decisions["rejected"].get(key, 0) + 1
        elif kind == "ORDER_INTENT":
            src = p.get("dry_run_request", {}).get("preview_source", "unknown")
            preview_sources[src] = preview_sources.get(src, 0) + 1

    initial = float(mandate.initial_capital)
    start_ms = int(started[2]["start_ms"]) if started else now
    exp = {"start_at": iso_ms(start_ms), "duration_days": mandate.duration_days, "initial_capital_usd": initial,
           "target_profit_usd": float(mandate.raw["experiment"]["target_net_profit"])}
    official = bool(started and started[2].get("official_data_source"))
    source = started[2].get("data_source") if started else None

    snap_rows, econ = [], []
    for at, p in snapshots:
        if at < start_ms or at > now:
            continue
        econ.append(float(Decimal(p["economic_value_usd"])))
        snap_rows.append({"at": iso_ms(at), "equity_usd": _f(p["equity_usd"]), "net_cashflow_usd": 0.0,
                          "cumulative_operating_cost_usd": _f(p["cumulative_operating_cost_usd"]),
                          "btc_benchmark_usd": _f(p.get("btc_benchmark_usd")), "human_equity_usd": None})
    peak, dd = initial, 0.0
    for v in econ:  # authoritative drawdown at full snapshot resolution
        peak = max(peak, v)
        dd = max(dd, (peak - v) / peak * 100)

    trades = [{"id": p["id"], "closed_at": iso_ms(at), "symbol": p["symbol"], "strategy": p["strategy"],
               "net_pnl_usd": _f(p["net_pnl_usd"]), "fees_usd": _f(p["fees_usd"]),
               "slippage_usd": _f(p["slippage_usd"]), "exit_reason": p["exit_reason"][:200]}
              for at, p in closed if start_ms <= at <= now]

    cands = registry.latest_candidates() if registry is not None else {}
    strategies = []
    for name, cls in catalog.ALL.items():
        key = f"{name}/{cls.version}"
        c = cands.get(key)
        mine = [p for _, p in closed if p.get("strategy_name") == name]
        sh = [float(Decimal(p["net_bps"])) for _, p in shadows if p["strategy"] == name]
        if c:
            failed = [g for g, v in c["gates"].items() if not v["pass"]]
            evidence = (f"Research {c['status']}; OOS trades {c['metrics'].get('oos_net', {}).get('n', 0)}; "
                        f"failed gates: {', '.join(failed) or 'none'}; registry edge {c['edge_lower_gross_bps'] or 0:.1f} bps.")
        else:
            evidence = "No research cycle on collected data yet; edge unknown, so the risk gate rejects entries."
        evidence += (f" Shadow (virtual, identical fills): {len(sh)} closed, mean {sum(sh) / len(sh):.1f} bps net."
                     if sh else " Shadow: no closed virtual trades yet.")
        params = c["params"] if c and c.get("params") else cls.grid[0]
        strategies.append({
            "name": (name[:-3].replace("_", " ").capitalize() + " (1h)" if name.endswith("_1h")
                     else name.replace("_", " ").capitalize() + " (5m)"),
            "version": f"{cls.version} · {params}"[:200],
            "state": ("PAPER · " + (c["status"] if c else "UNREGISTERED"))[:200],
            "closed_trades": len(mine),
            "net_pnl_usd": _f(sum((Decimal(p["net_pnl_usd"]) for p in mine), Decimal(0))) or 0.0,
            "change_note": "Frozen v1 baseline; no learned changes. Challenger versions require a matched forward test.",
            "evidence": evidence[:1000]})

    latches = risk.active_latches() if risk is not None else {}
    feed_ages = []
    coll, coll_at = (market.status("collector") if market is not None else (None, None))
    if market is not None:
        for sym in universe:
            b = market.latest_book(sym)
            if b:
                feed_ages.append((now - b["fetched_at"]) / 1000)
    open_pos = []
    exposure = 0.0
    if snapshots:
        last = snapshots[-1][1]
        marks = {k: Decimal(v) for k, v in last.get("marks", {}).items()}
        for pos in last.get("positions", []):
            open_pos.append(pos)
            exposure += float(Decimal(pos["qty"]) * marks.get(pos["symbol"], Decimal(0)))
    engine_age = (now - engine_at) / 1000 if engine_at else None
    reasons = []
    if engine_age is None:
        reasons.append("Paper engine has not run yet.")
    elif engine_age > 30:
        reasons.append(f"Paper engine heartbeat is {engine_age:.0f}s old — runtime may be stopped.")
    if not started:
        reasons.append("Experiment clock not started: waiting for fresh market data and complete bar history.")
    if latches:
        reasons.append("Entry latches: " + ", ".join(sorted(latches)) + ".")
    if engine_status and engine_status.get("reasons"):
        reasons.append("Feed: " + "; ".join(engine_status["reasons"][:4]) + ".")
    reasons.append("Simulated fills on later observed quotes; order requests are Pionex dry-run previews (never sent).")

    gates = live_preflight(mandate, registry=registry, risk=risk,
                           **paper_evidence([p for _, p in closed], now))
    report = {
        "schema_version": 1, "mode": "PAPER",
        "source_label": ("Canonical paper ledger · simulated fills on observed Pionex public quotes" if official else
                         f"Canonical paper ledger · TEST FEED {source or 'none'} — not Pionex market data"
                         if started else "Canonical paper ledger · no market data received yet")[:1000],
        "generated_at": iso_ms(now), "experiment": exp, "snapshots": _downsample(snap_rows, MAX_SNAPSHOTS),
        "trades": trades[-10000:], "strategies": strategies,
        "learning": {"status": "UNPROVEN", "paired_observations": 0, "mean_delta_usd": None, "ci95_low_usd": None,
                     "ci95_high_usd": None,
                     "method": "No challenger registered. All strategies are frozen v1 baselines; shadow books record "
                               "every signal on identical fills for future matched forward comparisons."},
        "operations": {"state": (state + (" · ENTRIES LATCHED" if latches else ""))[:1000],
                       "open_positions": len(open_pos), "gross_exposure_usd": round(exposure, 6),
                       "feed_age_seconds": round(max(feed_ages), 1) if feed_ages else None,
                       "reconciled": bool(recon and recon.get("ok")),
                       "protection": "NONE (paper) — local monitor exits at observed quotes; no exchange-side stops",
                       "reason": " ".join(reasons)[:1000]},
        "human_comparison": {"comparable": False, "note": "No dated human ledger supplied; comparison unavailable."},
        # Optional extensions (ignored by the original template, rendered by dashboard/index.html)
        "live_gates": gates,
        "readiness": strategy_readiness(cands, [p for _, p in closed], now, mandate, risk),
        "risk_state": {
            "authoritative_max_drawdown_pct": round(dd, 4) if econ else None,
            "snapshots_total": len(econ), "latches": sorted(latches),
            "floors_usd": risk.state_summary()["floors"] if risk is not None else None,
            "policy_hash": mandate.sha256, "live_enabled": mandate.live_enabled},
        "runtime": {"engine_heartbeat_age_s": round(engine_age, 1) if engine_age is not None else None,
                    "collector_heartbeat_age_s": round((now - coll_at) / 1000, 1) if coll_at else None,
                    "collector_errors": coll.get("errors") if coll else None,
                    "collector_last_error": coll.get("last_error") if coll else None,
                    "data_source": source, "official_data_source": official,
                    "fx": started[2]["fx_source"] if started else None,
                    "order_previews": preview_sources, "risk_decisions": decisions,
                    "incidents": len(incidents), "journal_rows": journal.count(),
                    "end_at": started[2]["end_at"] if started else None},
    }
    return validate_report(report)


class ReportInvalid(ValueError):
    pass


def validate_report(r: dict) -> dict:
    """Python port of the template's validate() (assets/dashboard.html)."""
    def fail(m):
        raise ReportInvalid(m)

    def num(v, n, lo=-1e12, hi=1e12):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < lo or v > hi:
            fail(f"{n} must be a finite number in range")

    def text(v, n):
        if not isinstance(v, str) or len(v) > 1000:
            fail(f"{n} must be text (up to 1,000 characters)")

    def date(v, n):
        if not isinstance(v, str) or not ISO_RE.match(v):
            fail(f"{n} must include an ISO timestamp and timezone")
        try:
            return parse_iso_ms(v)
        except ValueError:
            fail(f"{n} invalid")

    if r.get("schema_version") != 1:
        fail("Unsupported report version")
    if r.get("mode") not in ("LIVE", "PAPER", "BACKTEST", "DEMO"):
        fail("bad mode")
    text(r["source_label"], "Source")
    gen = date(r["generated_at"], "Generated time")
    e = r["experiment"]
    start = date(e["start_at"], "Start")
    num(e["duration_days"], "Duration", 1, 365)
    num(e["initial_capital_usd"], "Initial capital", .01, 1e9)
    num(e["target_profit_usd"], "Target", .01, 1e9)
    if gen < start:
        fail("Generated time precedes experiment start")
    for k, lim in (("snapshots", 5000), ("trades", 10000), ("strategies", 100)):
        if not isinstance(r[k], list) or len(r[k]) > lim:
            fail(f"{k} must be an array with at most {lim} records")
    last, op = start - 1, 0.0
    for s in r["snapshots"]:
        at = date(s["at"], "Snapshot time")
        if at <= last or at < start or at > gen:
            fail("Snapshots must be unique, chronological, and within the report window")
        last = at
        num(s["equity_usd"], "equity_usd", 0)
        num(s["cumulative_operating_cost_usd"], "cumulative_operating_cost_usd", 0)
        num(s["net_cashflow_usd"], "Net cash flow")
        if s["cumulative_operating_cost_usd"] < op:
            fail("Cumulative operating cost cannot decrease")
        op = s["cumulative_operating_cost_usd"]
        for k in ("btc_benchmark_usd", "human_equity_usd"):
            if s.get(k) is not None:
                num(s[k], k, 0)
    ids = set()
    for t in r["trades"]:
        for k in ("id", "symbol", "strategy", "exit_reason"):
            text(t[k], k)
        if not t["id"] or t["id"] in ids:
            fail("Trade IDs must be nonempty and unique")
        ids.add(t["id"])
        at = date(t["closed_at"], "Trade close")
        if at < start or at > gen:
            fail("Trade close is outside the report window")
        num(t["net_pnl_usd"], "net_pnl_usd")
        num(t["slippage_usd"], "slippage_usd")
        num(t["fees_usd"], "Trade fees", 0)
    for s in r["strategies"]:
        for k in ("name", "version", "state", "change_note", "evidence"):
            text(s[k], k)
        if not isinstance(s["closed_trades"], int) or s["closed_trades"] < 0:
            fail("Strategy trade count must be an integer")
        num(s["net_pnl_usd"], "Strategy P&L")
    lr = r["learning"]
    if lr["status"] not in ("UNPROVEN", "IMPROVING", "NO_IMPROVEMENT", "DECLINING"):
        fail("Unknown learning status")
    vals = [lr["mean_delta_usd"], lr["ci95_low_usd"], lr["ci95_high_usd"]]
    if any(v is not None for v in vals) and not all(v is not None for v in vals):
        fail("Learning estimate and interval must be supplied together")
    if lr["status"] == "IMPROVING" and not (all(v is not None for v in vals) and lr["ci95_low_usd"] > 0
                                             and lr["paired_observations"] > 0):
        fail("Improvement needs paired evidence and a positive lower confidence bound")
    o = r["operations"]
    for k in ("state", "protection", "reason"):
        text(o[k], k)
    num(o["open_positions"], "open_positions", 0)
    num(o["gross_exposure_usd"], "gross_exposure_usd", 0)
    if not isinstance(o["reconciled"], bool):
        fail("Reconciled must be true or false")
    if not isinstance(r["human_comparison"]["comparable"], bool):
        fail("Comparable must be true or false")
    text(r["human_comparison"]["note"], "Human note")
    rd = r.get("readiness")
    if rd is not None:
        if rd.get("stage") not in READINESS_ORDER or not isinstance(rd.get("strategies"), list) \
                or len(rd["strategies"]) > 100:
            fail("readiness must carry a known stage and a short strategy list")
        text(rd["headline"], "Readiness headline")
        text(rd["rule"], "Readiness rule")
        for s in rd["strategies"]:
            if s.get("stage") not in READINESS_ORDER:
                fail("Unknown readiness stage")
            text(s["strategy"], "Readiness strategy")
            text(s["detail"], "Readiness detail")
    return r
