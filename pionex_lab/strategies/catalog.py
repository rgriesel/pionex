"""Frozen v1 research hypotheses from references/research.md.

Each strategy is deterministic, long-or-cash, decides only on COMPLETED bars, and
declares its invalidation (stop), target, and maximum holding time up front. The
same `check()` code is used by the backtester and by the paper engine. Parameter
grids are bounded (<= 20 trials per hypothesis per the mandate). None of these is
evidence of an edge; each is an unproven hypothesis until it passes the gates.

Not implemented on purpose: lead/lag and order-flow hypotheses require
synchronized tick/book replay (the collector stores book ticks for that later);
bounded grids require a validated range regime and verified exchange-side stops.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

from .indicators import (atr, efficiency_ratio, ema, finite, percentile_rank, prior_max, prior_min, rolling_std,
                         rolling_vwap, rsi, sma)

MIN_STOP_FRACTION = 0.0015  # tighter stops are dominated by spread/fees
MAX_STOP_FRACTION = 0.03
HOUR_MS = 3_600_000
FIVE_MIN_MS = 300_000


@dataclass(frozen=True)
class Signal:
    strategy: str
    version: str
    symbol: str
    bar_time: int          # open time of the completed decision bar
    decided_at: int        # close time of that bar; execution only after this
    reference_price: float
    stop: float
    target: float | None
    max_hold_bars: int
    reason: str
    features: dict = field(default_factory=dict, compare=False)

    @property
    def opportunity_id(self) -> str:
        return f"{self.strategy}:{self.symbol}:{self.bar_time}"


def _grid(**axes):
    keys = list(axes)
    return [dict(zip(keys, combo)) for combo in itertools.product(*(axes[k] for k in keys))]


def align_hourly(t5, t60):
    """For each 5m bar, index of the last 1h bar that had CLOSED by the 5m bar's close."""
    out, j = [-1] * len(t5), -1
    for i, t in enumerate(t5):
        close5 = t + FIVE_MIN_MS
        while j + 1 < len(t60) and t60[j + 1] + HOUR_MS <= close5:
            j += 1
        out[i] = j
    return out


class Strategy:
    name = "base"
    version = "v1"
    grid: list = []
    max_hold_bars = 48
    warmup = 250

    def __init__(self, params: dict | None = None):
        self.params = dict(params or self.grid[0])
        unknown = set(self.params) - set(self.grid[0])
        if unknown:
            raise ValueError(f"unknown params {unknown}")

    @property
    def key(self) -> str:
        return f"{self.name}/{self.version}"

    def prepare(self, universe: dict) -> dict:
        prep = {}
        for sym, (b5, b60) in universe.items():
            h1 = align_hourly(b5.t, b60.t)
            c60 = b60.c
            prep[sym] = {"b5": b5, "b60": b60, "h1": h1, "atr": atr(b5.h, b5.l, b5.c, 14),
                         "ema20_1h": ema(c60, 20), "ema50_1h": ema(c60, 50)}
            self._prepare_symbol(prep[sym])
        return prep

    def _prepare_symbol(self, d: dict) -> None:
        pass

    def check(self, prep: dict, symbol: str, i: int) -> Signal | None:
        raise NotImplementedError

    def _signal(self, d, symbol, i, stop, target, reason, features, hold=None):
        b5 = d["b5"]
        close = b5.c[i]
        if not finite(stop) or stop <= 0:
            return None
        dist = (close - stop) / close
        if not MIN_STOP_FRACTION <= dist <= MAX_STOP_FRACTION:
            return None
        if target is not None and (not finite(target) or target <= close):
            return None
        return Signal(self.name, self.version, symbol, b5.t[i], b5.t[i] + FIVE_MIN_MS, close, stop, target,
                      hold or self.max_hold_bars, reason, {k: round(v, 8) if isinstance(v, float) else v
                                                          for k, v in features.items()})

    @staticmethod
    def _uptrend_1h(d, i, lookback=3) -> bool:
        j = d["h1"][i]
        e = d["ema20_1h"]
        if j < lookback or not finite(e[j], e[j - lookback]):
            return False
        return d["b60"].c[j] > e[j] and e[j] > e[j - lookback]


class VolatilityBreakout(Strategy):
    """Completed 5m compression, break of the prior range, expanding volume,
    aligned 1h trend. Invalidation: range low. Time exit 4h."""
    name = "volatility_breakout"
    grid = _grid(lookback=[12, 24], vol_mult=[1.5, 2.0], rr=[1.5, 2.5])

    def _prepare_symbol(self, d):
        b = d["b5"]
        mid, sd = sma(b.c, 20), rolling_std(b.c, 20)
        width = [4 * s / m if finite(s, m) and m > 0 else math.nan for s, m in zip(sd, mid)]
        d["width_rank"] = percentile_rank(width, 200)
        d["vol_sma"] = sma(b.v, 20)
        for n in (12, 24):
            d[f"hi{n}"], d[f"lo{n}"] = prior_max(b.h, n), prior_min(b.l, n)

    def check(self, prep, symbol, i):
        d, p = prep[symbol], self.params
        b, n = d["b5"], p["lookback"]
        if i < 1 or not finite(d["width_rank"][i - 1], d[f"hi{n}"][i], d["vol_sma"][i - 1]):
            return None
        if d["width_rank"][i - 1] > 0.30 or b.c[i] <= d[f"hi{n}"][i]:
            return None
        if b.v[i] <= p["vol_mult"] * d["vol_sma"][i - 1] or not self._uptrend_1h(d, i):
            return None
        stop = min(d[f"lo{n}"][i], b.l[i])
        target = b.c[i] + p["rr"] * (b.c[i] - stop)
        return self._signal(d, symbol, i, stop, target, "compressed range breakout with volume, 1h uptrend",
                            {"width_rank": d["width_rank"][i - 1], "vol_ratio": b.v[i] / d["vol_sma"][i - 1]})


class TrendPullback(Strategy):
    """Recovery from a 5m pullback inside an established 1h uptrend."""
    name = "trend_pullback"
    grid = _grid(rsi_low=[35, 40], rr=[1.5, 2.0, 3.0])

    def _prepare_symbol(self, d):
        b = d["b5"]
        d["rsi"], d["ema20"] = rsi(b.c, 14), ema(b.c, 20)
        d["lo12"] = prior_min(b.l, 12)

    def check(self, prep, symbol, i):
        d, p = prep[symbol], self.params
        b, r = d["b5"], d["rsi"]
        j = d["h1"][i]
        if i < 7 or j < 1 or not finite(r[i], r[i - 1], d["ema20"][i], d["lo12"][i], d["ema20_1h"][j], d["ema50_1h"][j]):
            return None
        if not (d["ema20_1h"][j] > d["ema50_1h"][j] and d["b60"].c[j] > d["ema50_1h"][j]):
            return None
        recent = [v for v in r[i - 6:i] if finite(v)]
        dipped = bool(recent) and min(recent) < p["rsi_low"]
        if not (dipped and r[i - 1] < 50 <= r[i] and b.c[i] > d["ema20"][i]):
            return None
        stop = min(d["lo12"][i], b.l[i])
        target = b.c[i] + p["rr"] * (b.c[i] - stop)
        return self._signal(d, symbol, i, stop, target, "RSI recovery above 50 after pullback in 1h uptrend",
                            {"rsi": r[i], "rsi_prev": r[i - 1]})


class RangeReversion(Strategy):
    """Fresh negative deviation from rolling VWAP in a non-trending regime."""
    name = "range_reversion"
    grid = _grid(k=[2.0, 2.5], er_max=[0.25, 0.35], stop_atr=[1.5, 2.0])
    max_hold_bars = 24

    def _prepare_symbol(self, d):
        b = d["b5"]
        vw = rolling_vwap(b.h, b.l, b.c, b.v, 48)
        dev = [c - v if finite(v) else math.nan for c, v in zip(b.c, vw)]
        sd = rolling_std([x if finite(x) else 0.0 for x in dev], 48)
        d["vwap"], d["dev"], d["dev_sd"] = vw, dev, sd
        d["er5"] = efficiency_ratio(b.c, 48)
        d["er60"] = efficiency_ratio(d["b60"].c, 24)

    def check(self, prep, symbol, i):
        d, p = prep[symbol], self.params
        b = d["b5"]
        j = d["h1"][i]
        if i < 2 or j < 0 or not finite(d["dev"][i], d["dev"][i - 1], d["dev_sd"][i], d["er5"][i], d["er60"][j],
                                        d["atr"][i], d["vwap"][i]):
            return None
        if d["dev_sd"][i] <= 0 or d["er5"][i] >= p["er_max"] or d["er60"][j] >= p["er_max"]:
            return None
        z, z_prev = d["dev"][i] / d["dev_sd"][i], d["dev"][i - 1] / d["dev_sd"][i]
        if not (z <= -p["k"] < z_prev):
            return None
        stop = b.c[i] - p["stop_atr"] * d["atr"][i]
        return self._signal(d, symbol, i, stop, d["vwap"][i], "fresh VWAP deviation in non-trending regime",
                            {"z": z, "er5": d["er5"][i], "er60": d["er60"][j]})


class RelativeStrength(Strategy):
    """Strongest eligible asset after broad-market adjustment, with a fixed
    continuation trigger. Needs at least two aligned symbols."""
    name = "relative_strength"
    grid = _grid(lookback_h=[12, 24], trigger=[6, 12], rr=[1.5, 2.0])

    def prepare(self, universe):
        prep = super().prepare(universe)
        for d in prep.values():
            d["index"] = {t: k for k, t in enumerate(d["b5"].t)}
        prep["_symbols"] = sorted(universe)
        return prep

    def _prepare_symbol(self, d):
        for n in (6, 12):
            d[f"hi{n}"] = prior_max(d["b5"].h, n)

    def _hour_return(self, d, t5, n):
        idx = d["index"].get(t5)
        if idx is None:
            return None
        j = d["h1"][idx]
        if j < n:
            return None
        c = d["b60"].c
        return c[j] / c[j - n] - 1

    def check(self, prep, symbol, i):
        p, syms = self.params, prep["_symbols"]
        if len(syms) < 2:
            return None
        d = prep[symbol]
        b = d["b5"]
        t = b.t[i]
        rets = {s: self._hour_return(prep[s], t, p["lookback_h"]) for s in syms}
        if any(v is None for v in rets.values()):
            return None
        market = sum(rets.values()) / len(rets)
        rel = {s: r - market for s, r in rets.items()}
        best = max(syms, key=lambda s: (rel[s], s))
        if best != symbol or rel[symbol] <= 0 or rets[symbol] <= 0:
            return None
        n = p["trigger"]
        if not finite(d[f"hi{n}"][i], d["atr"][i]) or b.c[i] <= d[f"hi{n}"][i]:
            return None
        stop = b.c[i] - 1.5 * d["atr"][i]
        target = b.c[i] + p["rr"] * (b.c[i] - stop)
        return self._signal(d, symbol, i, stop, target, "relative-strength leader breaks short-term high",
                            {"rel_return": rel[symbol], "abs_return": rets[symbol]})


STRATEGIES = {cls.name: cls for cls in (VolatilityBreakout, TrendPullback, RangeReversion, RelativeStrength)}


def build(name: str, params: dict | None = None) -> Strategy:
    return STRATEGIES[name](params)
