"""BTC swing rules v1: the user's checklist as fixed rules, tested long AND short (research only).

Pre-registered 2026-10-13, before any result. Separate from the paper lab's spot/long-only/4h
mandate: this studies signals for the user's own manual futures trading. It places no orders.

At each completed 4H bar (all inputs point-in-time):
  trend      daily close vs daily EMA50, with the EMA50 rising (long) / falling (short) over 5 days
  bias       anchored VWAPs from the latest CONFIRMED major 4H swing high and swing low (k x ATR
             zigzag): price above both = long bias, below both = short bias
  entry      pullback into the nearer AVWAP (bar extreme within 0.5 ATR of it) and a close back
             beyond it in the trend direction (green bar for longs, red for shorts)
  room       nearest opposite level among the 10 most recent confirmed swings at least 1 ATR away
  elliott    Wave Lab primary 4H count must not be in a driving wave (3/5/C) against the trade
  events     no entries within 12h of a US CPI release (08:30 New York) or FOMC decision (14:00)
  exits      stop = stop_atr x ATR, target = rr x risk, time exit after `hold` 4H bars (<= 3 days);
             simulated on 1h bars after entry, stop first when stop and target share a bar
  costs      Pionex futures taker 0.05%/side + 2 bps slippage/side + funding (Binance history)
Grid (16 configs): k in {4, 6}, stop_atr in {1.5, 2.5}, rr in {1.5, 2.5}, hold in {12, 18}.
Walk-forward and gates as in the lab's research (3 folds + untouched final window).
"""
from __future__ import annotations

import bisect
import itertools
import json
import math
from datetime import date, datetime, timedelta, timezone

from ..data.store import resample
from ..research import metrics
from ..strategies.catalog import _zigzag, align_context
from ..strategies.indicators import atr, ema
from ..waves.elliott import analyze

RULES = "btc-swing v1 (pre-registered 2026-10-13)"
GRID = [dict(zip(("k", "stop_atr", "rr", "hold"), v)) for v in itertools.product((4.0, 6.0), (1.5, 2.5), (1.5, 2.5), (12, 18))]
FEE_BPS, SLIP_BPS = 5.0, 2.0
H4, H1 = 14_400_000, 3_600_000
CPI = """2023-04-12 2023-05-10 2023-06-13 2023-07-12 2023-08-10 2023-09-13 2023-10-12 2023-11-14 2023-12-12
2024-01-11 2024-02-13 2024-03-12 2024-04-10 2024-05-15 2024-06-12 2024-07-11 2024-08-14 2024-09-11 2024-10-10
2024-11-13 2024-12-11 2025-01-15 2025-02-12 2025-03-12 2025-04-10 2025-05-13 2025-06-11 2025-07-15 2025-08-12
2025-09-11 2025-10-24 2025-12-18 2026-01-13 2026-02-13 2026-03-11 2026-04-10 2026-05-12 2026-06-10 2026-07-14
2026-08-12 2026-09-11 2026-10-14 2026-11-10 2026-12-10""".split()          # bls.gov release archive and schedule
FOMC = """2023-05-03 2023-06-14 2023-07-26 2023-09-20 2023-11-01 2023-12-13 2024-01-31 2024-03-20 2024-05-01
2024-06-12 2024-07-31 2024-09-18 2024-11-07 2024-12-18 2025-01-29 2025-03-19 2025-05-07 2025-06-18 2025-07-30
2025-09-17 2025-10-29 2025-12-10 2026-01-28 2026-03-18 2026-04-29 2026-06-17 2026-07-29 2026-09-16 2026-10-28
2026-12-09""".split()                                           # federalreserve.gov FOMC calendars


def _ny_ms(day: str, hh: int, mm: int) -> int:
    """New York local time on `day` in UTC ms (US DST: 2nd Sunday of March to 1st Sunday of November)."""
    d = date.fromisoformat(day)

    def nth_sunday(y, m, n):
        f = date(y, m, 1)
        return f + timedelta(days=(6 - f.weekday()) % 7 + 7 * (n - 1))
    off = 4 if nth_sunday(d.year, 3, 2) <= d < nth_sunday(d.year, 11, 1) else 5
    return int(datetime(d.year, d.month, d.day, hh + off, mm, tzinfo=timezone.utc).timestamp() * 1000)


EVENTS = sorted([_ny_ms(d, 8, 30) for d in CPI] + [_ny_ms(d, 14, 0) for d in FOMC])


def near_event(t_ms: int, hours: float = 12) -> bool:
    return any(abs(t_ms - e) <= hours * H1 for e in EVENTS)


def prepare(b1h, funding=None, elliott=True) -> dict:
    """Point-in-time features per completed 4H bar, from 1h bars (oldest first)."""
    b4, bd = resample(b1h, "4H"), resample(b1h, "1D")
    a4, ed = atr(b4.h, b4.l, b4.c, 14), ema(bd.c, 50)
    jd = align_context(b4.t, bd.t, H4, 86_400_000)
    tp = [(h + l + c) / 3 for h, l, c in zip(b4.h, b4.l, b4.c)]
    pv, vv = [0.0], [0.0]
    for x, v in zip(tp, b4.v):
        pv.append(pv[-1] + x * v)
        vv.append(vv[-1] + v)
    piv = {k: _zigzag(b4.h, b4.l, a4, k) for k in (4.0, 6.0)}
    known = {}
    for k, pv_ in piv.items():                     # number of pivots confirmed by each bar's close
        cnt, n = [0] * len(b4), 0
        for i in range(len(b4)):
            while n < len(pv_) and pv_[n][3] <= i:
                n += 1
            cnt[i] = n
        known[k] = cnt
    ft = [t for t, _ in (funding or [])]
    fc = [0.0]
    for _, r in (funding or []):
        fc.append(fc[-1] + r)
    ell = [None] * len(b4)
    if elliott:
        for i in range(200, len(b4)):
            s = max(0, i - 299)
            p = analyze(b4.t[s:i + 1], b4.o[s:i + 1], b4.h[s:i + 1], b4.l[s:i + 1], b4.c[s:i + 1],
                        degree="intermediate", history=False).get("primary")
            if p and str(p["current_wave"]) in ("3", "5", "C"):
                ell[i] = p["move"]                     # direction of a driving wave in progress
    idx1 = {t: k for k, t in enumerate(b1h.t)}
    return {"b4": b4, "b1": b1h, "atr": a4, "ema_d": ed, "jd": jd, "bd": bd, "pv": pv, "vv": vv, "piv": piv,
            "known": known, "ell": ell, "idx1": idx1, "fund_t": ft, "fund_cum": fc}


def funding_between(d, t0, t1) -> float:
    """Sum of funding rates settled in (t0, t1]."""
    ft, fc = d["fund_t"], d["fund_cum"]
    return fc[bisect.bisect_right(ft, t1)] - fc[bisect.bisect_right(ft, t0)]


def _avwap(d, a, i):
    v = d["vv"][i + 1] - d["vv"][a]
    return (d["pv"][i + 1] - d["pv"][a]) / v if v > 0 else math.nan


def signal(d, i, p):
    """'LONG'/'SHORT' with (stop, target) at 4H bar i, or None. Uses only data known at its close."""
    b, a = d["b4"], d["atr"][i]
    j = d["jd"][i]
    if j < 55 or not (a == a) or a <= 0 or near_event(b.t[i] + H4):
        return None
    ed = d["ema_d"]
    bull = d["bd"].c[j] > ed[j] and ed[j] > ed[j - 5]
    bear = d["bd"].c[j] < ed[j] and ed[j] < ed[j - 5]
    if not (bull or bear):
        return None
    recent = d["piv"][p["k"]][max(0, d["known"][p["k"]][i] - 20):d["known"][p["k"]][i]]   # confirmed by bar i
    hs, ls = [x for x in recent if x[2] == "H"][-10:], [x for x in recent if x[2] == "L"][-10:]
    if not hs or not ls:
        return None
    vh, vl = _avwap(d, hs[-1][0], i), _avwap(d, ls[-1][0], i)
    c, lo, hi = b.c[i], b.l[i], b.h[i]
    if bull and c > vh and c > vl:
        sup = max(vh, vl)
        if lo > sup + 0.5 * a or c <= sup or c <= b.o[i] or d["ell"][i] == "down":
            return None
        above = [x[1] for x in hs if x[1] > c]
        if above and min(above) - c < a:
            return None
        side, stop = "LONG", c - p["stop_atr"] * a
    elif bear and c < vh and c < vl:
        res = min(vh, vl)
        if hi < res - 0.5 * a or c >= res or c >= b.o[i] or d["ell"][i] == "up":
            return None
        below = [x[1] for x in ls if x[1] < c]
        if below and c - max(below) < a:
            return None
        side, stop = "SHORT", c + p["stop_atr"] * a
    else:
        return None
    risk = abs(c - stop)
    return side, stop, c + p["rr"] * risk if side == "LONG" else c - p["rr"] * risk


def simulate(d, p, start, end, cost_mult=1.0, delay_h=0):
    """Trades for 4H decision bars in [start, end); exits on 1h bars; one position at a time."""
    b4, b1, out, i = d["b4"], d["b1"], [], max(start, 210)
    fee = (FEE_BPS + SLIP_BPS) * cost_mult / 1e4
    while i < min(end, len(b4) - 1):
        sig = signal(d, i, p)
        if not sig:
            i += 1
            continue
        side, stop, target = sig
        k = d["idx1"].get(b4.t[i] + H4)
        if k is None or k + delay_h >= len(b1.t):
            i += 1
            continue
        k += delay_h
        entry, t_entry, s = b1.o[k], b1.t[k], 1 if side == "LONG" else -1
        last = k + p["hold"] * 4 - 1
        exit_px = exit_k = None
        for m in range(k, min(last + 1, len(b1.t))):
            if (b1.l[m] <= stop) if s > 0 else (b1.h[m] >= stop):
                exit_px, exit_k = stop, m
                break
            if (b1.h[m] >= target) if s > 0 else (b1.l[m] <= target):
                exit_px, exit_k = target, m
                break
        if exit_px is None:
            exit_k = min(last, len(b1.t) - 1)
            exit_px = b1.c[exit_k]
        t_exit = b1.t[exit_k] + H1
        gross = s * (exit_px / entry - 1)
        funding = funding_between(d, t_entry, t_exit) * s           # longs pay positive funding
        net = gross - 2 * fee - funding * cost_mult
        out.append({"entry_time": t_entry, "exit_time": t_exit, "side": side, "gross_bps": gross * 1e4,
                    "net_bps": net * 1e4, "symbol": "BTC_USDT", "strategy": RULES})
        i = max(i + 1, next((q for q in range(i + 1, len(b4)) if b4.t[q] >= t_exit), len(b4)))
    return out


def walk_forward(d, alpha_configs=len(GRID)) -> dict:
    """Lab-style evaluation: 3 rolling folds + untouched final 25%, best config chosen on train."""
    n = len(d["b4"])
    t0, dev = 210, 210 + (n - 210) * 3 // 4
    chunk = (dev - t0) // 4
    bounds = [t0 + k * chunk for k in range(4)] + [dev]
    emb = 18                                                    # embargo = max holding (bars)

    def best(lo, hi):
        scored = [(metrics.summarize(simulate(d, p, lo, hi)), p) for p in GRID]
        ok = [(s, p) for s, p in scored if s["n"] >= 20]
        return max(ok, key=lambda x: x[0]["expectancy_bps"])[1] if ok else None
    oos, stress, folds, notes = [], [], [], []
    for f in range(1, 4):
        p = best(bounds[0], bounds[f])
        if p is None:
            folds.append(0.0)
            notes.append(f"fold{f}: no config with >= 20 train trades")
            continue
        tr = simulate(d, p, bounds[f] + emb, bounds[f + 1])
        oos += tr
        stress += simulate(d, p, bounds[f] + emb, bounds[f + 1], cost_mult=2.0, delay_h=1)
        folds.append(sum(t["net_bps"] for t in tr))
        notes.append(f"fold{f}: {p}, {len(tr)} trades")
    final = best(t0, dev)
    test = simulate(d, final, dev + emb, n) if final else []
    if final:
        stress += simulate(d, final, dev + emb, n, cost_mult=2.0, delay_h=1)
    allt = oos + test
    net, gross, st = metrics.summarize(allt), metrics.summarize(allt, "gross_bps"), metrics.summarize(stress)
    lower = metrics.block_bootstrap_lower(allt, 0.05 / alpha_configs)
    pos, nf = metrics.fold_positive(folds)
    gates = {"min_oos_trades": net["n"] >= 200, "min_oos_days": net["span_days"] >= 60,
             "positive_expectancy": (net["expectancy_bps"] or 0) > 0,
             "profit_factor": (net["profit_factor"] or 0) >= 1.2, "fold_consistency": pos >= 2,
             "bootstrap_lower_bound": lower is not None and lower > 0, "cost_stress": st["n"] > 0 and st["total_bps"] > 0,
             "without_best_trade": net["n"] > 0 and net["total_minus_best_bps"] >= 0}
    failed = [k for k, v in gates.items() if not v]
    status = ("QUALIFIED" if not failed else "INSUFFICIENT_DATA" if set(failed) <= {"min_oos_trades", "min_oos_days"}
              or net["n"] == 0 else "REJECTED")
    sides = {s: metrics.summarize([t for t in allt if t["side"] == s]) for s in ("LONG", "SHORT")}
    return {"rules": RULES, "status": status, "failed": failed, "final_params": final, "fold_notes": notes,
            "fold_totals_bps": folds, "oos_net": net, "oos_gross": gross, "stress": st, "bootstrap_lower_bps": lower,
            "by_side": sides, "test_trades": len(test)}


def run(paths, cfg) -> dict:
    from ..cli import _universe_bars
    from ..data.proxy import funding_series
    from ..data.store import MarketView
    u, _ = _universe_bars(paths, cfg, "1h", "proxy")
    b1 = u["BTC_USDT"][0]
    fund = funding_series(MarketView(paths.proxy_market).conn, "BTC_USDT")
    out = walk_forward(prepare(b1, fund))
    out["data"] = {"bars_1h": len(b1), "from": b1.t[0], "to": b1.t[-1], "events": len(EVENTS)}
    dst = paths.reports / "btc_swing_v1.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    return out
