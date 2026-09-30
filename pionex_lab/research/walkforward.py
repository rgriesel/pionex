"""Walk-forward qualification cycle (references/research.md "Evidence gates").

Protocol, fixed before looking at results:
* Chronological only. The first 75% of the common history is development data,
  split into four chunks -> three expanding (rolling-origin) folds: train on
  chunks [0..f), validate on chunk f. The last 25% is an untouched test window
  evaluated once with parameters chosen on the full development window.
* Purge: trades not completed inside their window are dropped. Embargo: every
  validation/test window starts max_hold_bars after its training boundary.
* Search budget from the mandate: <= 5 hypotheses and <= 20 parameter sets each;
  one research cycle per UTC day. Every trial is written to the registry.
* The bootstrap confidence level is Bonferroni-adjusted by the number of
  configurations searched in the cycle.
"""
from __future__ import annotations

import bisect
import hashlib
import inspect
import uuid

from ..data.quality import check_bars
from ..strategies import catalog, indicators
from ..util import utc_day
from . import backtest, metrics
from .backtest import BASE, STRESS, CostModel, simulate_universe

FIVE_MIN_MS = 300_000
MIN_TRAIN_TRADES = 20
MAX_MISSING_FRACTION = 0.001
MAX_GAP_BARS = 6


class DailyBudgetSpent(RuntimeError):
    """One research cycle (<= 5 hypotheses) per UTC day, across all timeframes."""


def code_hash() -> str:
    h = hashlib.sha256()
    for mod in (catalog, indicators, backtest, metrics):
        h.update(inspect.getsource(mod).encode("utf-8"))
    h.update(inspect.getsource(inspect.getmodule(code_hash)).encode("utf-8"))
    return h.hexdigest()


def data_hash(universe: dict) -> str:
    h = hashlib.sha256()
    for sym in sorted(universe):
        for bars in universe[sym]:
            h.update(f"{sym}|{bars.interval}|{len(bars)}|".encode())
            h.update(",".join(f"{t}:{c!r}" for t, c in zip(bars.t, bars.c)).encode())
    return h.hexdigest()


def data_quality(universe: dict) -> dict:
    out, ok = {}, True
    for sym, (b5, b60) in universe.items():
        for bars in (b5, b60):
            q = check_bars(bars)
            s = q.summary()
            s["max_gap_bars"] = max((n for _, n in q.gaps), default=0)
            frac = q.missing_bars / max(1, q.count + q.missing_bars)
            s["missing_fraction"] = frac
            s["ok"] = bool(q.count) and not q.invalid and q.non_monotonic == 0 and frac <= MAX_MISSING_FRACTION \
                and s["max_gap_bars"] <= MAX_GAP_BARS
            ok &= s["ok"]
            out[f"{sym}:{bars.interval}"] = s
    return {"ok": ok, "series": out}


def _windows(universe, t_start, t_end):
    out = {}
    for sym, (b5, _) in universe.items():
        a, b = bisect.bisect_left(b5.t, t_start), bisect.bisect_left(b5.t, t_end)
        if b > a:
            out[sym] = (a, b)
    return out


def _gate(passed, value, threshold, note=""):
    return {"pass": bool(passed), "value": value, "threshold": threshold, "note": note}


def run_cycle(universe: dict, registry, mandate, cost: CostModel, now_ms: int, strategy_names=None,
              enforce_daily_limit: bool = True, note: str = "", timeframe: str = "5m",
              data_source: dict | None = None) -> list:
    q = mandate.qualification
    names = list(strategy_names or catalog.STRATEGIES)
    if len(names) > int(q["max_hypotheses_per_cycle"]):
        raise ValueError("search budget: too many hypotheses in one cycle")
    classes = [catalog.ALL[n] for n in names]
    if len({c.base_interval for c in classes}) != 1:
        raise ValueError("one research cycle must use a single base timeframe")
    base_ms = catalog.INTERVAL_MS[classes[0].base_interval]
    for cls in classes:
        if len(cls.grid) > int(q["max_parameter_trials_per_hypothesis"]):
            raise ValueError(f"search budget: {cls.name} grid exceeds trials limit")
    if enforce_daily_limit and registry.cycles_on(utc_day(now_ms)):
        raise DailyBudgetSpent("a research cycle already ran this UTC day; the daily search budget is spent")
    configs = sum(len(c.grid) for c in classes)
    alpha = 0.05 / max(1, configs)
    symbols = sorted(universe)
    dq = data_quality(universe)
    dhash, chash = data_hash(universe), code_hash()
    cycle_id = "cyc-" + uuid.uuid4().hex[:12]
    registry.start_cycle(cycle_id, now_ms, len(classes), configs,
                         {"alpha": alpha, "folds": 3, "test_fraction": 0.25, "block_days": 3},
                         {"symbols": symbols, "data_hash": dhash, "quality_ok": dq["ok"], "timeframe": timeframe,
                          "base_interval": classes[0].base_interval,
                          "context_interval": classes[0].context_interval,
                          "data_source": data_source or {"venue": "Pionex public API"}}, note)
    warm = max(c.warmup for c in classes)
    starts = [u[0].t[warm] for u in universe.values() if len(u[0]) > warm]
    ends = [u[0].t[-1] + base_ms for u in universe.values() if len(u[0])]
    results = []
    if len(starts) != len(universe) or not ends:
        t0 = t1 = 0
    else:
        t0, t1 = max(starts), min(ends)
    span_days = max(0, t1 - t0) / 86_400_000
    for cls in classes:
        results.append(_evaluate(cls, universe, symbols, t0, t1, span_days, registry, cycle_id, cost, q, alpha,
                                 dq, dhash, chash, now_ms))
    registry.finish_cycle(cycle_id, now_ms)
    return results


def _evaluate(cls, universe, symbols, t0, t1, span_days, registry, cycle_id, cost, q, alpha, dq, dhash, chash, now):
    version = cls.version
    if span_days < 10:
        gates = {"data_span": _gate(False, round(span_days, 2), ">= 10 days before any evaluation")}
        registry.add_candidate(cycle_id, cls.name, version, None, "INSUFFICIENT_DATA", gates,
                               {"data_quality": dq}, 0.0, dhash, chash, now)
        return {"strategy": cls.name, "status": "INSUFFICIENT_DATA", "gates": gates}
    embargo = cls.max_hold_bars * catalog.INTERVAL_MS[cls.base_interval]
    dev_end = t0 + (t1 - t0) * 3 // 4
    chunk = (dev_end - t0) // 4
    bounds = [t0 + k * chunk for k in range(4)] + [dev_end]
    prep = cls().prepare(universe)
    instances = [cls(p) for p in cls.grid]

    def select(train_windows, label):
        best, best_s = None, None
        for inst in instances:
            s = metrics.summarize(simulate_universe(inst, prep, symbols, train_windows, cost)["trades"])
            registry.add_trial(cycle_id, cls.name, inst.params, label, s, now)
            if s["n"] >= MIN_TRAIN_TRADES and (best_s is None or s["expectancy_bps"] > best_s["expectancy_bps"]):
                best, best_s = inst, s
        return best

    oos, oos_stress, fold_totals, fold_notes = [], [], [], []
    for f in range(1, 4):
        chosen = select(_windows(universe, bounds[0], bounds[f]), f"fold{f}:train")
        if chosen is None:
            fold_totals.append(0.0)
            fold_notes.append(f"fold{f}: no parameter set had >= {MIN_TRAIN_TRADES} train trades")
            continue
        vw = _windows(universe, bounds[f] + embargo, bounds[f + 1])
        val = simulate_universe(chosen, prep, symbols, vw, cost)["trades"]
        oos += val
        oos_stress += simulate_universe(chosen, prep, symbols, vw, cost.scaled(q["cost_stress_multiplier"]),
                                        STRESS)["trades"]
        fold_totals.append(sum(t["net_bps"] for t in val))
        fold_notes.append(f"fold{f}: params {chosen.params}, {len(val)} trades")
    final = select(_windows(universe, t0, dev_end), "final:train")
    tw = _windows(universe, dev_end + embargo, t1)
    test, sensitivity = [], {}
    if final is not None:
        test = simulate_universe(final, prep, symbols, tw, cost)["trades"]
        oos_stress += simulate_universe(final, prep, symbols, tw, cost.scaled(q["cost_stress_multiplier"]),
                                        STRESS)["trades"]
        for inst in instances:  # nearby-parameter sensitivity on the test window (reported, not selected)
            s = metrics.summarize(simulate_universe(inst, prep, symbols, tw, cost)["trades"])
            sensitivity[repr(inst.params)] = {"n": s["n"], "expectancy_bps": s["expectancy_bps"]}
    oos_all = oos + test
    net = metrics.summarize(oos_all)
    gross = metrics.summarize(oos_all, "gross_bps")
    stress = metrics.summarize(oos_stress)
    lower_net = metrics.block_bootstrap_lower(oos_all, alpha)
    lower_gross = metrics.block_bootstrap_lower(oos_all, alpha, key="gross_bps")
    pos, nfolds = metrics.fold_positive(fold_totals)
    exp_ = net["expectancy_bps"]
    gates = {
        "data_quality": _gate(dq["ok"], dq["ok"], f"missing <= {MAX_MISSING_FRACTION:.1%}, gaps <= {MAX_GAP_BARS} bars"),
        "walk_forward_folds": _gate(nfolds >= int(q["min_walk_forward_folds"]), nfolds, q["min_walk_forward_folds"]),
        "min_oos_trades": _gate(net["n"] >= int(q["min_oos_trades"]), net["n"], q["min_oos_trades"]),
        "min_oos_days": _gate(net["span_days"] >= float(q["min_oos_days"]), round(net["span_days"], 1), q["min_oos_days"]),
        "positive_expectancy": _gate(exp_ is not None and exp_ > 0, exp_, "> 0 bps"),
        "profit_factor": _gate(net["profit_factor"] is not None and net["profit_factor"] >= float(q["min_net_profit_factor"]),
                               net["profit_factor"], q["min_net_profit_factor"], net.get("profit_factor_note") or ""),
        "fold_consistency": _gate(pos >= 2, f"{pos}/{nfolds}", ">= 2 of 3 validation folds positive"),
        "bootstrap_lower_bound": _gate(lower_net is not None and lower_net > 0, lower_net,
                                       f"> 0 at one-sided alpha {alpha:.5f} (Bonferroni over {len(cls.grid)}+ configs)"),
        "cost_stress": _gate(stress["n"] > 0 and stress["total_bps"] > 0, stress["total_bps"],
                             f"> 0 with {q['cost_stress_multiplier']}x costs, +1 bar delay, 20% missed fills, +10 bps stop slip"),
        "without_best_trade": _gate(net["n"] > 0 and net["total_minus_best_bps"] >= 0, net["total_minus_best_bps"], ">= 0"),
    }
    failed = [k for k, g in gates.items() if not g["pass"]]
    sample_only = set(failed) <= {"min_oos_trades", "min_oos_days"} and failed
    status = "QUALIFIED_FOR_PAPER" if not failed else "INSUFFICIENT_DATA" if sample_only else "REJECTED"
    edge = max(0.0, lower_gross) if lower_gross is not None else 0.0
    m = {"oos_net": net, "oos_gross": gross, "oos_stress": stress, "fold_totals_bps": fold_totals,
         "fold_notes": fold_notes, "test_trades": len(test), "concentration": metrics.concentration(oos_all),
         "sensitivity_test_window": sensitivity, "bootstrap_lower_net_bps": lower_net,
         "bootstrap_lower_gross_bps": lower_gross, "windows": {"t0": t0, "dev_end": dev_end, "t1": t1},
         "data_quality": dq, "cost_model": cost.__dict__, "roundtrip_cost_bps": cost.roundtrip_bps}
    registry.add_candidate(cycle_id, cls.name, version, final.params if final else None, status, gates, m, edge,
                           dhash, chash, now)
    return {"strategy": cls.name, "status": status, "params": final.params if final else None,
            "failed_gates": failed, "oos_trades": net["n"], "expectancy_bps": exp_, "edge_lower_gross_bps": edge}
