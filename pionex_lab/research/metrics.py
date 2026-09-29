"""Evidence metrics: expectancy, profit factor, concentration, block bootstrap."""
from __future__ import annotations

import math
import random

DAY_MS = 86_400_000


def summarize(trades: list, key: str = "net_bps") -> dict:
    vals = [t[key] for t in trades]
    n = len(vals)
    if not n:
        return {"n": 0, "expectancy_bps": None, "win_rate": None, "profit_factor": None, "total_bps": 0.0,
                "total_minus_best_bps": 0.0, "max_drawdown_bps": 0.0, "span_days": 0.0}
    wins = [v for v in vals if v > 0]
    losses = [-v for v in vals if v < 0]
    cum = peak = dd = 0.0
    for v in vals:
        cum += v
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    span = (max(t["exit_time"] for t in trades) - min(t["entry_time"] for t in trades)) / DAY_MS
    return {"n": n, "expectancy_bps": sum(vals) / n, "win_rate": len(wins) / n,
            "profit_factor": (sum(wins) / sum(losses)) if losses else None,
            "profit_factor_note": None if losses else "unavailable: no losing trades",
            "total_bps": sum(vals), "total_minus_best_bps": sum(vals) - max(vals),
            "max_drawdown_bps": dd, "span_days": span}


def daily_series(trades: list, key: str = "net_bps") -> list:
    """Calendar-complete (sum, count) per UTC exit day, including empty days."""
    if not trades:
        return []
    days = {}
    for t in trades:
        d = t["exit_time"] // DAY_MS
        s, c = days.get(d, (0.0, 0))
        days[d] = (s + t[key], c + 1)
    lo, hi = min(days), max(days)
    return [days.get(d, (0.0, 0)) for d in range(lo, hi + 1)]


def block_bootstrap_lower(trades: list, alpha: float, key: str = "net_bps", block_days: int = 3,
                          resamples: int | None = None, seed: int = 20260928) -> float | None:
    """One-sided lower confidence bound on mean per-trade value.

    Circular block bootstrap over calendar days (blocks predeclared at 3 days) keeps
    intra-day and multi-day clustering. `alpha` should already be divided by the
    number of configurations searched (Bonferroni), so repeated selection widens
    the interval instead of being ignored.
    """
    series = daily_series(trades, key)
    if len(series) < 2 or sum(c for _, c in series) < 2:
        return None
    if resamples is None:
        resamples = int(min(200_000, max(2_000, math.ceil(20 / alpha))))
    rng = random.Random(seed)
    n = len(series)
    b = max(1, min(block_days, n))
    means = []
    for _ in range(resamples):
        tot, cnt, days = 0.0, 0, 0
        while days < n:
            start = rng.randrange(n)
            for off in range(b):
                if days >= n:
                    break
                s, c = series[(start + off) % n]
                tot += s
                cnt += c
                days += 1
        if cnt:
            means.append(tot / cnt)
    if not means:
        return None
    means.sort()
    idx = max(0, min(len(means) - 1, int(math.floor(alpha * len(means)))))
    return means[idx]


def fold_positive(fold_totals: list) -> tuple[int, int]:
    return sum(1 for v in fold_totals if v > 0), len(fold_totals)


def concentration(trades: list, key: str = "net_bps") -> dict:
    if not trades:
        return {}
    by_symbol, by_day = {}, {}
    for t in trades:
        by_symbol[t["symbol"]] = by_symbol.get(t["symbol"], 0.0) + t[key]
        d = t["exit_time"] // DAY_MS
        by_day[d] = by_day.get(d, 0.0) + t[key]
    total_abs = sum(abs(v) for v in by_day.values()) or 1.0
    return {"by_symbol_bps": by_symbol, "largest_day_share_of_abs_pnl": max(abs(v) for v in by_day.values()) / total_abs,
            "trades_by_exit_reason": _count(t["exit_reason"] for t in trades)}


def _count(it):
    out = {}
    for x in it:
        out[x] = out.get(x, 0) + 1
    return out
