"""Idea card 1 (2026-10-16): BTC-led regime gate for the altcoin votes on CTA basket v1.1 (research only: no order path).

PRE-REGISTERED 2026-10-16 03:50 SAST (machine clock), before the test was run (nothing below changes after a result;
a changed idea is a new test). Issue CLO-16, card 1 of research/ideas/2026-10-16.md. Not previously tested (checked
docs/STRATEGY_LOG.md). Status: overlay on the in-sample v1.1, PROXY data (Binance daily klines). Not proof of profit.

HYPOTHESIS: an altcoin's trend vote is more reliable when BTC's trend is also IN; alts held while BTC is OUT give the
deepest drawdowns.

RULE: v1.1 unchanged (tsmom_vote: 2 of the 20/60/120-day returns > 0 at yesterday's close; vol sizing 40%/N per coin /
30-day vol; 100% gross cap; 2% band; decisions on yesterday's close, fills at the 00:00 UTC open). Gate: on each
decision day t the targets of the 9 non-BTC coins are multiplied by 1 if BTC's v1.1 vote is IN at yesterday's close
(BTC row of day t-1 exists, has 120 bars of history and passes the vote), else by 0. BTC's own target is untouched. A
missing BTC row counts as OUT. Gate applied after the gross cap, before the band (the cta.simulate `scale` hook, which
now also accepts a {coin: factor} dict; default behaviour byte-identical). Single parameter set, no grid.

WINDOW: full v1.1 window (all decision days from 2017-12-16). Thirds = cta.stats equal thirds.

CONTROL (required): v1.1 with its 40% target scaled by one factor k = avg_exposure(gate) / avg_exposure(v1.1), so the
average gross exposure matches; one shot, no search (as in overlays.py).

BINDING EPISODES: a day "binds" when BTC is OUT and at least one alt would have had a positive target (the gate
changes something). Episodes = runs of binding days merged when separated by fewer than 7 quiet days
(overlays.episodes).

VERDICT RULE (the card's kill criterion):
  INSUFFICIENT if the gate binds in fewer than 3 distinct episodes.
  FAIL if any of: (a) max drawdown of the gate is not at least 3 percentage points below v1.1's; (b) Sharpe of the gate
  is below the same-exposure control's; (c) Sharpe of the gate is lower than v1.1's in at least 2 of the 3 thirds.
  PASS otherwise. On PASS the CEO sends it to the Red Team.
REPORTED, not gating: CAGR, turnover, exposure, bootstrap (10-day blocks, 20,000 resamples, seed 20261014) of the
Sharpe difference gate - control and gate - v1.1, a 4x-cost run (gate, v1.1, control at 4x costs) and its Sharpe
comparison, 2018-20 / 2021-on split, and the C2 point-in-time top-10 universe (pit_1d.db, pit.cost_map costs, same
rule, same control construction, same kill criterion applied as a confirmation) where BTC is a member.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from . import cta, overlays, pit
from .cta import DAY

BTC = "BTC_USDT"
RULE, SIZING = "tsmom_vote", "vol"
DD_POINTS = 0.03
MIN_EPISODES = 3


class BtcGate:
    """scale hook: factor 0 on every non-BTC coin on days BTC's v1.1 vote is OUT at yesterday's close."""

    def __init__(self, btc=BTC):
        self.btc, self.log = btc, {}

    def btc_in(self, t, data):
        row = data.get(self.btc, {}).get(t - DAY)
        return bool(row is not None and row["age"] >= 120 and cta.signal(row, RULE))

    def __call__(self, t, targets, data):
        inn = self.btc_in(t, data)
        alts = [s for s, w in targets.items() if s != self.btc and w > 0]
        self.log[t] = {"btc_in": inn, "binds": (not inn) and bool(alts)}
        return {} if inn else {s: 0.0 for s in targets if s != self.btc}


def _decide(base, gate, ctrl, episodes_n):
    sb, sg, sc = cta.stats(base), cta.stats(gate), cta.stats(ctrl)
    checks = {"max_dd_down_3_points": 100 * (sb["max_drawdown"] - sg["max_drawdown"]) >= 100 * DD_POINTS - 1e-9,
              "sharpe_not_below_same_exposure_control": (sg["sharpe"] or 0.0) >= (sc["sharpe"] or 0.0),
              "sharpe_not_lower_in_2_of_3_thirds": sum(g < b for g, b in zip(sg["sharpe_thirds"], sb["sharpe_thirds"])) < 2}
    verdict = "INSUFFICIENT" if episodes_n < MIN_EPISODES else ("PASS" if all(checks.values()) else "FAIL")
    return {"v11": sb, "gate": sg, "control_same_exposure": sc, "checks": checks, "verdict": verdict,
            "dd_cut_points": 100 * (sb["max_drawdown"] - sg["max_drawdown"]),
            "thirds_lower_than_v11": sum(g < b for g, b in zip(sg["sharpe_thirds"], sb["sharpe_thirds"]))}


def evaluate(data, coins=cta.UNIVERSE, cost=None, cost4=None, btc=BTC, **kw):
    """Run base, gate, control (and the same at 4x costs) once; return the report block."""
    def sim(c=None, scale=None, target=0.40):
        return cta.simulate(data, RULE, SIZING, 0, coins=coins, cost=c, scale=scale, target=target, **kw)
    base = sim(cost)
    hook = BtcGate(btc)
    gate = sim(cost, hook)
    k = cta.stats(gate)["avg_exposure"] / cta.stats(base)["avg_exposure"]
    ctrl = sim(cost, target=0.40 * k)
    days = [x[0] for x in gate]
    binds = [t for t in days if hook.log.get(t, {}).get("binds")]
    out = _decide(base, gate, ctrl, overlays.episodes(binds))
    out["control_target_scale"] = k
    out["activity"] = {"decision_days": len(days), "btc_out_days": sum(1 for t in days if not hook.log.get(t, {}).get("btc_in", True)),
                       "binding_days": len(binds), "episodes": overlays.episodes(binds),
                       "episode_ranges": _ranges(binds)}
    rb, rg, rc = ([x[1] for x in s] for s in (base, gate, ctrl))
    out["bootstrap"] = {"gate_minus_control": overlays.paired_block_bootstrap(rg, rc),
                        "gate_minus_v11": overlays.paired_block_bootstrap(rg, rb)}
    out["turnover_per_year"] = {"v11": out["v11"]["turnover_per_year"], "gate": out["gate"]["turnover_per_year"]}
    if cost4 is not None:
        b4, g4 = sim(cost4), sim(cost4, BtcGate(btc))
        k4 = cta.stats(g4)["avg_exposure"] / cta.stats(b4)["avg_exposure"]
        c4 = sim(cost4, target=0.40 * k4)
        out["costs_4x"] = _decide(b4, g4, c4, out["activity"]["episodes"])
    s21 = datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp() * 1000
    out["subperiods"] = {}
    for name, sel in (("2018_2020", lambda t: t < s21), ("2021_on", lambda t: t >= s21)):
        parts = [[x for x in s_ if sel(x[0])] for s_ in (base, gate, ctrl)]
        if all(parts):
            out["subperiods"][name] = dict(zip(("v11", "gate", "control"), map(cta.stats, parts)))
    return out


def _ranges(days, gap=overlays.EPISODE_GAP_DAYS):
    """[(first day, last day, binding days)] per episode."""
    out, cur, last = [], None, None
    for t in sorted(days):
        if last is None or (t - last) // DAY - 1 >= gap:
            cur = [t, t, 0]
            out.append(cur)
        cur[1], cur[2], last = t, cur[2] + 1, t
    return [[pit._iso(a), pit._iso(b), n] for a, b, n in out]


def evaluate_pit(series, sets10):
    """C2 confirmation: the same test on the point-in-time top-10 universe (window from pit.START)."""
    fixed = [s for s in cta.UNIVERSE if s in series]
    need = set(fixed)
    for v in sets10.values():
        need.update(v)
    data = {n: pit.rows_of(series[n]) for n in need}
    names = sorted(need)
    uni = pit.universe_fn(sets10)

    def sim(scale=None, target=0.40, c=None):
        return cta.simulate(data, RULE, SIZING, pit.START, coins=names, cost=c, universe=uni, scale=scale, target=target)
    c1, c4 = pit.cost_map(names), pit.cost_map(names, 4.0)
    res = {}
    for label, c in (("costs_1x", c1), ("costs_4x", c4)):
        base, hook = sim(c=c), BtcGate()
        gate = sim(hook, c=c)
        k = cta.stats(gate)["avg_exposure"] / cta.stats(base)["avg_exposure"]
        ctrl = sim(target=0.40 * k, c=c)
        binds = [x[0] for x in gate if hook.log.get(x[0], {}).get("binds")]
        res[label] = _decide(base, gate, ctrl, overlays.episodes(binds))
        res[label]["control_target_scale"] = k
        res[label]["activity"] = {"binding_days": len(binds), "episodes": overlays.episodes(binds)}
    return res


def run(paths, write=True):
    data = cta.load(paths)
    costs4 = {s: 4 * v for s, v in cta.COST.items()}
    reg = cta.stats(cta.simulate(data, RULE, SIZING))
    rep = {"preregistered": "see the module docstring (pionex_lab/swing/btc_gate.py)",
           "status": "backtest on PROXY data; overlay on the in-sample v1.1; not proof of profit; red team on a PASS",
           "step1_regression": {"stats": reg, "ok": round(reg["cagr"], 3) == 0.358 and round(reg["max_drawdown"], 3) == 0.263
                                and round(reg["sharpe"], 2) == 1.37}}
    if not rep["step1_regression"]["ok"]:
        rep["verdict"] = "VOID (regression check failed)"
    else:
        rep["full_period"] = evaluate(data, cost4=costs4)
        rep["verdict"] = rep["full_period"]["verdict"]
        db = paths.root / "alpha" / "pit_1d.db"
        if db.exists():
            series = pit.load_series(db)
            rep["c2_point_in_time_confirmation"] = evaluate_pit(series, pit.rank_universe(series, pit.TOP))
    if write:
        (paths.reports / "btc_gate_card1.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return rep
