"""Daily trend filter, spot long-only, multi-day holds: does it beat simply holding? (research only)

Pre-registered 2026-10-13 before any result. Outside the lab mandate (holds last days to weeks, the
mandate allows 4h), so nothing here trades. Data: Binance spot 1h (labelled PROXY) resampled to UTC days.
Rules, decided on a completed daily close and executed at the next day's open (00:00 UTC):
  ema50      hold while the daily close is above its 50-day EMA (the user's own trend line), else cash
  sma20_100  hold while the 20-day SMA is above the 100-day SMA, else cash
  hold       buy at the first tradable day and hold (benchmark)
Costs: 5 bps fee + 2 bps slippage per side. Cash earns nothing.
Reported per symbol: total return, CAGR, max drawdown, daily Sharpe (no risk-free), time invested,
switches, and each third of the period. The rules are judged useful only if, on BTC and ETH alike,
they beat holding on Sharpe AND max drawdown, and are positive in at least 2 of 3 thirds.
"""
from __future__ import annotations

import json
import math

from ..strategies.indicators import ema

RULES = "daily-trend v1 (pre-registered 2026-10-13)"
SIDE_COST = (5.0 + 2.0) / 1e4
WARMUP = 100


def sma(x, n):
    out, s = [math.nan] * len(x), 0.0
    for i, v in enumerate(x):
        s += v
        if i >= n:
            s -= x[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def positions(c: list, rule: str) -> list:
    """Desired holding (1/0) decided at each day's close."""
    if rule == "hold":
        return [1] * len(c)
    if rule == "ema50":
        e = ema(c, 50)
        return [1 if e[i] == e[i] and c[i] > e[i] else 0 for i in range(len(c))]
    if rule == "sma20_100":
        a, b = sma(c, 20), sma(c, 100)
        return [1 if b[i] == b[i] and a[i] > b[i] else 0 for i in range(len(c))]
    if rule == "ema50_ls":                     # long above the EMA, short below (perpetual, both ways)
        e = ema(c, 50)
        return [0 if e[i] != e[i] else 1 if c[i] > e[i] else -1 for i in range(len(c))]
    raise ValueError(rule)


def backtest(d, rule: str, start: int = WARMUP, end: int | None = None, funding=()) -> dict:
    """d: daily Bars. Position decided at close i-1 is held over day i (open i -> open i+1), for days
    in [start, end). Signals use the whole history up to each close. With `funding` [(t, rate)], an
    open position pays (long) or receives (short) every settlement inside its day; none before the
    funding history starts (Binance perps from 2019-09)."""
    import bisect
    pos = positions(list(d.c), rule)
    ft = [t for t, _ in funding]
    fc = [0.0]
    for _, x in funding:
        fc.append(fc[-1] + x)
    eq, held, switches, cur = [1.0], 0, 0, 0
    rets = []
    for i in range(max(start, WARMUP), min(end or len(d), len(d)) - 1):
        want = pos[i - 1]
        r = 0.0
        if want != cur:
            r -= SIDE_COST * abs(want - cur)
            switches += 1
            cur = want
        if cur:
            r += cur * (d.o[i + 1] / d.o[i] - 1)
            if ft:
                r -= cur * (fc[bisect.bisect_right(ft, d.t[i + 1])] - fc[bisect.bisect_right(ft, d.t[i])])
            held += 1
        rets.append(r)
        eq.append(eq[-1] * (1 + r))
    n = len(rets)
    peak, mdd = 1.0, 0.0
    for v in eq:
        peak = max(peak, v)
        mdd = max(mdd, 1 - v / peak)
    mean = sum(rets) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in rets) / n)
    k = n // 3
    thirds = [math.prod(1 + x for x in part) - 1 for part in (rets[:k], rets[k:2 * k], rets[2 * k:])]
    return {"rule": rule, "total": eq[-1] - 1, "cagr": eq[-1] ** (365.25 / n) - 1, "max_drawdown": mdd,
            "sharpe": mean / sd * math.sqrt(365.25) if sd else None, "time_in": held / n,
            "switches": switches, "thirds": thirds, "days": n}


def vol_scaled(d, start: int, end: int | None = None, target: float = 0.40, window: int = 30) -> dict:
    """ema50 with volatility targeting (pre-registered 2026-10-13 after the OOS pass): while IN, hold
    min(1, target / realised vol) of capital, vol = annualised stdev of the last `window` daily
    close-to-close returns known at the decision close; the size is reset daily and only changes of
    size are charged (7 bps a side on the traded fraction). Pass: on BTC and ETH, in both windows,
    a smaller max drawdown than plain ema50 and a Sharpe at least as high."""
    c = list(d.c)
    pos = positions(c, "ema50")
    eq, cur, rets, held = [1.0], 0.0, [], 0
    for i in range(max(start, WARMUP), min(end or len(d), len(d)) - 1):
        j = i - 1
        rs = [c[q] / c[q - 1] - 1 for q in range(j - window + 1, j + 1)]
        m = sum(rs) / window
        vol = math.sqrt(sum((x - m) ** 2 for x in rs) / window * 365.25)
        want = (min(1.0, target / vol) if vol > 0 else 1.0) if pos[j] else 0.0
        r = -SIDE_COST * abs(want - cur)
        cur = want
        if cur:
            r += cur * (d.o[i + 1] / d.o[i] - 1)
            held += 1
        rets.append(r)
        eq.append(eq[-1] * (1 + r))
    n = len(rets)
    peak, mdd = 1.0, 0.0
    for v in eq:
        peak = max(peak, v)
        mdd = max(mdd, 1 - v / peak)
    mean = sum(rets) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in rets) / n)
    return {"rule": f"ema50_vol{int(target * 100)}", "total": eq[-1] - 1, "cagr": eq[-1] ** (365.25 / n) - 1,
            "max_drawdown": mdd, "sharpe": mean / sd * math.sqrt(365.25) if sd else None, "time_in": held / n, "days": n}


OOS_RULES = "daily-trend out-of-sample check (pre-registered 2026-10-13, after v1 passed)"
OOS_END = "2023-04-01"                       # v1 used 2023-04 onward; everything before is unseen


def run_oos(paths) -> dict:
    """Out-of-sample check, pre-registered 2026-10-13 after v1 passed on 2023-04..2026-10:
    1. ema50 (long-only spot, unchanged) on 2017-11..2023-03, BTC and ETH, never used before. It
       passes if on both it beats holding on Sharpe AND max drawdown.
    2. ema50_ls (new: long above / short below the EMA on the perpetual, with funding from 2019-09;
       none before) on both windows. It passes if on both symbols and both windows its Sharpe beats
       holding and its total return is positive.
    Data: Binance spot daily klines (PROXY, from 2017-08) and Binance USD-M funding."""
    from datetime import datetime, timezone
    from ..data.proxy import funding_series
    from ..data.store import MarketView
    view = MarketView(paths.proxy_market)
    cut = int(datetime.fromisoformat(OOS_END).replace(tzinfo=timezone.utc).timestamp() * 1000)
    report = {"rules": OOS_RULES, "venue": "PROXY: Binance spot daily klines + USD-M funding, not Pionex"}
    for sym in ("BTC_USDT", "ETH_USDT"):
        d = view.bars(sym, "1D")
        fund = funding_series(view.conn, sym)
        k = next(i for i, t in enumerate(d.t) if t >= cut)
        report[sym] = {"days": len(d), "from": d.t[0], "cut_index": k}
        for win, (a, b) in (("oos_2017_2023", (WARMUP, k)), ("recent_2023_2026", (k, len(d)))):
            report[sym][win] = {r: backtest(d, r, a, b, fund if r == "ema50_ls" else ()) for r in ("hold", "ema50", "ema50_ls")}
    w = ("oos_2017_2023", "recent_2023_2026")
    syms = ("BTC_USDT", "ETH_USDT")
    report["ema50_passes_oos"] = all(report[s][w[0]]["ema50"]["sharpe"] > report[s][w[0]]["hold"]["sharpe"]
                                     and report[s][w[0]]["ema50"]["max_drawdown"] < report[s][w[0]]["hold"]["max_drawdown"]
                                     for s in syms)
    report["ema50_ls_passes"] = all(report[s][x]["ema50_ls"]["sharpe"] > report[s][x]["hold"]["sharpe"]
                                    and report[s][x]["ema50_ls"]["total"] > 0 for s in syms for x in w)
    dst = paths.reports / "daily_trend_oos.json"
    dst.write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report


def run(paths, cfg) -> dict:
    from ..cli import _universe_bars
    from ..data.store import resample
    u, _ = _universe_bars(paths, cfg, "1h", "proxy")
    report = {"rules": RULES, "venue": "PROXY: Binance spot 1h resampled to UTC days, not Pionex"}
    for sym in ("BTC_USDT", "ETH_USDT"):
        d = resample(u[sym][0], "1D")
        report[sym] = {r: backtest(d, r) for r in ("hold", "ema50", "sma20_100")}
    verdict = {}
    for r in ("ema50", "sma20_100"):
        verdict[r] = all(report[s][r]["sharpe"] > report[s]["hold"]["sharpe"]
                         and report[s][r]["max_drawdown"] < report[s]["hold"]["max_drawdown"]
                         and sum(t > 0 for t in report[s][r]["thirds"]) >= 2 for s in ("BTC_USDT", "ETH_USDT"))
    report["useful"] = verdict
    dst = paths.reports / "daily_trend_v1.json"
    dst.write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report
