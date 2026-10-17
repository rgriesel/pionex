"""CLO-45 item 5: does ADAPTING (regime shrink, strategy stop/re-qualify) beat static holding of CTA v1.1, net of costs?
Research only: no order path. PROXY data (Binance daily klines, var/proxy_market.db). Not proof of profit.

PRE-REGISTERED 2026-10-17 18:14 SAST (machine clock), before the test was run; nothing below changes after a result
(a changed idea is a new test). Issue CLO-45. Prior overlays on v1.1 (corr cap, DVOL shock, BTC gate; STRATEGY_LOG
2026-10-14/16) all FAILED against the same-exposure control; this is a new, different rule set, so it is a new test.

BASE: CTA v1.1 (tsmom_vote, vol sizing, target 40%, 2% band, 10 coins, PROXY costs of cta.COST), full window.
EVALUATION WINDOW: decision days AFTER the first DESIGN_DAYS = 730 (the design window is used only to set the design
range of rule B, so the evaluation is out-of-sample with respect to everything fitted). Thirds = cta.stats thirds.

RULE A (regime shrink; live detector pionex_lab/live/regime.py classify(), daily-bar version, thresholds frozen there):
  at decision day t, label = regime.label_from_daily(BTC closes, ETH closes up to yesterday's close).
  factor = 0 if label == crash, 0.5 if label == high-vol, else 1 (via the cta.simulate `scale` hook: only ever cuts).
RULE B (strategy health stop + re-qualification; live rules pionex_lab/live/health.py, same constants K=0.5, H=5, ZCLIP=3,
  MIN_DAYS_CUSUM=10, RETIRE_WINDOW_DAYS=180):
  design mu, sigma, max drawdown = mean, sd, max drawdown of the static v1.1 daily net returns of the first 730 days.
  While LIVE, from day 731: after each day's return, DRIFT if the downward CUSUM since the last (re)start has >= 10 days and
  S >= H, or the drawdown since the last (re)start exceeds the design max drawdown. DRIFT -> flat from the next day
  (costs: one side, gross exposure x cta.SIDE, at the exit and again at re-entry). While STOPPED the strategy runs as a
  SHADOW (the static v1.1 series keeps being recorded) and returns only when the shadow record since the stop has >= 30
  days, net return > 0, drawdown <= design max, and no CUSUM alarm (the gate's forward rules, no Red Team/luck step in a
  backtest). A second DRIFT within 180 days of the previous stop is RETIRED: flat for the rest of the window.
CONTROL (required, as in overlays.py/btc_gate.py): v1.1 with scale = one constant k = avg_exposure(rule) / avg_exposure(v1.1)
  on the evaluation window (same average exposure, no timing), one shot.

PASS (each rule judged separately, ALL must hold, on the evaluation window):
  1. max drawdown at least 3 percentage points below static v1.1's;
  2. Sharpe >= the same-exposure control's;
  3. Sharpe not lower than static v1.1's in at least 2 of the 3 thirds (fail if lower in >= 2);
  4. block bootstrap (overlays.paired_block_bootstrap, 10-day blocks, 20,000 resamples, q 2.5%) lower bound of the mean
     daily return difference (rule - control) >= -CONTROL_TOLERANCE x mean(v1.1)  (not worse than a plain exposure cut);
  5. luck-proofing, cost stress: at 2x and 4x costs the rule's Sharpe is still >= its control's at the same costs.
  INSUFFICIENT if the rule changes the position in fewer than 3 distinct episodes (overlays.episodes) in the window.
  FAIL otherwise. A PASS needs the Red Team, and only then do the shrink factors go into the allocator; on FAIL the shipped
  allocator keeps scale 1 for that rule (the stop/notify detection stays: it is protection, not a return claim).
REPORTED, not gating: CAGR, exposure, turnover, number of stops/retirements, full-window numbers, deflated Sharpe of each rule
  against the firm trial count N (research/luck.py, if importable), luck block-bootstrap lower bound of the Sharpe diff.
"""
from __future__ import annotations

import json
import math

from ..live import health, regime
from . import cta, overlays
from .cta import DAY

RULE, SIZING, TARGET = "tsmom_vote", "vol", 0.40
DESIGN_DAYS = 730
MIN_SHADOW_DAYS = 30
DD_POINTS = 0.03
MIN_EPISODES = 3
BTC, ETH = "BTC_USDT", "ETH_USDT"
SHRINK = {"crash": 0.0, "high-vol": 0.5}


class RegimeScale:
    """Rule A hook: factor by the regime label at yesterday's close."""

    def __init__(self, data):
        self.days = {s: sorted(data[s]) for s in (BTC, ETH)}
        self.closes = {s: [data[s][d]["c"] for d in self.days[s]] for s in (BTC, ETH)}
        self.idx = {s: {d: i for i, d in enumerate(self.days[s])} for s in (BTC, ETH)}
        self.log = {}

    def __call__(self, t, targets, data):
        y = t - DAY
        i, j = self.idx[BTC].get(y), self.idx[ETH].get(y)
        if i is None:
            return 1.0
        btc = self.closes[BTC][max(0, i - 124):i + 1]
        eth = self.closes[ETH][max(0, j - 124):j + 1] if j is not None else None
        label = regime.label_from_daily(btc, eth)
        f = SHRINK.get(label, 1.0)
        self.log[t] = (label, f)
        return f


def _eq_dd(xs):
    e, pk, dd = 1.0, 1.0, 0.0
    for x in xs:
        e *= 1 + x
        pk = max(pk, e)
        dd = max(dd, 1 - e / pk)
    return e, dd


def rule_b(series, switch_cost):
    """Apply rule B to the static v1.1 series [(t, r, gross, traded)] -> (adapted series on the same days, stop days)."""
    n = len(series)
    rets = [x[1] for x in series]
    d = rets[:DESIGN_DAYS]
    mu = sum(d) / len(d)
    sigma = max(math.sqrt(sum((x - mu) ** 2 for x in d) / len(d)), health.MIN_SIGMA)
    dd_max = _eq_dd(d)[1]
    out = list(series[:DESIGN_DAYS])
    state, start, last_stop, stops = "LIVE", DESIGN_DAYS, None, []
    exit_gross = entry = 0.0
    for i in range(DESIGN_DAYS, n):
        t, r, g, tr = series[i]
        if state == "LIVE":
            if entry:
                out.append((t, (1 + r) * (1 - g * cta.SIDE * switch_cost) - 1, g, tr + g))
                entry = 0.0
            else:
                out.append((t, r, g, tr))
            seg = rets[start:i + 1]
            alarm, _ = health.cusum_loss(seg, mu, sigma)
            if alarm or _eq_dd(seg)[1] > dd_max:
                state, shadow_from, exit_gross = "FLAT", i + 1, g
                if last_stop is not None and (t - last_stop) <= health.RETIRE_WINDOW_DAYS * DAY:
                    state = "RETIRED"
                last_stop = t
                stops.append(t)
        else:
            out.append((t, -exit_gross * cta.SIDE * switch_cost if exit_gross else 0.0, 0.0, exit_gross))
            exit_gross = 0.0
            if state == "FLAT":
                sh = rets[shadow_from:i + 1]
                e2, dd2 = _eq_dd(sh)
                if len(sh) >= MIN_SHADOW_DAYS and e2 > 1.0 and dd2 <= dd_max and not health.cusum_loss(sh, mu, sigma)[0]:
                    state, start, entry = "LIVE", i + 1, 1.0
    return out, stops


def window(series, k=DESIGN_DAYS):
    return series[k:]


def _decide(base, rule, ctrl, base4, rule4, ctrl4, base2, rule2, ctrl2, episodes_n):
    sb, sr, sc = cta.stats(base), cta.stats(rule), cta.stats(ctrl)
    rb, rr, rc = ([x[1] for x in s] for s in (base, rule, ctrl))
    boot = overlays.paired_block_bootstrap(rr, rc)
    tol = -overlays.CONTROL_TOLERANCE * (sum(rb) / len(rb))
    lower = boot["mean_diff"]["lower"]
    thirds_worse = sum(a < b for a, b in zip(sr["sharpe_thirds"], sb["sharpe_thirds"]))
    s4 = [cta.stats(x)["sharpe"] for x in (rule4, ctrl4)]
    s2 = [cta.stats(x)["sharpe"] for x in (rule2, ctrl2)]
    gates = {"dd_cut_3pts": sr["max_drawdown"] <= sb["max_drawdown"] - DD_POINTS,
             "sharpe_ge_control": sr["sharpe"] >= sc["sharpe"],
             "thirds_not_worse_in_2": thirds_worse < 2,
             "bootstrap_vs_control": lower >= tol,
             "cost_stress_2x_4x": s2[0] >= s2[1] and s4[0] >= s4[1]}
    verdict = "INSUFFICIENT" if episodes_n < MIN_EPISODES else ("PASS" if all(gates.values()) else "FAIL")
    return {"verdict": verdict, "gates": gates, "episodes": episodes_n, "static": sb, "rule": sr, "control": sc,
            "bootstrap_vs_control": boot, "bootstrap_tolerance": tol, "thirds_worse": thirds_worse,
            "sharpe_2x": s2, "sharpe_4x": s4}


def _ctrl(data, cost, k):
    return cta.simulate(data, RULE, SIZING, 0, cost=cost, scale=lambda t, tg, d: k, target=TARGET)


def evaluate(data, mult):
    """Static, rule A, rule B and their same-exposure controls at `mult` x costs; returns the series."""
    cost = {s: mult * v for s, v in cta.COST.items()} if mult != 1 else None
    base = cta.simulate(data, RULE, SIZING, 0, cost=cost, target=TARGET)
    hook = RegimeScale(data)
    a = cta.simulate(data, RULE, SIZING, 0, cost=cost, scale=hook, target=TARGET)
    b, stops = rule_b(base, mult)
    out = {"base": base, "A": a, "B": b, "hook": hook, "stops": stops, "ctrl": {}}
    for name, ser in (("A", a), ("B", b)):
        k = min(1.0, cta.stats(window(ser))["avg_exposure"] / cta.stats(window(base))["avg_exposure"])
        out["ctrl"][name] = (k, _ctrl(data, cost, k))
    return out


def run(paths, write=True):
    data = cta.load(paths)
    reg = cta.stats(cta.simulate(data, RULE, SIZING))
    rep = {"preregistered": "see the module docstring (pionex_lab/swing/adapt_test.py)",
           "status": "backtest on PROXY data; overlay on the in-sample v1.1; not proof of profit",
           "step1_regression": {"stats": reg, "ok": round(reg["cagr"], 3) == 0.358 and round(reg["max_drawdown"], 3) == 0.263
                                and round(reg["sharpe"], 2) == 1.37}}
    if not rep["step1_regression"]["ok"]:
        rep["verdict"] = "VOID (regression check failed)"
    else:
        r1, r2, r4 = evaluate(data, 1), evaluate(data, 2), evaluate(data, 4)
        rep["rules"] = {}
        for name in ("A", "B"):
            if name == "A":
                ep = overlays.episodes([t for t, (lab, f) in r1["hook"].log.items() if f < 1.0 and t >= window(r1["base"])[0][0]])
            else:
                ep = overlays.episodes(list(r1["stops"]))
            rep["rules"][name] = _decide(window(r1["base"]), window(r1[name]), window(r1["ctrl"][name][1]),
                                         window(r4["base"]), window(r4[name]), window(r4["ctrl"][name][1]),
                                         window(r2["base"]), window(r2[name]), window(r2["ctrl"][name][1]), ep)
            rep["rules"][name]["control_k"] = r1["ctrl"][name][0]
            rep["rules"][name]["full_window"] = {"static": cta.stats(r1["base"]), "rule": cta.stats(r1[name])}
            rr = [x[1] for x in window(r1[name])]
            try:
                from ..research import luck
                n = luck.trial_count(paths.root / "trials.db")
                rep["rules"][name]["deflated_sharpe"] = luck.deflated_sharpe(rr, max(n, 1))
                rep["rules"][name]["luck_block_bootstrap"] = luck.block_bootstrap(rr, n_boot=2000)
            except Exception as exc:                          # reported only; the suite is another agent's module
                rep["rules"][name]["luck_unavailable"] = f"{type(exc).__name__}: {str(exc)[:80]}"
        rep["activity"] = {"A_days_cut": sum(1 for f in (v[1] for v in r1["hook"].log.values()) if f < 1.0),
                           "A_label_counts": {lab: sum(1 for v in r1["hook"].log.values() if v[0] == lab)
                                              for lab in ("crash", "high-vol", "bull", "bear", "low-vol", "sideways", "unknown")},
                           "B_stops": len(r1["stops"])}
        rep["verdict"] = {k: v["verdict"] for k, v in rep["rules"].items()}
    if write:
        (paths.reports / "adapt_test_clo45.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    return rep
