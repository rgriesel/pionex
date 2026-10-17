"""Card 2 (research/ideas/2026-10-17.md), CLO-29: smart-vs-crowd positioning divergence, STEP 1 (IC screen) only.
Research only: no order path. PROXY data (Binance USD-M futures `metrics` archive as stored in proxy_market.db).
Not proof of profit.

PRE-REGISTERED 2026-10-17 03:50 SAST (machine clock), before any divergence score or IC was computed.
Nothing below changes after a result; a changed idea is a new test. One parameter set, no grid, run once.

HYPOTHESIS: when top traders (large accounts, by position size) are more net long than the broad account base, the
next 7 days are better than average; the reverse when the crowd is long and top traders are not.

DATA: var/proxy_market.db table metrics (5-minute rows, BTC_USDT and ETH_USDT, 2023-04-01 -> 2026-10-12, free
Binance archive, PROXY). top_ls_sum = top-trader POSITION long/short ratio; ls_count = all-account COUNT long/short
ratio (top_ls_count, the top-trader account ratio, is not used). Daily value of each = mean over the UTC day of the
5-minute log ratio; a day with fewer than 200 valid rows (of 288) or any ratio <= 0 is undefined. Daily closes:
proxy_market.db klines 1D (as flow.py / cta.load).
SCORE: g_d = mean_d(log top_ls_sum) - mean_d(log ls_count); m5_d = mean(g_{d-4..d}) (all 5 days defined);
D_d = (m5_d - mean(m5_{d-365..d-1})) / popstd(m5_{d-365..d-1}), all 365 values required (excludes day d).
Known at the close of day d.
STEP 1: per coin on each day d with D_d defined and closes d-5, d-1, d, d+7 present: y = c_{d+7}/c_d - 1;
controls r1 = c_d/c_{d-1}-1, r5 = c_d/c_{d-5}-1; D and y regressed on [1, r1, r5], IC = Pearson of residuals;
t = IC*sqrt((n/7 - 2)/(1 - IC^2)). Plain Spearman reported. Halves: the sorted valid days split at the median
into first and second half; partial IC of each half reported (same controls).
COST BASIS: step 1 trades nothing, so cta.COST and the 4x stress are not applicable here; they apply to step 2,
which is a separate pre-registered run and happens only after a PASS of step 1.
KILL CRITERION (card): INSUFFICIENT if raw metrics history < 3 years (1096 days) for either coin.
FAIL if partial IC is not > 0 with t >= 2 on BOTH BTC and ETH, or the sign of the partial IC differs between
halves (either coin). Otherwise step 1 PASSES (not a strategy PASS; step 2 gate and Red Team still required).
"""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timezone

from .cta import DAY
from .flow import _pearson, _ranks, _resid, IC_T_MIN

COINS = ("BTC_USDT", "ETH_USDT")
SMOOTH, Z_WINDOW, HORIZON, MIN_ROWS, MIN_HISTORY_DAYS = 5, 365, 7, 200, 1096
NAN = float("nan")


def load_gap(db_path, symbol):
    """{day t ms: mean log(top_ls_sum) - mean log(ls_count)} over valid 5-minute rows of the UTC day."""
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT t, top_ls_sum, ls_count FROM metrics WHERE symbol=? ORDER BY t", (symbol,)).fetchall()
    conn.close()
    acc = {}
    for t, a, b in rows:
        if a is None or b is None or a <= 0 or b <= 0:
            continue
        s = acc.setdefault(t - t % DAY, [0, 0.0, 0.0])
        s[0] += 1
        s[1] += math.log(a)
        s[2] += math.log(b)
    gap = {d: (s[1] - s[2]) / s[0] for d, s in acc.items() if s[0] >= MIN_ROWS}
    span = (rows[-1][0] - rows[0][0]) / DAY if rows else 0
    return gap, span


def divergence_z(gap, smooth=SMOOTH, window=Z_WINDOW):
    days = sorted(gap)
    m5 = {}
    for t in days:
        xs = [gap.get(t - k * DAY, NAN) for k in range(smooth)]
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


def _sample(z, closes, days, horizon=HORIZON):
    zs, ys, r1, r5 = [], [], [], []
    for d in days:
        need = (d - DAY, d - 5 * DAY, d + horizon * DAY)
        if d not in closes or any(x not in closes for x in need):
            continue
        zs.append(z[d])
        ys.append(closes[d + horizon * DAY] / closes[d] - 1)
        r1.append(closes[d] / closes[d - DAY] - 1)
        r5.append(closes[d] / closes[d - 5 * DAY] - 1)
    return zs, ys, r1, r5


def _ic(zs, ys, r1, r5, horizon=HORIZON):
    n = len(zs)
    ic = _pearson(_resid(zs, [r1, r5]), _resid(ys, [r1, r5]))
    t = ic * math.sqrt((n / horizon - 2) / (1 - ic * ic))
    return {"n": n, "n_eff": n / horizon, "partial_ic": ic, "t": t, "spearman_ic": _pearson(_ranks(zs), _ranks(ys))}


def screen(z, closes):
    days = [d for d in sorted(z) if d in closes]
    full = _ic(*_sample(z, closes, days))
    valid = [d for d in days if all(x in closes for x in (d - DAY, d - 5 * DAY, d + HORIZON * DAY))]
    mid = len(valid) // 2
    h1, h2 = _ic(*_sample(z, closes, valid[:mid])), _ic(*_sample(z, closes, valid[mid:]))
    full.update(first_half=h1, second_half=h2, halves_same_sign=(h1["partial_ic"] > 0) == (h2["partial_ic"] > 0),
                **{"from": datetime.fromtimestamp(valid[0] / 1000, timezone.utc).date().isoformat(),
                   "to": datetime.fromtimestamp(valid[-1] / 1000, timezone.utc).date().isoformat()})
    full["pass"] = full["partial_ic"] > 0 and full["t"] >= IC_T_MIN and full["halves_same_sign"]
    return full


def verdict(step1, spans):
    if any(s < MIN_HISTORY_DAYS for s in spans.values()):
        return "INSUFFICIENT"
    return "PASS_STEP1" if all(v["pass"] for v in step1.values()) else "FAIL"


def run(paths, metrics_db=None, write=True):
    from . import cta
    metrics_db = metrics_db or paths.root / "proxy_market.db"
    data = cta.load(paths)
    step1, spans = {}, {}
    for c in COINS:
        gap, spans[c] = load_gap(metrics_db, c)
        step1[c] = screen(divergence_z(gap), {t: r["c"] for t, r in data[c].items()})
    rep = {"preregistered": "see the module docstring (pionex_lab/swing/positioning.py)",
           "status": "step 1 IC screen on PROXY data (Binance futures metrics); not proof of profit",
           "history_days": spans, "step1_ic": step1, "verdict": verdict(step1, spans)}
    if write:
        (paths.reports / "positioning_card2.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return rep
