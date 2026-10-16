"""C3 (issue CLO-4): gold-token (PAXG) trend sleeve for idle cash on CTA basket v1.1 (research only: no order path).

PRE-REGISTERED 2026-10-16 19:05 SAST (machine clock), before the test was run (nothing below changes after a result;
a changed idea is a new test). Spec: research/edge_candidates_2026-10-14.md section C3; the board confirmed the
[proposed] gates as written on 2026-10-14 23:15 SAST. Not previously tested (checked docs/STRATEGY_LOG.md). Status: PROXY
data (Binance spot daily klines, PAXGUSDT from 2020-08-28); not proof of profit.

HYPOTHESIS: v1.1 holds 27% of NAV on average, so 73% idles. A gold-token trend sleeve run by the same machinery is a
low-correlation use of that cash.

RULE: v1.1 with PAXG_USDT as an 11th coin in cta.simulate: tsmom_vote (2 of the 20/60/120-day returns > 0 at yesterday's
close), vol sizing (target/N)/vol30 per coin, 100% gross cap, 2% band, decisions on yesterday's close, fills at the 00:00
UTC open. Per-coin risk budget unchanged: target = 0.44 with N = 11, so target/N = 4% as in v1.1 (0.40/10). PAXG joins
after 120 bars of history like every coin. Single parameter set, no grid.
COSTS: 5 bps fee + 2 bps slippage per side + half the measured Pionex spread. PAXG_USDT spread measured read-only
2026-10-16 (public bookTickers, 5 samples, ask-bid 0.01/0.02/0.01/0.01/0.01 USDT on ~4159): mean 0.03 bps, i.e. 0.0 at
the 0.1 bp resolution of cta.SPREAD_BPS, so PAXG costs 7 bps a side like BTC and ETH (frozen). Min order 10 USDT.

WINDOW: from PAXG's first decision day (the day after its 120th bar) to the last day on which all 11 coins have a bar
(trim() cuts longer series to it; found before any result, PAXG had one more daily bar than the other ten, which would
have added one extra interval to the basket only). Control and test are run on
exactly these days (start_ms filter on the full-history simulations; same day list asserted).
CONTROL: v1.1 as is (10 coins, target 0.40, measured costs) on the same days.
REGRESSION CHECK first: full-window v1.1 must reproduce CAGR 35.8% / max DD 26.3% / Sharpe 1.37, else VOID.

GATES (all five must hold; the 4x-cost run must meet gates 1-5 again):
  1. Sharpe of the 11-coin basket > the control's.
  2. Max drawdown not worse than the control's by more than 1 percentage point.
  3. Sharpe higher than the control's in at least 2 of the 3 equal thirds (cta.stats thirds).
  4. Paired circular block bootstrap (overlays: 10-day blocks, 20,000 resamples, seed 20261014) lower bound (q = 0.025)
     of mean(daily return, basket - control) >= -10% of the control's mean daily return.
  5. Correlation of the PAXG sleeve with v1.1 below 0.4: Pearson r between the PAXG daily contribution to the basket
     (weight x open-to-open return, from the cta.simulate trace, before costs, in the 11-coin run; interval starting
     day t0 matched to trace day t0 + 1 day, missing = 0) and the control's daily net return, over the window days.
VERDICT: INSUFFICIENT if PAXG has fewer than 3 trend episodes (runs of decision days with PAXG's vote IN, merged when
separated by fewer than 7 OUT days); else PASS if all gates hold at 1x and at 4x costs; else FAIL. On PASS the CEO sends
it to the Red Team.
REPORTED, not gating: CAGR, exposure, turnover, PAXG buy-and-hold (Sharpe, CAGR, max DD, window return: a gold bull
market flatters any long-biased rule), PAXG-only sleeve stats, Sharpe-difference bootstrap, 2020-2022 / 2023-on split.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone

from . import cta, overlays
from .cta import DAY, SIDE

GOLD = "PAXG_USDT"
RULE, SIZING = "tsmom_vote", "vol"
PAXG_SPREAD_BPS = 0.0
TARGET_11 = 0.44
DD_TOLERANCE = 0.01
MIN_EPISODES = 3
EPISODE_GAP = 7
MAX_CORR = 0.4
COINS_11 = cta.UNIVERSE + (GOLD,)


def costs(mult=1.0):
    c = dict(cta.COST)
    c[GOLD] = SIDE + PAXG_SPREAD_BPS / 2 / 1e4
    return {s: mult * v for s, v in c.items()}


def trim(data):
    """Cut every series to the last bar day that all coins share (same window for basket and control)."""
    end = min(max(rows) for rows in data.values())
    return {s: {t: r for t, r in rows.items() if t <= end} for s, rows in data.items()}


def start_day(data, gold=GOLD):
    """First decision day of the sleeve: the day after the 120th bar."""
    days = sorted(data[gold])
    return days[120] + DAY


def corr(a, b):
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb) if va and vb else 0.0


def sleeve_series(trace, days, gold=GOLD):
    """PAXG daily contribution aligned to the return series days (interval start t0 <-> trace day t0 + DAY)."""
    by = {t: c.get(gold, 0.0) for t, c in trace}
    return [by.get(t0 + DAY, 0.0) for t0 in days]


def in_days(data, days, gold=GOLD):
    out = []
    for t in days:
        row = data[gold].get(t - DAY)
        if row is not None and row["age"] >= 120 and cta.signal(row, RULE):
            out.append(t)
    return out


def decide(basket, control, sleeve_corr, episodes_n):
    sb, sc = cta.stats(basket), cta.stats(control)
    rb, rc = [x[1] for x in basket], [x[1] for x in control]
    boot = overlays.paired_block_bootstrap(rb, rc)
    tol = -overlays.CONTROL_TOLERANCE * (sum(rc) / len(rc))
    thirds = sum(g > c for g, c in zip(sb["sharpe_thirds"], sc["sharpe_thirds"]))
    checks = {"sharpe_higher": (sb["sharpe"] or 0.0) > (sc["sharpe"] or 0.0),
              "max_dd_not_worse_by_more_than_1_point": 100 * (sb["max_drawdown"] - sc["max_drawdown"]) <= 100 * DD_TOLERANCE + 1e-9,
              "sharpe_higher_in_2_of_3_thirds": thirds >= 2,
              "bootstrap_lower_bound_ok": boot["mean_diff"]["lower"] >= tol,
              "sleeve_corr_below_0.4": sleeve_corr < MAX_CORR}
    return {"basket_11": sb, "control_v11": sc, "checks": checks, "all_hold": all(checks.values()),
            "thirds_higher": thirds, "dd_diff_points": 100 * (sb["max_drawdown"] - sc["max_drawdown"]),
            "sleeve_corr": sleeve_corr, "bootstrap_basket_minus_control": boot, "bootstrap_lower_bound_floor": tol,
            "episodes": episodes_n}


def _sims(data, start, mult):
    c = costs(mult)
    ctrace = []
    basket = cta.simulate(data, RULE, SIZING, start, coins=COINS_11, cost=c, target=TARGET_11, trace=ctrace)
    control = cta.simulate(data, RULE, SIZING, start, coins=cta.UNIVERSE, cost=c, target=0.40)
    ds, dc = [x[0] for x in basket], [x[0] for x in control]
    assert ds == dc, "basket and control cover different days"
    return basket, control, ctrace


def evaluate(data, mult=1.0):
    start = start_day(data)
    basket, control, trace = _sims(data, start, mult)
    days = [x[0] for x in basket]
    sleeve = sleeve_series(trace, days)
    r = corr(sleeve, [x[1] for x in control])
    ins = in_days(data, days)
    out = decide(basket, control, r, overlays.episodes(ins, EPISODE_GAP))
    out["window_start"] = datetime.fromtimestamp(days[0] / 1000, timezone.utc).date().isoformat()
    out["paxg_in_days"] = len(ins)
    out["paxg_sleeve_mean_daily_contribution"] = sum(sleeve) / len(sleeve)
    return out, basket, control


def paxg_hold(data, days):
    rows = data[GOLD]
    series = [(t, rows[t + DAY]["o"] / rows[t]["o"] - 1, 1.0) for t in days if t in rows and t + DAY in rows]
    return cta.stats(series)


def run(paths, write=True):
    data = trim(cta.load(paths, COINS_11))
    reg = cta.stats(cta.simulate(data, RULE, SIZING))
    rep = {"preregistered": "see the module docstring (pionex_lab/swing/gold.py)",
           "status": "backtest on PROXY data (Binance PAXGUSDT daily); not proof of profit; red team on a PASS",
           "paxg_spread_bps_samples": [0.024, 0.048, 0.024, 0.024, 0.024],
           "step1_regression": {"stats": reg, "ok": round(reg["cagr"], 3) == 0.358 and round(reg["max_drawdown"], 3) == 0.263
                                and round(reg["sharpe"], 2) == 1.37}}
    if not rep["step1_regression"]["ok"]:
        rep["verdict"] = "VOID (regression check failed)"
    else:
        x1, basket, control = evaluate(data, 1.0)
        x4, _, _ = evaluate(data, 4.0)
        days = [x[0] for x in basket]
        x1["paxg_buy_and_hold"] = paxg_hold(data, days)
        s22 = datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000
        x1["subperiods"] = {}
        for name, sel in (("2020_2022", lambda t: t < s22), ("2023_on", lambda t: t >= s22)):
            parts = [[x for x in s if sel(x[0])] for s in (basket, control)]
            if all(parts):
                x1["subperiods"][name] = dict(zip(("basket_11", "control_v11"), map(cta.stats, parts)))
        rep["window_1x"], rep["window_4x"] = x1, x4
        if x1["episodes"] < MIN_EPISODES:
            rep["verdict"] = "INSUFFICIENT"
        else:
            rep["verdict"] = "PASS" if x1["all_hold"] and x4["all_hold"] else "FAIL"
    if write:
        (paths.reports / "gold_c3.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return rep
