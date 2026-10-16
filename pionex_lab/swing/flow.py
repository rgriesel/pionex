"""Card 3 (research/ideas/2026-10-16.md), CLO-17: daily taker-buy imbalance as a flow confirmation for BTC and ETH.
Research only: no order path. PROXY data (Binance spot daily klines). Not proof of profit.

PRE-REGISTERED 2026-10-16 03:45 SAST (machine clock), before any taker-flow data was fetched or any result produced.
Nothing below changes after a result; a changed idea is a new test. One parameter set, no grid, run once.

STEP 0 (data): proxy_market.db / pit_1d.db do NOT keep the taker-buy columns (checked 2026-10-16: klines has
open..volume only, bars has vol and qvol only). The columns are fetched from the free Binance archive
(data.binance.vision, spot 1d monthly zips + the running month's daily zips, BTCUSDT and ETHUSDT) into a NEW file
var/alpha/taker_1d.db: taker(symbol, t ms, qvol = column 7 quote volume, tbq = column 10 taker-buy quote volume).
Prices for the basket come from proxy_market.db exactly as in v1.1 (cta.load).

FLOW SCORE (per coin, known at the close of day d): ratio_d = tbq_d / qvol_d; m5_d = mean(ratio_{d-4..d});
z_d = (m5_d - mean(m5_{d-365..d-1})) / std(m5_{d-365..d-1}) (population std; the window excludes day d itself and
needs all 365 values; otherwise z is undefined). A day with qvol = 0 or a missing bar makes m5 undefined for 5 days.
A decision on day t at 00:00 UTC uses z_{t-1} (yesterday's close).

STEP 1 (IC screen, first; if it fails the verdict is FAIL and there is no basket test). Per coin separately, on every
day d where z_d exists and the close of d+7 exists: y = c_{d+7}/c_d - 1 (next 7-day return). Controls = the day's
return r1 = c_d/c_{d-1} - 1 and the trailing 5-day return r5 = c_d/c_{d-5} - 1. Both z and y are regressed (OLS, with
intercept) on [r1, r5]; IC = Pearson correlation of the two residual series (partial correlation). The plain Spearman
IC of z vs y is reported too. t-stat = IC * sqrt((n_eff - 2) / (1 - IC^2)) with n_eff = n / 7 (7-day forward returns
overlap; this is the honest adjustment). Gate 1: partial IC > 0 AND t >= 2 for BTC AND for ETH.

STEP 2 (only if step 1 passes): the BTC+ETH two-coin v1.1 book (the $100 canary pair): cta.simulate with
coins = (BTC_USDT, ETH_USDT), tsmom_vote, vol sizing, 40% target, 2% band, 100% cap, cta.COST, decisions on yesterday's
close, fills at the next 00:00 UTC open. Gated book: after the targets are known (post gross cap), a coin's target is
multiplied by 0.5 when its z_{t-1} < -1, else 1 (z undefined -> 1). Implemented through cta.simulate's
`scale` hook returning a per-coin dict {coin: factor} (added by the parallel CLO-16 work; default None = v1.1
byte-identical). [Amended 2026-10-16 ~04:00 SAST, still before any data or result: my own `coin_scale` hook was dropped.] No second variant.
Window: from the first decision day on which both coins have a defined z, to the last v1.1 decision day; v1.1 and all
comparators on the identical days.
Same-exposure control: the same book with no gating and its 40% target scaled by one factor k = avg_exposure(gated) /
avg_exposure(v1.1), one shot, no search (as overlays._control).
Comparators and reports: v1.1 (2-coin, same window), gated, control; full period, the three equal thirds (Sharpe),
CAGR, max drawdown, exposure, turnover, days active per coin, episodes; all repeated at 4x costs (every per-coin cost
x4; control rebuilt at the 4x exposure). The C2 point-in-time universe does not apply (a two-coin book on BTC and ETH
that were top-10 in every month of the window); it is stated, not run.

GATES (all must hold for PASS; the card's kill criterion is gates 2-3):
  1. Step 1 passes (see above).
  2. Sharpe(gated) > Sharpe(control) over the window.
  3. NOT [max-drawdown cut vs v1.1 < 3 percentage points AND Sharpe(gated) <= Sharpe(v1.1)].
  4. Sharpe(gated) > Sharpe(control) at 4x costs.
  5. The gate is active on at least 3 distinct episodes (overlays.episodes, 7-day merge), else INSUFFICIENT.
Thirds are reported, not gating. FAIL if step 1 fails or any of gates 2-4 fails. A PASS goes to the Red Team.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone

from . import cta
from .cta import DAY
from .overlays import episodes

COINS = ("BTC_USDT", "ETH_USDT")
SMOOTH, Z_WINDOW, Z_CUT, GATE_FACTOR, HORIZON = 5, 365, -1.0, 0.5, 7
IC_T_MIN = 2.0
DD_POINTS = 0.03
RULE, SIZING = "tsmom_vote", "vol"
NAN = float("nan")


# ---- data ----------------------------------------------------------------------------------------------
def load_taker(db_path, symbol):
    """{t ms: (qvol, tbq)} from var/alpha/taker_1d.db for a symbol like BTC_USDT."""
    import sqlite3
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT t, qvol, tbq FROM taker WHERE symbol=? ORDER BY t", (symbol.replace("_", ""),)).fetchall()
    conn.close()
    return {t: (q, b) for t, q, b in rows}


def flow_z(taker, smooth=SMOOTH, window=Z_WINDOW):
    """{day t: z_t} known at the close of day t (see the module docstring)."""
    days = sorted(taker)
    ratio = {}
    for t in days:
        q, b = taker[t]
        ratio[t] = b / q if q > 0 else NAN
    m5 = {}
    for t in days:
        xs = [ratio.get(t - k * DAY, NAN) for k in range(smooth)]
        m5[t] = sum(xs) / smooth if all(x == x for x in xs) else NAN
    z = {}
    for t in days:
        hist = [m5.get(t - k * DAY, NAN) for k in range(1, window + 1)]
        if m5[t] != m5[t] or any(x != x for x in hist):
            continue
        mu = sum(hist) / window
        sd = math.sqrt(sum((x - mu) ** 2 for x in hist) / window)
        if sd > 0:
            z[t] = (m5[t] - mu) / sd
    return z


# ---- step 1 --------------------------------------------------------------------------------------------
def _resid(y, xs):
    """OLS residuals of y on [1, xs...] by normal equations (Gaussian elimination)."""
    k = len(xs) + 1
    cols = [[1.0] * len(y)] + xs
    A = [[sum(a * b for a, b in zip(cols[i], cols[j])) for j in range(k)] + [sum(a * b for a, b in zip(cols[i], y))]
         for i in range(k)]
    for i in range(k):
        p = max(range(i, k), key=lambda r: abs(A[r][i]))
        A[i], A[p] = A[p], A[i]
        for r in range(k):
            if r != i:
                f = A[r][i] / A[i][i]
                A[r] = [a - f * b for a, b in zip(A[r], A[i])]
    beta = [A[i][k] / A[i][i] for i in range(k)]
    return [y[n] - sum(beta[i] * cols[i][n] for i in range(k)) for n in range(len(y))]


def _pearson(a, b):
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    sab = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    saa, sbb = sum((x - ma) ** 2 for x in a), sum((y - mb) ** 2 for y in b)
    return sab / math.sqrt(saa * sbb) if saa > 0 and sbb > 0 else 0.0


def _ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def ic_screen(z, closes, horizon=HORIZON):
    """Partial IC (controlling r1 and r5) and plain Spearman IC of z_d vs the next `horizon`-day return."""
    zs, ys, r1, r5 = [], [], [], []
    for d in sorted(z):
        need = (d - DAY, d - 5 * DAY, d + horizon * DAY)
        if d not in closes or any(x not in closes for x in need):
            continue
        zs.append(z[d])
        ys.append(closes[d + horizon * DAY] / closes[d] - 1)
        r1.append(closes[d] / closes[d - DAY] - 1)
        r5.append(closes[d] / closes[d - 5 * DAY] - 1)
    n = len(zs)
    ic = _pearson(_resid(zs, [r1, r5]), _resid(ys, [r1, r5]))
    n_eff = n / horizon
    t = ic * math.sqrt((n_eff - 2) / (1 - ic * ic))
    sp = _pearson(_ranks(zs), _ranks(ys))
    return {"n": n, "n_eff": n_eff, "partial_ic": ic, "t": t, "spearman_ic": sp,
            "pass": ic > 0 and t >= IC_T_MIN,
            "from": datetime.fromtimestamp(min(d for d in z if d in closes) / 1000, timezone.utc).date().isoformat()}


# ---- step 2 --------------------------------------------------------------------------------------------
class FlowScale:
    """cta.simulate scale hook returning {coin: factor}: GATE_FACTOR for a coin whose z (yesterday's close) is below Z_CUT."""

    def __init__(self, zmaps):
        self.z, self.log = zmaps, {}

    def __call__(self, t, targets, data):
        out = {}
        for coin in COINS:
            v = self.z.get(coin, {}).get(t - DAY)
            if v is not None and v < Z_CUT:
                out[coin] = GATE_FACTOR
                if targets.get(coin, 0) > 0:
                    self.log.setdefault(coin, set()).add(t)
        return out


def _stats_pack(data, start, cost=None, hook=None):
    return cta.simulate(data, RULE, SIZING, start, cost=cost, coins=COINS, scale=hook)


def evaluate_book(data, zmaps, mult=1.0):
    start = max(min(z) for z in zmaps.values()) + DAY
    cost = {s: mult * v for s, v in cta.COST.items()}
    base = _stats_pack(data, start, cost)
    hook = FlowScale(zmaps)
    gated = _stats_pack(data, start, cost, hook)
    sb, sg = cta.stats(base), cta.stats(gated)
    k = sg["avg_exposure"] / sb["avg_exposure"]
    ctrl = cta.simulate(data, RULE, SIZING, start, target=0.40 * k, cost=cost, coins=COINS)
    sc = cta.stats(ctrl)
    assert [x[0] for x in base] == [x[0] for x in gated] == [x[0] for x in ctrl]
    act = set().union(*hook.log.values()) if hook.log else set()
    return {"window_from": datetime.fromtimestamp(start / 1000, timezone.utc).date().isoformat(), "cost_mult": mult,
            "v11_2coin": sb, "gated": sg, "control_same_exposure": sc, "control_target_scale": k,
            "max_dd_cut_points": 100 * (sb["max_drawdown"] - sg["max_drawdown"]),
            "days_active": {c: len(v) for c, v in hook.log.items()}, "active_days_any": len(act),
            "episodes": episodes(act)}


def verdict(step1, full, full4):
    g = {"1_step1_ic_passes_both_coins": all(v["pass"] for v in step1.values())}
    if not g["1_step1_ic_passes_both_coins"]:
        return g, "FAIL"
    g["2_sharpe_gated_gt_control"] = full["gated"]["sharpe"] > full["control_same_exposure"]["sharpe"]
    g["3_not_(dd_cut_lt_3pts_and_sharpe_not_higher)"] = not (
        full["max_dd_cut_points"] < 100 * DD_POINTS - 1e-9 and full["gated"]["sharpe"] <= full["v11_2coin"]["sharpe"])
    g["4_sharpe_gated_gt_control_at_4x_costs"] = full4["gated"]["sharpe"] > full4["control_same_exposure"]["sharpe"]
    if full["episodes"] < 3:
        return g, "INSUFFICIENT"
    return g, "PASS" if all(g.values()) else "FAIL"


def run(paths, taker_db=None, write=True):
    taker_db = taker_db or paths.root / "alpha" / "taker_1d.db"
    data = cta.load(paths)
    zmaps, step1 = {}, {}
    for c in COINS:
        zmaps[c] = flow_z(load_taker(taker_db, c))
        closes = {t: r["c"] for t, r in data[c].items()}
        step1[c] = ic_screen(zmaps[c], closes)
    rep = {"preregistered": "see the module docstring (pionex_lab/swing/flow.py)",
           "status": "backtest on PROXY data (Binance daily klines + taker flow); not proof of profit; red team pending on PASS",
           "step1_ic": step1}
    if all(v["pass"] for v in step1.values()):
        rep["step2_full"] = evaluate_book(data, zmaps)
        rep["step2_4x_costs"] = evaluate_book(data, zmaps, 4.0)
        rep["gates"], rep["verdict"] = verdict(step1, rep["step2_full"], rep["step2_4x_costs"])
    else:
        rep["gates"], rep["verdict"] = verdict(step1, None, None)
        rep["step2_full"] = "not run: step 1 failed (pre-registered stop)"
    if write:
        (paths.reports / "flow_taker_card3.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return rep
