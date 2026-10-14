"""C1: Donchian-ensemble trend (Zarattini, Pagani, Barbon) against CTA v1.1 on the same 10 coins (research only).

PRE-REGISTERED 2026-10-14 21:08 SAST (machine clock), before anything below was run. Nothing changes after a result;
a changed idea is a new test. Issue CLO-3; spec research/edge_candidates_2026-10-14.md section C1; the lead (board)
confirmed the [proposed] gates as written. Status: backtest on PROXY data (Binance daily klines); v1.1 is itself
in-sample, so a pass shows the family is robust to signal design, not a new independent edge. Not proof of profit.

SOURCE OF THE RULE (honest sourcing): the paper "Catching Crypto Trends", SFI Research Paper 25-80, SSRN 5209907,
could NOT be read (SSRN returns HTTP 403; the Concretum summary and abarbon.com give no lookbacks). The definitions
below come from a third-party reading note of the paper that cites the paper's own sections
(github.com/alfred1123/Quant_Strategies docs/research/catching-crypto-trends.md, fetched 2026-10-14): lookbacks
[PAPER Sec. 4.1-4.3], Donchian and entry/exit [Sec. 4.1], trailing mid-line stop [Sec. 4.1, footnote 3], equal-weight
ensemble [Sec. 4.3]. No page numbers could be verified; the rule is second-hand. If the paper differs, this test is of
the rule as written here.
  Lookbacks n (days): 5, 10, 20, 30, 60, 90, 150, 250, 360, equal weight (the recalled grid was right).
  Per coin and lookback, on daily CLOSES: Up_n(t) = max close of the last n days including day t, Down_n(t) = min,
  Mid_n(t) = (Up_n + Down_n) / 2. Flat -> long when close[t] == Up_n(t) (a new n-day closing high), the stop is
  then set to Mid_n(t). Long -> flat when close[t] <= stop(t); otherwise stays long and stop(t+1) = max(stop(t),
  Mid_n(t)) (ratchets, never falls). Exit is checked before entry. A channel is eligible once the coin has n closes.
  (The paper's own vol target 25% and leverage cap 200% are replaced by the lab's v1.1 sizing: spot, no leverage.)

IMPLEMENTATION (default off; cta.simulate(rule="donchian") multiplies each v1.1 target by row["dc"]): per coin and
decision day d (yesterday's close), dc = (number of eligible channels that are long) / (number of eligible channels).
Target weight = dc x (0.40/N) / vol30 (v1.1 sizing; N = coins available; vol30 = 30-day annualised vol), 100% gross
cap, 2% band on drifted weights, decisions on yesterday's close, fills at the next 00:00 UTC open, costs cta.COST
(7 bps per side plus half the measured Pionex spread per coin). Universe BTC ETH SOL XRP DOGE LINK ADA BNB AVAX LTC,
a coin tradable once it has 120 days of history (as v1.1). Channel state runs from each coin's first bar. No
lookback or parameter is tuned. Window: all v1.1 decision days (2017-12-16 to latest); primary comparison on
identical days; since-2021 reported.

STEP 1 (regression check, must hold or the run is void): re-derive v1.1 tsmom_vol "all" through the modified
simulate: CAGR 35.8%, max DD 26.3%, Sharpe 1.37, turnover 15.6x.

GATES (all must hold; confirmed by the lead):
  1. cta.run pass rule: Sharpe above the equal-weight hold basket AND max drawdown below it, on the whole period AND
     since 2021-01-01; Sharpe above hold in at least 2 of the 3 equal thirds of the whole period.
  2. Non-inferiority to v1.1 on identical days: Sharpe >= v1.1 Sharpe - 0.15 AND the paired circular block bootstrap
     (10-day blocks, 20,000 resamples, seed 20261014, one-sided q = 0.025: alpha 0.05 split over C1/C2/C3) lower
     bound of Sharpe(Donchian) - Sharpe(v1.1) >= -0.40.
  3. At 4x costs: Donchian Sharpe >= v1.1's 4x-cost Sharpe - 0.10.
  4. Turnover per year <= 1.25 x v1.1's turnover (15.6x).
  5. No single coin contributes more than 35% of the summed daily contribution (weight x return, before costs) over
     the whole period (the log-return share in the spec is approximated by this arithmetic share; positive
     contributions only if the total is positive).
  Falsified also if gate 1 or 2 fails, or if all the Sharpe comes from 2020-21: operationalised as Sharpe on the days
  outside 2020-01-01..2021-12-31 <= 0.5.
REPORTED, not gating: 50/50 blend with v1.1 (daily-return mix); correlation of daily returns with v1.1 (above 0.95 =
the same bet; adopt only for lower turnover); the two strategies' behaviour in 2026; the same run on the C2 universe
once C2 exists (a confirmation, not a second chance); per-year Sharpe.
Verdict INSUFFICIENT (not PASS) if fewer than 3 distinct episodes (flat/long regime changes of the basket) exist.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone

from . import cta
from .cta import DAY

LOOKBACKS = (5, 10, 20, 30, 60, 90, 150, 250, 360)
NON_INFERIORITY_SHARPE, BOOT_LOWER_MIN, COST4_TOL, TURNOVER_MULT, MAX_COIN_SHARE = 0.15, -0.40, 0.10, 1.25, 0.35
EX_2020_21_MIN_SHARPE = 0.5
BOOT_Q = 0.025
RULES = "donchian-ensemble C1 (pre-registered 2026-10-14 21:08 SAST)"


def channel_states(closes, n):
    """Position (0/1) after each close for one lookback, or None while fewer than n closes exist."""
    out, pos, stop = [], 0, 0.0
    for i, c in enumerate(closes):
        if i < n - 1:
            out.append(None)
            continue
        win = closes[i - n + 1:i + 1]
        up, mid = max(win), (max(win) + min(win)) / 2
        if pos:
            if c <= stop:
                pos = 0
            else:
                stop = max(stop, mid)
        elif c >= up:
            pos, stop = 1, mid
        out.append(pos)
    return out


def share_long(closes, lookbacks=LOOKBACKS):
    """Per day: share of eligible channels that are long (0.0 when none is eligible)."""
    states = [channel_states(closes, n) for n in lookbacks]
    out = []
    for i in range(len(closes)):
        el = [s[i] for s in states if s[i] is not None]
        out.append(sum(el) / len(el) if el else 0.0)
    return out


def add_dc(data):
    """Add row["dc"] to every coin-day of cta.load() data (in place) and return it."""
    for rows in data.values():
        ts = sorted(rows)
        for t, f in zip(ts, share_long([rows[t]["c"] for t in ts])):
            rows[t]["dc"] = f
    return data


def _sharpe(xs):
    m = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))
    return m / sd * math.sqrt(365.25) if sd else 0.0


def _corr(a, b):
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    return cov / math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))


def coin_shares(trace):
    tot = {}
    for _t, d in trace:
        for s, v in d.items():
            tot[s] = tot.get(s, 0.0) + v
    z = sum(tot.values())
    return {s: v / z for s, v in sorted(tot.items())} if z > 0 else {}


def evaluate(data, regression_only=False):
    from .overlays import paired_block_bootstrap
    s21 = int(datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    sim = cta.simulate
    rep = {"rules": RULES}
    base = sim(data, "tsmom_vote", "vol")
    rep["regression_v11"] = cta.stats(base)
    b = rep["regression_v11"]
    rep["regression_ok"] = (abs(b["cagr"] - 0.358) < 0.0006 and abs(b["max_drawdown"] - 0.263) < 0.0006
                            and abs(b["sharpe"] - 1.37) < 0.006)
    if regression_only or not rep["regression_ok"]:
        return rep
    for label, start in (("all", 0), ("since_2021", s21)):
        r = {"ew_hold": cta.stats(sim(data, "hold", "equal", start)),
             "v11": cta.stats(sim(data, "tsmom_vote", "vol", start)),
             "donchian": cta.stats(sim(data, "donchian", "vol", start))}
        rep[label] = r
    a, c = rep["all"], rep["since_2021"]
    g1 = (a["donchian"]["sharpe"] > a["ew_hold"]["sharpe"] and a["donchian"]["max_drawdown"] < a["ew_hold"]["max_drawdown"]
          and c["donchian"]["sharpe"] > c["ew_hold"]["sharpe"] and c["donchian"]["max_drawdown"] < c["ew_hold"]["max_drawdown"]
          and sum(x > y for x, y in zip(a["donchian"]["sharpe_thirds"], a["ew_hold"]["sharpe_thirds"])) >= 2)
    trace = []
    don = sim(data, "donchian", "vol", trace=trace)
    ref = sim(data, "tsmom_vote", "vol")
    assert [x[0] for x in don] == [x[0] for x in ref]
    rd, rv = [x[1] for x in don], [x[1] for x in ref]
    boot = paired_block_bootstrap(rd, rv, q=BOOT_Q)
    g2 = (a["donchian"]["sharpe"] >= a["v11"]["sharpe"] - NON_INFERIORITY_SHARPE
          and boot["sharpe_diff"]["lower"] >= BOOT_LOWER_MIN)
    x4 = {s: 4 * v for s, v in cta.COST.items()}
    cost4 = {"donchian": cta.stats(sim(data, "donchian", "vol", cost=x4)), "v11": cta.stats(sim(data, "tsmom_vote", "vol", cost=x4))}
    g3 = cost4["donchian"]["sharpe"] >= cost4["v11"]["sharpe"] - COST4_TOL
    g4 = a["donchian"]["turnover_per_year"] <= TURNOVER_MULT * a["v11"]["turnover_per_year"]
    shares = coin_shares(trace)
    g5 = bool(shares) and max(shares.values()) <= MAX_COIN_SHARE
    lo, hi = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000), int(datetime(2022, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    ex = [x[1] for x in don if not lo <= x[0] < hi]
    sh_ex = _sharpe(ex)
    reg = [x[2] > 0 for x in don]
    eps = 1 + sum(1 for p, q in zip(reg, reg[1:]) if p != q)
    years = {}
    for (t, r), (_t, rr) in zip(((x[0], x[1]) for x in don), ((x[0], x[1]) for x in ref)):
        y = datetime.fromtimestamp(t / 1000, timezone.utc).year
        years.setdefault(y, ([], []))
        years[y][0].append(r)
        years[y][1].append(rr)
    blend = [(x[0], 0.5 * x[1] + 0.5 * y[1], 0.5 * (x[2] + y[2]), 0.5 * (x[3] + y[3])) for x, y in zip(don, ref)]
    rep.update({
        "bootstrap_vs_v11": boot, "cost_4x": cost4, "coin_share_of_contribution": shares,
        "sharpe_ex_2020_21": sh_ex, "regime_episodes": eps,
        "reported": {"blend_50_50": cta.stats(blend), "corr_with_v11": _corr(rd, rv),
                     "per_year_sharpe": {y: {"donchian": _sharpe(p[0]), "v11": _sharpe(p[1])} for y, p in sorted(years.items()) if len(p[0]) > 20}},
        "gates": {"1_cta_pass_rule": g1, "2_non_inferior_to_v11": g2, "3_cost_4x": g3, "4_turnover": g4,
                  "5_no_coin_over_35pct": g5, "ex_2020_21_sharpe_above_0.5": sh_ex > EX_2020_21_MIN_SHARPE}})
    y26 = [(x[1], y[1]) for x, y in zip(don, ref) if x[0] >= int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)]
    eq = lambda xs: math.prod(1 + v for v in xs) - 1
    rep["reported"]["last_2026"] = {"days": len(y26), "donchian_return": eq([p for p, _ in y26]), "v11_return": eq([q for _, q in y26])}
    gates = rep["gates"]
    rep["verdict"] = "INSUFFICIENT" if eps < 3 else ("PASS" if all(gates.values()) else "FAIL")
    return rep


def run(paths, write=True):
    data = add_dc(cta.load(paths))
    rep = {"venue": "PROXY: Binance spot daily klines, not Pionex",
           "status": "backtest of a rule read second-hand from the paper; v1.1 base is in-sample; not proof of profit"}
    rep.update(evaluate(data))
    if write:
        (paths.reports / "donchian_ensemble_c1.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return rep
