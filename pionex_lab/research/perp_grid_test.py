"""Q7 / Route 9 (CLO-63): bounded-leverage BTC perp LONG grid, one pre-registered test. Research only: no orders, no keys.

PRE-REGISTERED 2026-10-18 11:05 SAST (machine clock), BEFORE any run of this module. Frozen; a changed idea is a new test.

Step 1, mining of CLO-46 (research/owner_bots_2026-10-17.md, var/reports/owner_rules_2026-10-17.json): no grid parameter (range,
grid count, leverage) separates winners from losers (all |rho| <= 0.11 on total return, p >= 0.48); 90% of the owner's profit was
float (direction), the plain stop-loss grid lost on history (R2 5x direction-gated mean -5.1%/window, 0 liquidations at 5x,
47/97 liquidated at 20x). So the test below adds nothing to the rules and only asks whether a plain, un-gated, stop-protected,
leverage-capped long grid has an after-cost edge. Prior odds of PASS: ~5%.

Rules (all fixed). Data: BTC_USDT 1h Binance PROXY (var/proxy_market.db), the same non-overlapping 14-day windows as
research/owner_rules.py (97 windows, 2023-01 -> 2026-10), run back to back, compounded. Each window: swing/grid.simulate long
grid, band +-8% of the window's first open, 40 rows geometric, stop-loss = bottom*0.97 (a stop on the whole grid, i.e. on every
resting order), closed at window end, fee 0.05%, slip 0.02% on grid fills and 0.05% on market orders. Perp mechanics as in
owner_rules.run_window: notional = L x margin, return on margin = L x sim return - funding 0.03%/day x L x 14d (flat,
charged every day, conservative vs the 2023-26 mean), liquidation at mean(levels)*(1-1/L+0.005) if reached before the stop
(whole margin lost). No directional gate, no regime gate (that is R2/R1, already FAILED).
Leverage rule (fixed grid of 4 candidates, all counted as trials): L = the largest of {5,4,3,2} whose compounded path has max
drawdown <= 35% AND zero liquidations, where the path trough inside each window is eq x (1 + L x (min_equity_ratio - 1)).
If no L qualifies the verdict is FAIL (no bounded leverage meets the drawdown cap).
PASS needs ALL, on the selected L: (G1) >= 40 windows; (G2) mean window return on margin > 0; (G3) block-bootstrap (block 2,
2,000 resamples) 2.5% lower bound of the mean > 0; (G4) compounded max DD <= 35% (by selection) and zero liquidations;
(G5) the mean is >= 0 in each third of the windows (chronological); (G6) mean still > 0 at 2x funding and 4x slippage;
(G7) compounded total return > 0.
Reported, NOT gated: implied 30-day return (mean x 30/14), share of rolling 28-day (2-window) compounded returns >= +100%
(the board target is >= +100% per 30 days at DD <= 35%), worst window, stop-out count, sensitivity at every L.
A PASS goes to Red Team review; it would NOT mean the board target is met unless the +100%/30d share is reported as such.
Trials: 4 (one per L) recorded in var/trials.db after the report is computed.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..swing import grid
from . import luck
from .owner_rules import (BAND, BOOT_BLOCK, BOOT_N, INVEST, MIN_WINDOWS, ROWS, SLIP, SLIP_MKT, STOP, WINDOW_BARS,
                          FUND_PER_DAY, load_ohlc, windows)

LEVERAGES = (5, 4, 3, 2)
DD_CAP = 0.35


def run_window(w, lev, slip=SLIP, slip_market=SLIP_MKT, fund=FUND_PER_DAY):
    p0 = w[0][1]
    bottom, top = p0 * (1 - BAND), p0 * (1 + BAND)
    lv = grid.levels(bottom, top, ROWS, "geometric")
    stop = bottom * STOP
    liq = sum(lv) / len(lv) * (1 - 1.0 / lev + 0.005)
    stop = max(stop, liq)
    r = grid.simulate(w, bottom, top, ROWS, INVEST, "geometric", slip=slip, slip_market=slip_market, stop_price=stop)
    if r["exit"] == "stop_loss" and liq >= bottom * STOP:
        return {"ret": -1.0, "trough": 0.0, "liq": True, "stop": True}
    cost = fund * (WINDOW_BARS / 24) * lev
    ret = max(lev * r["return"] - cost, -1.0)
    trough = max(1 + lev * (r["min_equity_ratio"] - 1) - cost, 0.0)
    return {"ret": ret, "trough": min(trough, 1 + ret), "liq": False, "stop": r["exit"] == "stop_loss"}


def path(res):
    eq, peak, dd = 1.0, 1.0, 0.0
    for r in res:
        dd = max(dd, 1 - eq * r["trough"] / peak)
        eq *= 1 + r["ret"]
        peak = max(peak, eq)
        dd = max(dd, 1 - eq / peak)
    return {"total_return": eq - 1, "max_dd": dd}


def evaluate(bars, n_trials):
    ws = [w for _i, w in windows(bars)]
    out = {}
    for L in LEVERAGES:
        res = [run_window(w, L) for w in ws]
        rets = [r["ret"] for r in res]
        p = path(res)
        roll = [(1 + rets[k]) * (1 + rets[k + 1]) - 1 for k in range(len(rets) - 1)]
        third = len(rets) // 3
        thirds = [sum(rets[a:b]) / (b - a) for a, b in ((0, third), (third, 2 * third), (2 * third, len(rets)))]
        res2 = [run_window(w, L, slip=SLIP * 4, slip_market=SLIP_MKT * 4, fund=FUND_PER_DAY * 2) for w in ws]
        out[L] = {"windows": len(rets), "mean": sum(rets) / len(rets), "median": sorted(rets)[len(rets) // 2],
                  "worst": min(rets), "best": max(rets), "liquidations": sum(r["liq"] for r in res),
                  "stops": sum(r["stop"] for r in res), "thirds_mean": thirds,
                  "mean_costs_stressed": sum(r["ret"] for r in res2) / len(res2),
                  "implied_30d": sum(rets) / len(rets) * 30 / 14,
                  "share_28d_ge_100pct": sum(1 for x in roll if x >= 1.0) / max(1, len(roll)),
                  **p, "boot_lower_bps": luck.block_bootstrap(rets, BOOT_BLOCK, BOOT_N)["mean_lower_bps"]}
    ok = [L for L in LEVERAGES if out[L]["max_dd"] <= DD_CAP and out[L]["liquidations"] == 0]
    sel = ok[0] if ok else None
    gates = None
    verdict = "FAIL"
    if sel is not None:
        s = out[sel]
        gates = {"G1_windows": s["windows"] >= MIN_WINDOWS, "G2_mean_pos": s["mean"] > 0,
                 "G3_boot_lower_pos": s["boot_lower_bps"] > 0,
                 "G4_dd_liq": s["max_dd"] <= DD_CAP and s["liquidations"] == 0,
                 "G5_thirds": all(t >= 0 for t in s["thirds_mean"]), "G6_stressed": s["mean_costs_stressed"] > 0,
                 "G7_total_pos": s["total_return"] > 0}
        verdict = "PASS" if all(gates.values()) else "FAIL"
    return {"n_trials_before": n_trials, "selected_leverage": sel, "gates": gates, "verdict": verdict,
            "by_leverage": out, "span": [ws[0][0][0], ws[-1][-1][0]]}


def main():
    root = Path(__file__).resolve().parents[2]
    reg = root / "var" / "trials.db"
    rep = evaluate(load_ohlc(root / "var" / "proxy_market.db"), luck.trial_count(reg))
    (root / "var" / "reports" / "perp_grid_2026-10-18.json").write_text(json.dumps(rep, indent=1, default=str))
    for L in LEVERAGES:
        luck.record_trial(reg, "perp_grid", f"CLO-63:L{L}", f"perp_grid_L{L}", {"band": BAND, "rows": ROWS, "lev": L},
                          "BTC 1h proxy 2023-2026", rep["verdict"] if L == rep["selected_leverage"] else "n/a")
    print(json.dumps(rep, indent=1, default=str))
    return rep


if __name__ == "__main__":
    main()
