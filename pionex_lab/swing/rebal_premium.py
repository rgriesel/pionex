"""Rebalancing-premium sleeve: threshold-rebalanced equal-weight basket vs a drifting one (research only: no order path).

PRE-REGISTERED 2026-10-17 03:50 SAST (machine clock), before any result was produced. Issue CLO-28; idea card 1 of
research/ideas/2026-10-17.md (source: Quantpedia, "Estimating Rebalancing Premium in Cryptocurrencies"; no net-of-cost
numbers seen). One parameter set, no grid. Nothing changes after the result; a changed idea is a new test. Backtest on
PROXY data (Binance spot daily klines, `var/alpha/pit_1d.db`, delisted pairs kept). Not proof of profit.

HYPOTHESIS: a long-only equal-weight basket of volatile, imperfectly correlated coins that is pulled back to equal
weight when weights drift out of the 0.75x..1.25x band earns more (log return, net of costs) than the same basket left
to drift on the same days.

UNIVERSES. B (decides): the C2 point-in-time top-10 by trailing-90-day median quote volume, re-ranked monthly
(pit.load_series + pit.rank_universe, same exclusions, TOP=10), delisted coins included; decision days 2018-01-01 ..
2026-09-30 (pit.START; last data month is 2026-09). A (context only, never gates): the ten v1.1 coins (cta.UNIVERSE)
from pit_1d.db, equal weight over those that have bars on the day, same window.

SLEEVES (all fully invested long-only spot, no signal, target weight 1/N over the day's members; each is simulated on
the same days):
  DRIFT       no rebalance. Only membership changes trade: coins that left the set (monthly re-rank, or bars ended) are
              sold, the proceeds are split equally over entrants (pro rata over the remaining holdings if there are none).
  MONTHLY     DRIFT rules plus a full rebalance to equal weight on the first UTC day of each month (the re-rank day).
  THRESHOLD   (the tested sleeve) DRIFT rules plus a full rebalance to equal weight (a) on the first UTC day of each month
              and (b) whenever any holding's weight, measured at yesterday's close, is above 1.25x or below 0.75x of
              the 1/N target.
Timing: the decision uses weights at the previous close; trades are filled at the next 00:00 UTC open; between close and
open holdings drift with the overnight gap, from open to close with the day's move. A new member needs a bar today.
A held coin whose bars have ended is sold at its last close, on the first day after its last bar (costed like a normal
sale); in the haircut stress run it first loses 50% of its value. A coin with a missing bar inside a gap of <= 7 days
carries zero return that day (pit.py gap rule).
COSTS: per side per unit of traded notional, pit.cost_map (cta.COST for the ten v1.1 coins; SIDE + half of an assumed
10 bps spread = 12 bps for the rest); stress = 4x. No Pionex spread was measured for the others.

SERIES RUN ONCE: B: DRIFT, MONTHLY, THRESHOLD at 1x costs; DRIFT and THRESHOLD at 4x costs; DRIFT and THRESHOLD with the 50%
haircut (1x costs). A: DRIFT, MONTHLY, THRESHOLD at 1x costs (context). Daily NAV simple return r; paired daily log
difference d_t = ln(1+r_THRESHOLD) - ln(1+r_DRIFT) on the same days.

KILL CRITERION (exactly the card's; Universe B at 1x costs unless stated). The verdict is FAIL if ANY holds:
  K1 bootstrap lower bound of mean(d) <= 0 (overlays.paired_block_bootstrap on the two daily log-return series: 10-day
     circular blocks, 20,000 resamples, seed 20261014, the 2.5% quantile = one-sided alpha 0.05 over 2 tests as in the
     lab's other tests);
  K2 mean(d) > 0 in fewer than 2 of the 3 equal thirds of the days;
  K3 mean(d) <= 0 at 4x costs (THRESHOLD 4x minus DRIFT 4x);
  K4 "comes from one year": after removing the calendar year with the largest sum of d, the mean of d over the other days
     is <= 0.
PASS only if none holds and the sample is not short (INSUFFICIENT if Universe B has fewer than 1,500 decision days).
REPORTED, not gating: CAGR, max drawdown, Sharpe, average turnover per year and rebalance count for every sleeve; mean d
per year; the THRESHOLD-vs-MONTHLY difference with the same bootstrap; the haircut run's mean d; the Universe A results.
A PASS means "worth a Red Team review"; it is long-only beta (hold-all PIT drawdown was 82-90%), not deployable.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone

from . import cta, pit
from .cta import DAY
from .overlays import paired_block_bootstrap

LOW, HIGH = 0.75, 1.25
HAIRCUT = 0.5
MIN_DAYS = 1500
SLEEVES = ("drift", "monthly", "threshold")


def _first_of_month(t):
    return datetime.fromtimestamp(t / 1000, timezone.utc).day == 1


def simulate(series, members, sleeve, cost, start, end, haircut=0.0):
    """Daily rows (t, r, exposure, turnover) of one sleeve and the count of rebalances. `series` = {coin: {"t","o","c"}},
    `members(t)` = set of names the universe allows on day t, `cost` = {coin: per-side cost}."""
    px = {n: dict(zip(s["t"], zip(s["o"], s["c"]))) for n, s in series.items()}
    last = {n: s["t"][-1] for n, s in series.items()}
    held, lastc, cash = {}, {}, 1.0
    nav_prev, out, rebalances = 1.0, [], 0
    for t in range(start, end + DAY, DAY):
        for n in held:                                            # overnight drift close(t-1) -> open(t)
            if t in px[n]:
                held[n] *= px[n][t][0] / lastc[n]
                lastc[n] = px[n][t][0]
            if t > last[n] and haircut:
                held[n] *= 1 - haircut
        equity = sum(held.values()) + cash
        target = {n for n in members(t) if t <= last[n] and (n in held or t in px[n])}
        w = {n: v / equity for n, v in held.items()}
        trig = False
        if sleeve != "drift" and held:
            if _first_of_month(t):
                trig = True
            elif sleeve == "threshold":
                k = 1.0 / len(w)
                trig = any(x > HIGH * k or x < LOW * k for x in w.values())
        if target and (trig or not held):
            new = {n: equity / len(target) for n in target}
            rebalances += 1 if held else 0
        else:
            keep = {n: v for n, v in held.items() if n in target}
            freed = equity - cash - sum(keep.values())
            entrants = sorted(target - set(keep))
            if entrants:
                new = dict(keep)
                for n in entrants:
                    new[n] = (freed + cash) / len(entrants) if not keep else freed / len(entrants)
            elif keep:
                tot = sum(keep.values())
                new = {n: v * (tot + freed) / tot for n, v in keep.items()}
            else:
                new = {}
        names = set(held) | set(new)
        traded = sum(abs(new.get(n, 0.0) - held.get(n, 0.0)) for n in names)
        fee = sum(abs(new.get(n, 0.0) - held.get(n, 0.0)) * cost.get(n, 0.0012) for n in names)
        if new:
            scale = (equity - fee) / equity
            held, cash = {n: v * scale for n, v in new.items()}, 0.0
        else:
            held, cash = {}, equity - fee
        for n in held:                                            # open -> close
            if t in px[n]:
                held[n] *= px[n][t][1] / px[n][t][0]
                lastc[n] = px[n][t][1]
            else:
                lastc.setdefault(n, 1.0)
        nav = sum(held.values()) + cash
        out.append((t, nav / nav_prev - 1.0, 1.0 if held else 0.0, traded / equity))
        nav_prev = nav
    return out, rebalances


def _members_b(sets):
    f = pit.universe_fn(sets)
    return f


def _members_a(series, names):
    first = {n: series[n]["t"][0] for n in names}

    def f(t):
        return {n for n in names if first[n] <= t}
    return f


def _stats(rows, reb):
    s = cta.stats([(t, r, e, to) for t, r, e, to in rows])
    s["rebalances"] = reb
    return s


def _log(rows):
    return [math.log(1 + r[1]) for r in rows]


def _thirds(d):
    k = len(d) // 3
    return [sum(x) / len(x) for x in (d[:k], d[k:2 * k], d[2 * k:])]


def _by_year(rows, d):
    ys = {}
    for r, x in zip(rows, d):
        ys.setdefault(datetime.fromtimestamp(r[0] / 1000, timezone.utc).year, []).append(x)
    return {y: sum(v) / len(v) for y, v in sorted(ys.items())}


def compare(rows_a, rows_b, label):
    a, b = _log(rows_a), _log(rows_b)
    d = [x - y for x, y in zip(a, b)]
    boot = paired_block_bootstrap(a, b)
    ys = {}
    for r, x in zip(rows_a, d):
        ys.setdefault(datetime.fromtimestamp(r[0] / 1000, timezone.utc).year, []).append(x)
    best = max(ys, key=lambda y: sum(ys[y]))
    rest = [x for y, v in ys.items() if y != best for x in v]
    return {"label": label, "mean_daily_log_diff": sum(d) / len(d), "annualised": sum(d) / len(d) * 365.25,
            "bootstrap_mean_diff": boot["mean_diff"], "thirds_mean": _thirds(d), "per_year_mean": _by_year(rows_a, d),
            "best_year": best, "mean_ex_best_year": sum(rest) / len(rest) if rest else None, "days": len(d)}


def evaluate(series, sets10, a_names=None):
    names = sorted({n for v in sets10.values() for n in v})
    sub = {n: series[n] for n in names}
    c1, c4 = pit.cost_map(names), pit.cost_map(names, 4.0)
    end = pit._ms(2026, 9, 30)
    mb = _members_b(sets10)
    runs = {}
    for sl in SLEEVES:
        runs[sl] = simulate(sub, mb, sl, c1, pit.START, end)
    for sl in ("drift", "threshold"):
        runs[sl + "_4x"] = simulate(sub, mb, sl, c4, pit.START, end)
        runs[sl + "_haircut"] = simulate(sub, mb, sl, c1, pit.START, end, haircut=HAIRCUT)
    rep = {"universe_B": {k: _stats(*v) for k, v in runs.items()}}
    main = compare(runs["threshold"][0], runs["drift"][0], "threshold - drift, 1x costs")
    x4 = compare(runs["threshold_4x"][0], runs["drift_4x"][0], "threshold - drift, 4x costs")
    hc = compare(runs["threshold_haircut"][0], runs["drift_haircut"][0], "threshold - drift, 50% haircut")
    mo = compare(runs["threshold"][0], runs["monthly"][0], "threshold - monthly, 1x costs")
    mo_d = compare(runs["monthly"][0], runs["drift"][0], "monthly - drift, 1x costs")
    kill = {"K1_bootstrap_lower_bound_le_0": main["bootstrap_mean_diff"]["lower"] <= 0,
            "K2_positive_in_fewer_than_2_of_3_thirds": sum(x > 0 for x in main["thirds_mean"]) < 2,
            "K3_negative_at_4x_costs": x4["mean_daily_log_diff"] <= 0,
            "K4_one_year_only": main["mean_ex_best_year"] is None or main["mean_ex_best_year"] <= 0}
    rep["comparisons_B"] = {"main": main, "x4": x4, "haircut": hc, "threshold_vs_monthly": mo, "monthly_vs_drift": mo_d}
    rep["kill"] = kill
    rep["max_drawdown_B"] = {k: rep["universe_B"][k]["max_drawdown"] for k in ("drift", "monthly", "threshold")}
    if main["days"] < MIN_DAYS:
        rep["verdict"] = "INSUFFICIENT"
    else:
        rep["verdict"] = "FAIL" if any(kill.values()) else "PASS"
    # context: Universe A
    fixed = [n for n in cta.UNIVERSE if n in series]
    suba = {n: series[n] for n in fixed}
    ma = _members_a(series, fixed)
    ca = pit.cost_map(fixed)
    ra = {sl: simulate(suba, ma, sl, ca, pit.START, end) for sl in SLEEVES}
    rep["universe_A_context"] = {"series": {k: _stats(*v) for k, v in ra.items()},
                                 "threshold_minus_drift": compare(ra["threshold"][0], ra["drift"][0], "A threshold - drift"),
                                 "monthly_minus_drift": compare(ra["monthly"][0], ra["drift"][0], "A monthly - drift")}
    return rep


def run(paths, write=True):
    series = pit.load_series(paths.root / "alpha" / "pit_1d.db")
    rep = {"preregistered": "see the module docstring (pionex_lab/swing/rebal_premium.py)",
           "venue": "PROXY: Binance spot daily klines incl. delisted pairs, not Pionex",
           "status": "backtest; long-only beta; not proof of profit; red team pending on a PASS"}
    rep.update(evaluate(series, pit.rank_universe(series, pit.TOP)))
    if write:
        (paths.reports / "rebal_premium.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return rep
