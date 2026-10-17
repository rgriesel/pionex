"""Pre-registered tests of the two rules taken from the owner-bot mining (CLO-46). Research only: no network, no orders.

PRE-REGISTERED 2026-10-17 18:25 SAST (machine clock), BEFORE any run of this module. Frozen; a changed idea is a new test.

Where the rules come from (research/owner_bots_2026-10-17.md; 41 finished bots, 39 futures, ONE 5-week window, one market,
so the findings are exploratory and uncorrected for 22 comparisons): (a) 90% of the owner's profit was FLOAT profit, i.e. the
direction of the position, and the winners' return rank-correlates with the direction-aligned move (rho 0.51, p 0.007, n 27);
(b) grid profit rises with realised volatility (rho 0.40, p 0.04, n 27) and with leverage (mechanical, rho 0.63).

Common set-up: BTC_USDT hourly OHLC from var/proxy_market.db (Binance PROXY archive), 2023-01-01 -> last full window; non-
overlapping WINDOW = 14 days (336 hourly bars) starting at 00:00 UTC. Each window is one grid run of swing/grid.simulate: band
start +-8%, 40 rows, geometric, stop-loss bottom*0.97, closed at the window end, fee 0.05%, slip 0.02% on grid fills and 0.05%
on market orders. A rule decides from data BEFORE the window starts, never after. Cash earns 0 while a rule is out.

R1 SPOT, volatility gate. Run the window only if regime.vol_ratio (14d / 90d realised vol of daily closes, CLO-45) >= 1.0
  at the window start; otherwise stay in cash. Statistic: mean net return of the windows run. Baseline: run every window.
  PASS needs ALL of: (1) >= 40 windows run; (2) mean return of run windows > 0 and > mean of all windows; (3) permutation
  p <= luck.thresholds(N).perm_p_max (10,000 random subsets of the same size drawn from all windows; one-sided on the
  mean); (4) block-bootstrap (block 2 windows, 2,000 resamples) 2.5% lower bound of the mean of run windows > 0.

R2 FUTURES, direction-aligned grid, 5x. Direction = long if the 168h return before the window start is > 0, else short.
  Futures-grid mechanics are modelled as the spot grid with notional N = 5 x margin; margin is the capital; return on margin =
  5 x the sim return minus funding 0.03%/day on notional (charged on both sides, conservative). A SHORT grid is the long grid
  on the reflected path p' = p0^2/p. Liquidation: a conservative price p_liq = mean(levels) x (1 - 1/L + 0.005) (long) /
  reflected (short); if the path reaches p_liq before the stop, the whole margin is lost (return -100%).
  Baselines: always long 5x; always short 5x. PASS needs ALL of: (1) >= 40 windows; (2) mean return > 0 and > both
  baselines; (3) permutation p <= luck.thresholds(N).perm_p_max (10,000 random direction assignments with the same number of
  longs; statistic = mean return); (4) block-bootstrap lower bound of the mean > 0; (5) zero liquidations at 5x.
  SENSITIVITY, reported and NOT gated: the same at 20x (liquidation-dominated; the owner mostly ran 15-40x).

Both rules count as 2 more trials in var/trials.db (recorded after the report is computed).
"""
from __future__ import annotations

import json
import math
import random
import sqlite3
from pathlib import Path

from ..swing import grid
from . import luck

DAY_MS = 86_400_000
WINDOW_BARS = 336
START_MS = 1_672_531_200_000          # 2023-01-01 00:00 UTC
BAND, ROWS, STOP, INVEST = 0.08, 40, 0.97, 1000.0
SLIP, SLIP_MKT = 0.0002, 0.0005
FUND_PER_DAY = 0.0003
LEV, LEV_SENS = 5, 20
VOL_GATE = 1.0
MIN_WINDOWS = 40
N_PERM, SEED = 10_000, 4602
BOOT_BLOCK, BOOT_N = 2, 2000


def load_ohlc(db, symbol="BTC_USDT"):
    c = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)
    try:
        rows = c.execute("SELECT open_time, open, high, low, close FROM klines WHERE symbol=? AND interval='60M' "
                         "AND open_time>=? ORDER BY open_time", (symbol, START_MS - 120 * DAY_MS)).fetchall()
    finally:
        c.close()
    return [(int(t), float(o), float(h), float(l), float(cl)) for t, o, h, l, cl in rows]


def windows(bars):
    """Non-overlapping windows as (start_index, bars[start:start+336]); only full, gap-free ones."""
    out = []
    i = 0
    while i < len(bars) and bars[i][0] < START_MS:
        i += 1
    while i + WINDOW_BARS <= len(bars):
        w = bars[i:i + WINDOW_BARS]
        if w[0][0] % DAY_MS == 0 and w[-1][0] - w[0][0] == (WINDOW_BARS - 1) * 3_600_000:
            out.append((i, w))
            i += WINDOW_BARS
        else:
            i += 1
    return out


def daily_closes(bars, i):
    """Last hourly close of each UTC day strictly before bars[i]'s day, oldest first (no look-ahead)."""
    day0 = bars[i][0] // DAY_MS * DAY_MS
    last = {}
    for t, _o, _h, _l, c in bars[max(0, i - 24 * 120):i]:
        d = t // DAY_MS * DAY_MS
        if d < day0:
            last[d] = c
    return [last[k] for k in sorted(last)]


def reflect(w):
    p0 = w[0][1]
    k = p0 * p0
    return [(t, k / o, k / l, k / h, k / c) for t, o, h, l, c in w]


def run_window(w, lev=1, short=False):
    """Return on margin of one window. lev=1 is the plain spot grid."""
    ww = reflect(w) if short else w
    p0 = ww[0][1]
    bottom, top = p0 * (1 - BAND), p0 * (1 + BAND)
    lv = grid.levels(bottom, top, ROWS, "geometric")
    stop = bottom * STOP
    liq = None
    if lev > 1:
        liq = sum(lv) / len(lv) * (1 - 1.0 / lev + 0.005)
        stop = max(stop, liq)
    r = grid.simulate(ww, bottom, top, ROWS, INVEST, "geometric", slip=SLIP, slip_market=SLIP_MKT, stop_price=stop)
    if lev == 1:
        return {"ret": r["return"], "liq": False}
    liquidated = r["exit"] == "stop_loss" and liq is not None and liq >= bottom * STOP
    if liquidated:
        return {"ret": -1.0, "liq": True}
    ret = lev * r["return"] - FUND_PER_DAY * (WINDOW_BARS / 24) * lev
    return {"ret": max(ret, -1.0), "liq": False}


def perm_mean(rets_all, k, obs, rng, n=N_PERM):
    hit = 0
    for _ in range(n):
        if sum(rng.sample(rets_all, k)) / k >= obs - 1e-15:
            hit += 1
    return (hit + 1) / (n + 1)


def perm_direction(long_rets, short_rets, n_long, obs, rng, n=N_PERM):
    hit = 0
    m = len(long_rets)
    for _ in range(n):
        longs = set(rng.sample(range(m), n_long))
        s = sum(long_rets[i] if i in longs else short_rets[i] for i in range(m)) / m
        if s >= obs - 1e-15:
            hit += 1
    return (hit + 1) / (n + 1)


def compound(rets):
    eq, peak, dd = 1.0, 1.0, 0.0
    for r in rets:
        eq *= 1 + r
        peak = max(peak, eq)
        dd = max(dd, 1 - eq / peak)
    return {"total_return": eq - 1, "max_dd": dd}


def evaluate(bars, n_trials, n_perm=N_PERM):
    from ..live import regime
    th = luck.thresholds(n_trials)
    ws = windows(bars)
    rng = random.Random(SEED)
    spot, vr, longs, shorts, longs_s, shorts_s = [], [], [], [], [], []
    for i, w in ws:
        d = daily_closes(bars, i)
        vr.append(regime.vol_ratio(d))
        spot.append(run_window(w)["ret"])
        tr = bars[i - 1][4] / bars[i - 169][4] - 1 if i >= 169 else 0.0
        longs.append((run_window(w, LEV), tr))
        shorts.append((run_window(w, LEV, True), tr))
        longs_s.append(run_window(w, LEV_SENS))
        shorts_s.append(run_window(w, LEV_SENS, True))
    # ---- R1
    run_idx = [k for k, v in enumerate(vr) if v is not None and v >= VOL_GATE]
    r1_runs = [spot[k] for k in run_idx]
    r1 = {"windows_total": len(ws), "windows_run": len(r1_runs), "mean_all": sum(spot) / len(spot),
          "mean_run": sum(r1_runs) / len(r1_runs) if r1_runs else None,
          "mean_idle": (sum(spot[k] for k in range(len(spot)) if k not in set(run_idx)) / max(1, len(spot) - len(run_idx))),
          "compound_gated": compound([spot[k] if k in set(run_idx) else 0.0 for k in range(len(spot))]),
          "compound_always": compound(spot)}
    if r1_runs:
        r1["perm_p"] = perm_mean(spot, len(r1_runs), r1["mean_run"], rng, n_perm)
        r1["boot_lower_bps"] = luck.block_bootstrap(r1_runs, BOOT_BLOCK, BOOT_N)["mean_lower_bps"]
        r1["pass"] = bool(len(r1_runs) >= MIN_WINDOWS and r1["mean_run"] > 0 and r1["mean_run"] > r1["mean_all"]
                          and r1["perm_p"] <= th["perm_p_max"] and r1["boot_lower_bps"] > 0)
    else:
        r1["pass"] = False
    # ---- R2
    def r2_block(L, S, tag):
        lr, sr = [x[0]["ret"] for x in L], [x[0]["ret"] for x in S]
        dirn = [t > 0 for _l, t in L]
        rule = [lr[k] if dirn[k] else sr[k] for k in range(len(lr))]
        out = {"leverage": tag, "windows": len(rule), "n_long": sum(dirn), "mean_rule": sum(rule) / len(rule),
               "mean_always_long": sum(lr) / len(lr), "mean_always_short": sum(sr) / len(sr),
               "liquidations_rule": sum(1 for k in range(len(rule)) if (L[k][0] if dirn[k] else S[k][0])["liq"]),
               "compound_rule": compound(rule), "compound_long": compound(lr), "compound_short": compound(sr)}
        out["perm_p"] = perm_direction(lr, sr, sum(dirn), out["mean_rule"], rng, n_perm)
        out["boot_lower_bps"] = luck.block_bootstrap(rule, BOOT_BLOCK, BOOT_N)["mean_lower_bps"]
        return out, rule
    r2, rule5 = r2_block(longs, shorts, LEV)
    r2["pass"] = bool(r2["windows"] >= MIN_WINDOWS and r2["mean_rule"] > 0 and r2["mean_rule"] > max(r2["mean_always_long"], r2["mean_always_short"])
                      and r2["perm_p"] <= th["perm_p_max"] and r2["boot_lower_bps"] > 0 and r2["liquidations_rule"] == 0)
    sens, _ = r2_block([(a, t) for a, (_x, t) in zip(longs_s, longs)], [(a, t) for a, (_x, t) in zip(shorts_s, shorts)], LEV_SENS)
    return {"thresholds": th, "n_trials_before": n_trials, "window_span": [ws[0][1][0][0], ws[-1][1][-1][0]],
            "R1_spot_volgate": r1, "R2_futures_direction_5x": r2, "R2_sensitivity_20x_not_gated": sens}


def main():
    root = Path(__file__).resolve().parents[2]
    bars = load_ohlc(root / "var" / "proxy_market.db")
    reg = root / "var" / "trials.db"
    n = luck.trial_count(reg)
    rep = evaluate(bars, n)
    out = root / "var" / "reports" / "owner_rules_2026-10-17.json"
    out.write_text(json.dumps(rep, indent=1, default=str))
    for k in ("R1_spot_volgate", "R2_futures_direction_5x"):
        luck.record_trial(reg, "owner_rules", f"CLO-46:{k}", k, {"band": BAND, "rows": ROWS, "window_bars": WINDOW_BARS},
                          "BTC 1h proxy 2023-2026", "PASS" if rep[k]["pass"] else "FAIL")
    print(json.dumps(rep, indent=1, default=str))
    return rep


if __name__ == "__main__":
    main()
