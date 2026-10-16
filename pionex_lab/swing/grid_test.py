"""CLO-21 (2b): sideways-pair spot grid, walk-forward, pre-registered. Research only: no order path, no keys.
PROXY data (Binance spot 1h archives held in var/alpha/*.db, var/proxy_market.db). Not proof of profit.

PRE-REGISTERED 2026-10-16 20:59 SAST (machine clock), committed before the first run. Nothing below changes after a
result; a changed idea is a new test. One parameter set, no grid search, run ONCE. (The only thing looked at before
this registration: how many 14-day windows pass a few screen threshold pairs, counts only, no returns; the loosest
pair was taken to get enough windows. Disclosed.)

WHAT IS STRUCTURALLY DIFFERENT from the range-reversion and Bollinger-reversion tests that FAILED (STRATEGY_LOG):
those were one position at a time, entered by market order on a signal, paying ~0.16%/trade, and they needed a
directional call at the band edge. A grid posts resting limit orders at ~50 levels at once, earns every small
oscillation (also those too small for any single entry rule) at a spacing fixed at >= 3x the round-trip cost, and needs
no prediction of the next move, only that price keeps moving back and forth inside the range. Its risk is the
opposite one: a breakout down leaves a bag of inventory bought on the way, a breakout up leaves cash. Whether the
grid income pays for that is exactly what the test measures. Known optimism of the simulator: touch fill (no queue),
unknown path inside a 1h candle.

UNIVERSE (fixed, written down first): the 10 USDT pairs of the CTA basket: BTC ETH SOL XRP DOGE LINK ADA BNB AVAX
LTC. They are the large pairs by 30-day Pionex/Binance volume for which 1h archives exist for 2021-2026; a ranking by
Pionex's own 30-day volume is not available historically, so this is the proxy for "top pairs by volume" and the
list is fixed here, not ranked per window (survivors by construction: a stated bias in favour of the grid, since a
dying pair is a bag).

DECISIONS: calendar days 2021-01-01 00:00 UTC + 14k days (k = 0, 1, ...), as long as the 14-day window ends on or
before the last bar. For each coin separately, on closed daily bars through day t-1 (daily bars built from the 1h
bars, UTC days), the screen is:
    ATR14%  = mean true range of the last 14 days / close(t-1)        <= 4.0%
    BW      = (upper - lower) / mean of the Bollinger(20, 2) bands    <= 0.25   (population std, 20 closes)
Needs 20 consecutive prior daily bars, else no decision. If the screen passes, ONE grid of 1000 USDT:
    top = BB upper + 0.5 * ATR14 ; bottom = BB lower - 0.5 * ATR14 (must be > 0)
    type geometric ; rows = min(200, 100, floor(ln(top/bottom) / ln(1 + 3 * RT)))   with RT = 2 * (fee + slip) =
    0.0014 (round-trip cost), so the step is at least 3 x RT = 0.42% and each grid holds >= 10 USDT; skip if rows < 2
    stop-loss price = bottom - 1.0 * ATR14 ; no take-profit ; close on exit (sell all base at the window's last
    close) after 14 days (336 hourly bars); the grid starts at the open of day t (decided before it).
Windows run one per coin per calendar slot; a stopped grid waits for the next slot. Windows with fewer than 320 of
336 bars are skipped and counted.
COSTS: fee 0.05% per fill; slip 0.02% against us on every grid fill; 0.05% on market orders (initial buy, stop,
close). Stress arm (reported, not gating): slip 0.08%, market slip 0.20%. Cash earns 0%.
SIMULATOR: pionex_lab/swing/grid.py (tested, tests/test_grid.py). Grid profit and float profit are reported
separately as Pionex defines them.

COMPARATORS: (a) cash, 0 per window. (b) buy-and-hold of the same coin over the same window, paying the same entry
and exit costs (pairwise, reported). (c) for drawdown: an equal-weight buy-and-hold of the coins that have data,
rebalanced every 14-day slot, costless (generous to buy-and-hold) vs the grid book: the same coins, each slot's
capital in its grid when screened and in cash when not, daily marks, same rebalancing.

GATES (all must hold for PASS; FAIL if a gate fails and it is evaluable; INSUFFICIENT if a gate cannot be evaluated):
  G1  at least 100 grid windows in total, and at least 10 in each calendar third of the window range, else INSUFFICIENT.
  G2  mean after-cost return per grid window > 0 (cash) AND the lower bound of the cluster bootstrap (resample the
      14-day calendar slots with all their windows, 20,000 draws, seed 20261016) at quantile 0.05 / 4 = 0.0125 is > 0.
      (4 = the grid-family tests reserved under CLO-19: this one, futures grid, trailing grid, one spare; Bonferroni.)
  G3  max drawdown of the grid book <= max drawdown of the equal-weight buy-and-hold book.
  G4  mean return per window > 0 in each of the three calendar thirds (slots split into equal thirds).
Reported, not gating: mean excess over same-coin buy-and-hold and its bootstrap lower bound, win rate, grid vs float
profit split, exit reasons, per-coin table, stress arm. A PASS goes to the Red Team; it is not closed by the quant.
"""
from __future__ import annotations

import json
import math
import random
import sqlite3
import statistics
from datetime import datetime, timezone
from pathlib import Path

from . import grid

HOUR, DAY = 3_600_000, 86_400_000
COINS = ("BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", "DOGE_USDT", "LINK_USDT", "ADA_USDT", "BNB_USDT",
         "AVAX_USDT", "LTC_USDT")
START = int(datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
SLOT_DAYS, WINDOW_BARS, MIN_BARS = 14, 336, 320
ATR_MAX, BW_MAX, K_ATR, STOP_ATR = 0.04, 0.25, 0.5, 1.0
INVEST, MAX_ROWS, STEP_MULT = 1000.0, 200, 3.0
FEE, SLIP, SLIP_MKT = 0.0005, 0.0002, 0.0005
STRESS = (0.0008, 0.0020)
RT = 2 * (FEE + SLIP)
MIN_WINDOWS, MIN_THIRD = 100, 10
BOOT_N, BOOT_SEED, BOOT_Q = 20_000, 20261016, 0.05 / 4
CUTOVER = int(datetime(2023, 4, 1, tzinfo=timezone.utc).timestamp() * 1000)
SOURCES = (("var/alpha/early_1h.db", 0, CUTOVER), ("var/alpha/alts_1h.db", CUTOVER, 10 ** 15),
           ("var/proxy_market.db", CUTOVER, 10 ** 15))


# ---- data ----------------------------------------------------------------------------------------------
def load_hourly(root, coin):
    """{t ms: (o, h, l, c)}: early_1h before 2023-04-01, alts_1h (alts) or proxy_market.db (BTC, ETH) after."""
    out = {}
    for rel, lo, hi in SOURCES:
        con = sqlite3.connect(str(Path(root) / rel))
        for t, o, h, l, c in con.execute("SELECT open_time, open, high, low, close FROM klines WHERE symbol=? "
                                         "AND interval='60M' AND open_time>=? AND open_time<? ORDER BY open_time",
                                         (coin, lo, hi)):
            out[t] = (float(o), float(h), float(l), float(c))
        con.close()
    return out


def daily_bars(hourly):
    """{day t ms: [o, h, l, c, n_hours]} UTC days."""
    days = {}
    for t in sorted(hourly):
        o, h, l, c = hourly[t]
        d = t // DAY * DAY
        x = days.setdefault(d, [o, h, l, c, 0])
        x[1], x[2], x[3], x[4] = max(x[1], h), min(x[2], l), c, x[4] + 1
    return days


# ---- screen and config -----------------------------------------------------------------------------------
def screen(days, t):
    """Indicators on closed daily bars through t-1, or None if 20 consecutive prior days are missing."""
    prior = [t - k * DAY for k in range(20, 0, -1)]
    if any(d not in days for d in prior) or (t - 21 * DAY) not in days:
        return None
    closes = [days[d][3] for d in prior]
    chain = [t - k * DAY for k in range(15, 0, -1)]
    tr = []
    for d in chain[1:]:
        h, l, pc = days[d][1], days[d][2], days[d - DAY][3]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(tr[-14:]) / 14
    mu = sum(closes) / 20
    sd = statistics.pstdev(closes)
    upper, lower = mu + 2 * sd, mu - 2 * sd
    return {"atr": atr, "atr_pct": atr / closes[-1], "bw": (upper - lower) / mu, "upper": upper, "lower": lower}


def config(s):
    """Grid config from the screen indicators, or None if the cost rule leaves fewer than 2 rows."""
    top, bottom = s["upper"] + K_ATR * s["atr"], s["lower"] - K_ATR * s["atr"]
    if bottom <= 0 or top <= bottom:
        return None
    rows = min(MAX_ROWS, int(INVEST // grid.MIN_GRID_USDT), int(math.log(top / bottom) / math.log(1 + STEP_MULT * RT)))
    if rows < 2:
        return None
    return {"top": top, "bottom": bottom, "rows": rows, "grid_type": "geometric",
            "step_pct": grid.step_pct(bottom, top, rows, "geometric"), "stop_price": bottom - STOP_ATR * s["atr"]}


def passes(s):
    return s is not None and s["atr_pct"] <= ATR_MAX and s["bw"] <= BW_MAX


# ---- one window ------------------------------------------------------------------------------------------
def window_bars(hourly, t):
    ts = [t + i * HOUR for i in range(WINDOW_BARS)]
    bars = [(x,) + hourly[x] for x in ts if x in hourly]
    return bars if len(bars) >= MIN_BARS else None


def run_window(bars, cfg, slip=SLIP, slip_market=SLIP_MKT):
    r = grid.simulate(bars, cfg["bottom"], cfg["top"], cfg["rows"], INVEST, cfg["grid_type"], fee=FEE, slip=slip,
                      slip_market=slip_market, stop_price=cfg["stop_price"], mark_every=24)
    marks = r["marks"] + [r["marks"][-1]] * max(0, SLOT_DAYS - len(r["marks"]))
    r["marks"] = marks[:SLOT_DAYS]
    return r


def hold_return(bars):
    return bars[-1][4] * (1 - SLIP_MKT) * (1 - FEE) / (bars[0][1] * (1 + SLIP_MKT) * (1 + FEE)) - 1


def hold_marks(bars):
    """Relative close at each of the 14 daily marks (no cost)."""
    o = bars[0][1]
    pts = [bars[min(len(bars) - 1, (k + 1) * 24 - 1)][4] / o for k in range(SLOT_DAYS)]
    return pts


# ---- statistics ------------------------------------------------------------------------------------------
def cluster_bootstrap_lower(by_slot, q=BOOT_Q, n=BOOT_N, seed=BOOT_SEED):
    """by_slot: {slot: [window returns]}. Resample slots with replacement; mean over all windows drawn.
    Returns (lower q-quantile, median) of the resampled mean."""
    slots = sorted(by_slot)
    sums = [sum(by_slot[s]) for s in slots]
    cnts = [len(by_slot[s]) for s in slots]
    rng = random.Random(seed)
    m = len(slots)
    means = []
    for _ in range(n):
        tot = cnt = 0
        for _k in range(m):
            j = rng.randrange(m)
            tot += sums[j]
            cnt += cnts[j]
        means.append(tot / cnt if cnt else 0.0)
    means.sort()
    return means[int(q * (n - 1))], means[n // 2]


def max_drawdown(curve):
    peak, dd = 1.0, 0.0
    for x in curve:
        peak = max(peak, x)
        dd = max(dd, 1 - x / peak)
    return dd


def book_curves(slots, coins_by_slot, win, hold):
    """Daily equity curves of the grid book and the buy-and-hold book, chained over the 14-day slots.
    win[(slot, coin)] = marks of a grid window; hold[(slot, coin)] = relative closes of the coin's hold path."""
    g = h = 1.0
    gc, hc = [], []
    for s in slots:
        coins = coins_by_slot[s]
        if not coins:
            continue
        for k in range(SLOT_DAYS):
            hv = sum(hold[(s, c)][k] for c in coins) / len(coins)
            gv = sum(win[(s, c)][k] if (s, c) in win else 1.0 for c in coins) / len(coins)
            gc.append(g * gv)
            hc.append(h * hv)
        g *= sum(win[(s, c)][-1] if (s, c) in win else 1.0 for c in coins) / len(coins)
        h *= sum(hold[(s, c)][-1] for c in coins) / len(coins)
    return gc, hc


# ---- the run ---------------------------------------------------------------------------------------------
def run(root, out_path=None):
    data = {c: load_hourly(root, c) for c in COINS}
    days = {c: daily_bars(data[c]) for c in COINS}
    last_bar = max(max(d) for d in data.values())
    slots, t = [], START
    while t + WINDOW_BARS * HOUR <= last_bar + HOUR:
        slots.append(t)
        t += SLOT_DAYS * DAY
    wins, wins_stress, win_marks, hold_marks_ = [], [], {}, {}
    coins_by_slot = {i: [] for i in range(len(slots))}
    skipped = {"short_window": 0, "no_screen": 0, "rows": 0, "screened_out": 0}
    for i, t in enumerate(slots):
        for c in COINS:
            bars = window_bars(data[c], t)
            if bars is None:
                skipped["short_window"] += 1
                continue
            coins_by_slot[i].append(c)
            hold_marks_[(i, c)] = hold_marks(bars)
            s = screen(days[c], t)
            if s is None:
                skipped["no_screen"] += 1
                continue
            if not passes(s):
                skipped["screened_out"] += 1
                continue
            cfg = config(s)
            if cfg is None:
                skipped["rows"] += 1
                continue
            r = run_window(bars, cfg)
            rs = run_window(bars, cfg, *STRESS)
            win_marks[(i, c)] = r["marks"]
            rec = {"slot": i, "t": datetime.fromtimestamp(t / 1000, timezone.utc).date().isoformat(), "coin": c,
                   "atr_pct": s["atr_pct"], "bw": s["bw"], "top": cfg["top"], "bottom": cfg["bottom"],
                   "rows": cfg["rows"], "step_pct": cfg["step_pct"], "stop": cfg["stop_price"],
                   "ret": r["return"], "grid_profit": r["grid_profit"], "float_profit": r["float_profit"],
                   "round_trips": r["round_trips"], "exit": r["exit"], "hold_ret": hold_return(bars),
                   "ret_stress": rs["return"]}
            wins.append(rec)
    n_slots = len(slots)
    third = lambda i: min(2, i * 3 // n_slots)
    by_slot, by_slot_ex = {}, {}
    for w in wins:
        by_slot.setdefault(w["slot"], []).append(w["ret"])
        by_slot_ex.setdefault(w["slot"], []).append(w["ret"] - w["hold_ret"])
    mean = lambda xs: sum(xs) / len(xs) if xs else float("nan")
    rets = [w["ret"] for w in wins]
    lb, med = cluster_bootstrap_lower(by_slot) if wins else (float("nan"), float("nan"))
    lb_ex, _ = cluster_bootstrap_lower(by_slot_ex) if wins else (float("nan"), float("nan"))
    thirds = []
    for k in range(3):
        ws = [w for w in wins if third(w["slot"]) == k]
        thirds.append({"n": len(ws), "mean_ret": mean([w["ret"] for w in ws]),
                       "mean_excess_vs_hold": mean([w["ret"] - w["hold_ret"] for w in ws])})
    gc, hc = book_curves(range(n_slots), coins_by_slot, win_marks, hold_marks_)
    dd_g, dd_h = max_drawdown(gc), max_drawdown(hc)
    per_coin = {}
    for c in COINS:
        ws = [w for w in wins if w["coin"] == c]
        per_coin[c] = {"n": len(ws), "mean_ret": mean([w["ret"] for w in ws]),
                       "mean_hold": mean([w["hold_ret"] for w in ws])}
    g1 = len(wins) >= MIN_WINDOWS and all(t_["n"] >= MIN_THIRD for t_ in thirds)
    g2 = bool(wins) and mean(rets) > 0 and lb > 0
    g3 = dd_g <= dd_h
    g4 = all(t_["n"] > 0 and t_["mean_ret"] > 0 for t_ in thirds)
    verdict = "INSUFFICIENT" if not g1 else ("PASS" if (g2 and g3 and g4) else "FAIL")
    gp = sum(w["grid_profit"] for w in wins)
    fp = sum(w["float_profit"] for w in wins)
    exits = {}
    for w in wins:
        exits[w["exit"]] = exits.get(w["exit"], 0) + 1
    report = {
        "test": "CLO-21 sideways-pair spot grid", "data": "PROXY (Binance 1h archives)", "verdict": verdict,
        "gates": {"G1_enough_windows": g1, "G2_mean_gt_cash_with_bootstrap_lb": g2, "G3_maxdd_le_hold": g3,
                  "G4_each_third_positive": g4},
        "slots": n_slots, "windows": len(wins), "skipped": skipped,
        "mean_ret": mean(rets), "median_ret": statistics.median(rets) if rets else None, "boot_lb_q": BOOT_Q,
        "boot_lb": lb, "boot_median": med, "win_rate": mean([1.0 if r > 0 else 0.0 for r in rets]),
        "mean_hold_ret": mean([w["hold_ret"] for w in wins]),
        "mean_excess_vs_hold": mean([w["ret"] - w["hold_ret"] for w in wins]), "boot_lb_excess_vs_hold": lb_ex,
        "grid_profit_total_usdt": gp, "float_profit_total_usdt": fp, "exits": exits,
        "mean_ret_stress": mean([w["ret_stress"] for w in wins]),
        "maxdd_grid_book": dd_g, "maxdd_hold_book": dd_h,
        "final_grid_book": gc[-1] if gc else None, "final_hold_book": hc[-1] if hc else None,
        "thirds": thirds, "per_coin": per_coin,
        "candidates_now": candidates_now(days, data),
        "windows_detail": wins,
    }
    if out_path:
        Path(out_path).write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report


def candidates_now(days, data):
    """Per pair: screen and grid config computed on the daily bars through the last complete day."""
    out = {}
    for c in COINS:
        last = max(d for d in days[c] if days[c][d][4] == 24)
        t = last + DAY
        s = screen(days[c], t)
        cfg = config(s) if s else None
        out[c] = {"as_of_decision_day": datetime.fromtimestamp(t / 1000, timezone.utc).date().isoformat(),
                  "indicators": s, "sideways": passes(s), "config": cfg,
                  "stop_loss": cfg["stop_price"] if cfg else None}
    return out


if __name__ == "__main__":
    import sys
    root = Path(__file__).resolve().parents[2]
    rep = run(root, root / "var" / "reports" / "grid_test.json" if "--write" in sys.argv else None)
    keep = {k: v for k, v in rep.items() if k not in ("windows_detail", "candidates_now", "per_coin")}
    print(json.dumps(keep, indent=1))
