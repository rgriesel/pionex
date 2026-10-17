"""Risk-of-ruin Monte Carlo for any test, spot or futures (research only).

Pre-registered 2026-10-17 07:30 SAST (CLO-34), before any test uses it. Parameters are fixed here:
  input      the OUT-OF-SAMPLE trades only (dicts with exit_time ms and `net_bps` = return on EQUITY,
             so leverage / margin_frac are already inside it), plus the OOS window [start_ms, end_ms]
             (or a plain list of daily returns for a daily-rebalanced basket)
  daily      returns summed per UTC exit day over the window, empty days = 0 (idle time counts)
  resample   circular block bootstrap over days, BLOCK_DAYS = 5, N_RESAMPLES = 10,000, seed 20261017
  path       30 days, starting equity $100 compounded daily (equity *= 1 + r, floored at 0)
  ruin       equity <= $50 at ANY daily close inside the 30 days (intra-day lows are not seen, so this
             slightly UNDERSTATES ruin for fast leveraged strategies; the trade-level liquidation is
             already inside each trade's net_bps)
  reported   p_ruin, median 30-day return, p5 / p95, and return_per_ruin = median 30-day return /
             max(p_ruin, 1/N): one extra ruin event in N resamples is the resolution floor
  INSUFFICIENT  fewer than MIN_DAYS = 60 OOS days: no ranking is meaningful
It is a descriptive resampling of the past OOS window, not a forecast and not proof of profit.
"""
from __future__ import annotations

import json
import random
import statistics

DAY_MS = 86_400_000
BLOCK_DAYS = 5
N_RESAMPLES = 10_000
HORIZON_DAYS = 30
START_EQUITY = 100.0
RUIN_EQUITY = 50.0
MIN_DAYS = 60
SEED = 20261017


def daily_returns(trades: list, start_ms: int, end_ms: int, key: str = "net_bps") -> list[float]:
    """Fractional return per UTC day in [start_ms, end_ms], from trades by exit day (bps -> fraction)."""
    d0, d1 = start_ms // DAY_MS, end_ms // DAY_MS
    days = [0.0] * (d1 - d0 + 1)
    for t in trades:
        d = t["exit_time"] // DAY_MS
        if d0 <= d <= d1:
            days[d - d0] += t[key] / 1e4
    return days


def monte_carlo(daily: list[float], n: int = N_RESAMPLES, horizon: int = HORIZON_DAYS,
                block: int = BLOCK_DAYS, seed: int = SEED, start: float = START_EQUITY,
                ruin: float = RUIN_EQUITY) -> dict:
    m = len(daily)
    if m < MIN_DAYS:
        return {"verdict": "INSUFFICIENT", "n_days": m, "reason": f"fewer than {MIN_DAYS} OOS days"}
    rng = random.Random(seed)
    finals, ruined = [], 0
    for _ in range(n):
        eq, hit, d = start, False, 0
        while d < horizon:
            s = rng.randrange(m)
            for off in range(block):
                if d >= horizon:
                    break
                eq = max(0.0, eq * (1.0 + daily[(s + off) % m]))
                d += 1
                if eq <= ruin:
                    hit = True
        finals.append(eq / start - 1.0)
        ruined += hit
    finals.sort()
    p = ruined / n
    med = statistics.median(finals)
    return {"verdict": "OK", "n_days": m, "resamples": n, "p_ruin": p, "median_30d_return": med,
            "mean_30d_return": sum(finals) / n, "p5_30d_return": finals[int(0.05 * n)],
            "p95_30d_return": finals[int(0.95 * n) - 1], "return_per_ruin": med / max(p, 1.0 / n),
            "ruin_floor_applied": p == 0.0}


def ruin_report(trades: list, start_ms: int, end_ms: int, **kw) -> dict:
    out = monte_carlo(daily_returns(trades, start_ms, end_ms), **kw)
    out["n_trades"] = sum(1 for t in trades if start_ms // DAY_MS <= t["exit_time"] // DAY_MS <= end_ms // DAY_MS)
    return out


def save(paths, slug: str, log_match: str, title: str, ruin: dict) -> None:
    """Write var/reports/ruin_<slug>.json; `log_match` is a substring of the test's STRATEGY_LOG row."""
    dst = paths.reports / f"ruin_{slug}.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps({"title": title, "log_match": log_match, "ruin": ruin}, indent=1), encoding="utf-8")
