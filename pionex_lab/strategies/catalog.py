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
INTERVAL_MS = {"5M": FIVE_MIN_MS, "60M": HOUR_MS, "4H": 4 * HOUR_MS}


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


def align_context(t_base, t_ctx, base_ms=FIVE_MIN_MS, ctx_ms=HOUR_MS):
    """For each base bar, index of the last context bar that had CLOSED by the base bar's close."""
    out, j = [-1] * len(t_base), -1
    for i, t in enumerate(t_base):
        close = t + base_ms
        while j + 1 < len(t_ctx) and t_ctx[j + 1] + ctx_ms <= close:
            j += 1
        out[i] = j
    return out


align_hourly = align_context  # 5m base / 1h context (original name)


class Strategy:
    name = "base"
    version = "v1"
    grid: list = []
    max_hold_bars = 48
    warmup = 250
    # Base bars drive signals; context bars give the higher-timeframe regime. Keys in the
    # prepared data keep their original names ("b5" = base, "b60"/"h1" = context).
    base_interval = "5M"
    context_interval = "60M"

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
            h1 = align_context(b5.t, b60.t, INTERVAL_MS[self.base_interval], INTERVAL_MS[self.context_interval])
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
        return Signal(self.name, self.version, symbol, b5.t[i], b5.t[i] + INTERVAL_MS[self.base_interval], close,
                      stop, target,
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


class CapitulationReversal(Strategy):
    """Pre-registered 2026-10-06, before any test on any data. Forced-selling flush: within the n
    bars before the decision bar, price falls from its prior high by at least k x the pre-drop ATR
    x sqrt(n) on a volume spike (a bar >= 2x the pre-drop 20-bar average), the low is at most two
    bars old, and the decision bar closes green below the prior high. Flushes overshoot and
    partially revert; their moves are larger than ordinary dips, which a ~16 bps round trip needs.
    Stop 0.25 ATR under the flush low, target rr x risk, time exit 4h."""
    name = "capitulation_reversal"
    grid = _grid(n=[6, 12], k=[3.0, 4.0], rr=[1.0, 2.0])

    def _prepare_symbol(self, d):
        b = d["b5"]
        d["vol_sma"] = sma(b.v, 20)
        for n in (6, 12):
            d[f"hi{n}"], d[f"lo{n}"] = prior_max(b.h, n), prior_min(b.l, n)

    def check(self, prep, symbol, i):
        d, p = prep[symbol], self.params
        b, n = d["b5"], p["n"]
        if i < n + 2:
            return None
        pre = i - n - 1
        hi, a0, c0, vs, a = d[f"hi{n}"][i], d["atr"][pre], b.c[pre], d["vol_sma"][pre], d["atr"][i]
        if not finite(hi, a0, vs, a, d[f"lo{n}"][i]) or min(a0, c0, vs, a) <= 0:
            return None
        low = min(d[f"lo{n}"][i], b.l[i])
        if min(b.l[i - 2:i + 1]) > low:                  # the flush low must be recent
            return None
        if (hi - low) / hi < p["k"] * (a0 / c0) * math.sqrt(n):
            return None
        if max(b.v[i - n:i]) < 2.0 * vs or not (b.o[i] < b.c[i] < hi):
            return None
        stop = low - 0.25 * a
        target = b.c[i] + p["rr"] * (b.c[i] - stop)
        return self._signal(d, symbol, i, stop, target, "first green bar after a high-volume flush",
                            {"drop_frac": (hi - low) / hi, "drop_in_atr": (hi - low) / a0})


class BandSnapbackScalp(Strategy):
    """Pre-registered 2026-10-06, before any test on any data. Scalp (30-60 min): an impulsive
    5m bar (range >= 1.5 ATR) closing below the lower Bollinger band (20, k sigma) snaps back
    toward the 20-bar mean. Only extreme stretches qualify, so the target move can clear the
    ~16 bps round trip. Optional 1h filter: 1h close above its EMA50. Target the 20-bar SMA,
    stop stop_atr x ATR below the close, time exit after `hold` bars."""
    name = "band_snapback_scalp"
    grid = _grid(k=[2.5, 3.0], trend=[0, 1], stop_atr=[1.0, 1.5], hold=[6, 12])
    max_hold_bars = 12

    def _prepare_symbol(self, d):
        b = d["b5"]
        d["sma20"], d["sd20"] = sma(b.c, 20), rolling_std(b.c, 20)

    def check(self, prep, symbol, i):
        d, p = prep[symbol], self.params
        b, j, a = d["b5"], d["h1"][i], d["atr"][i]
        mid, sd = d["sma20"][i], d["sd20"][i]
        if not finite(mid, sd, a) or a <= 0 or sd <= 0:
            return None
        if b.c[i] >= mid - p["k"] * sd or b.h[i] - b.l[i] < 1.5 * a:
            return None
        if p["trend"] and (j < 0 or not finite(d["ema50_1h"][j]) or d["b60"].c[j] <= d["ema50_1h"][j]):
            return None
        return self._signal(d, symbol, i, b.c[i] - p["stop_atr"] * a, mid, "impulsive close below the lower band",
                            {"z": (b.c[i] - mid) / sd, "range_atr": (b.h[i] - b.l[i]) / a}, hold=p["hold"])


def _funding_ranks(f: list, n: int) -> list:
    """For each settlement j with n settlements of history: (time, mid-rank of its rate within the
    trailing n, rate). Mid-rank counts ties half, so the common 0.01% baseline is not an extreme."""
    out = []
    for j in range(n - 1, len(f)):
        window, r0 = [r for _, r in f[j - n + 1:j + 1]], f[j][1]
        out.append((f[j][0], (sum(1 for r in window if r < r0) + 0.5 * sum(1 for r in window if r == r0)) / n, r0))
    return out


class FundingSettlementBounce(Strategy):
    """Pre-registered 2026-10-09, before any test on any data. Non-OHLCV scalp around perpetual
    funding settlements (every 8h): when the settling rate is positive and in the top tail (mid-rank
    >= q) of its trailing 270 settlements, crowded longs close before settlement to avoid paying,
    pressing price; after settlement buyers return. Buy `offset` 5m bars after the settlement hour
    (only once the settlement is known), hold `hold` bars, stop 1.5 ATR, no target. Funding comes
    from the labelled proxy venue; bars without a `funding` attribute never signal."""
    name = "funding_settlement_bounce"
    grid = _grid(q=[0.80, 0.90], offset=[1, 3], hold=[6, 12])
    max_hold_bars = 12
    lookback = 270

    def _prepare_symbol(self, d):
        f = getattr(d["b5"], "funding", None) or []
        d["f_info"] = {t // HOUR_MS * HOUR_MS: (t, rank, rate) for t, rank, rate in _funding_ranks(f, self.lookback)}

    def check(self, prep, symbol, i):
        d, p = prep[symbol], self.params
        b, a = d["b5"], d["atr"][i]
        close = b.t[i] + FIVE_MIN_MS
        hour = close - p["offset"] * FIVE_MIN_MS
        x = d["f_info"].get(hour) if hour % HOUR_MS == 0 else None
        if x is None or not finite(a) or a <= 0:
            return None
        t_settle, rank, rate = x
        if t_settle > close or rate <= 0 or rank < p["q"]:     # known by now; longs crowded and paying
            return None
        return self._signal(d, symbol, i, b.c[i] - 1.5 * a, None, "post-settlement bounce after crowded-long funding",
                            {"funding_rank": rank, "funding_rate": rate}, hold=p["hold"])


def _us_open_utc_ms(t_ms: int) -> int:
    """09:30 New York time on t_ms's UTC date, in UTC ms (US DST: second Sunday of March to the
    first Sunday of November)."""
    from datetime import date, datetime, timedelta, timezone
    d = datetime.fromtimestamp(t_ms / 1000, timezone.utc).date()

    def nth_sunday(year, month, n):
        first = date(year, month, 1)
        return first + timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))
    dst = nth_sunday(d.year, 3, 2) <= d < nth_sunday(d.year, 11, 1)
    midnight = int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)
    return midnight + ((13 if dst else 14) * 60 + 30) * 60_000


class UsOpenBreakoutScalp(Strategy):
    """Pre-registered 2026-10-06, before any test on any data. Scalp (<= 60 min): the first three
    5m bars after the US equity open (09:30 New York, DST-aware) set an opening range; on US
    weekdays, the first completed bar within the next 75 minutes that closes above that range on
    volume >= v_mult x its 20-bar average is bought. Stop at the range low (or its midpoint),
    target rr x risk, time exit after 12 bars."""
    name = "us_open_breakout_scalp"
    grid = _grid(stop_mid=[0, 1], rr=[1.0, 1.5, 2.0], v_mult=[1.0, 1.5])
    max_hold_bars = 12

    def _prepare_symbol(self, d):
        d["vol_sma"] = sma(d["b5"].v, 20)
        days = {}
        d["us_open"] = [days.setdefault(t // 86_400_000, _us_open_utc_ms(t)) for t in d["b5"].t]

    def check(self, prep, symbol, i):
        d, p = prep[symbol], self.params
        b = d["b5"]
        t = b.t[i]
        open_ms = d["us_open"][i]
        if not open_ms + 15 * 60_000 <= t < open_ms + 90 * 60_000 or (t // 86_400_000 + 3) % 7 >= 5:
            return None                                     # outside the window, or a weekend
        k0 = i - (t - open_ms) // FIVE_MIN_MS
        if k0 < 1 or b.t[k0] != open_ms or not finite(d["vol_sma"][i - 1]):
            return None                                     # opening bars missing
        hi, lo = max(b.h[k0:k0 + 3]), min(b.l[k0:k0 + 3])
        if any(c > hi for c in b.c[k0 + 3:i]) or b.c[i] <= hi or b.v[i] < p["v_mult"] * d["vol_sma"][i - 1]:
            return None                                     # not the first close above the range
        stop = (hi + lo) / 2 if p["stop_mid"] else lo
        target = b.c[i] + p["rr"] * (b.c[i] - stop)
        return self._signal(d, symbol, i, stop, target, "first close above the US opening range",
                            {"range_frac": (hi - lo) / lo, "vol_ratio": b.v[i] / d["vol_sma"][i - 1]})


class FundingExtreme1h(Strategy):
    """Pre-registered 2026-10-08, before any test on any data. First hypothesis on information
    other than OHLCV: every price-pattern hypothesis so far had ~0 gross expectancy. When the
    just-settled perpetual funding rate is negative (shorts pay longs) and in the lowest q of its
    trailing 90 days (270 settlements, mid-rank so the common 0.01% baseline ties are not "lowest"),
    shorts are crowded and paying to stay in; that can precede short squeezes.
    Go long spot on the first closed hour after such a settlement; stop stop_atr x ATR, no
    target, time exit after `hold` hours. Funding comes from the labelled proxy venue (see
    data/proxy.py); bars without a `funding` attribute (e.g. the live engine, until a live
    funding feed exists) never signal."""
    name = "funding_extreme_1h"
    base_interval, context_interval = "60M", "4H"
    max_hold_bars = 4
    grid = _grid(q=[0.05, 0.10], hold=[2, 4], stop_atr=[1.5, 2.5])
    lookback = 270

    def _prepare_symbol(self, d):
        b, n = d["b5"], self.lookback
        f = getattr(b, "funding", None) or []
        ranks, rates, fresh = [math.nan] * len(b), [math.nan] * len(b), [False] * len(b)
        cache, j = {}, -1
        for i, t in enumerate(b.t):
            prev, close = j, t + INTERVAL_MS[self.base_interval]
            while j + 1 < len(f) and f[j + 1][0] <= close:      # settlements known by this bar's close
                j += 1
            if j >= n - 1:
                if j not in cache:
                    window, r0 = [r for _, r in f[j - n + 1:j + 1]], f[j][1]
                    cache[j] = (sum(1 for r in window if r < r0) + 0.5 * sum(1 for r in window if r == r0)) / n
                ranks[i], rates[i], fresh[i] = cache[j], f[j][1], j != prev
        d["f_rank"], d["f_rate"], d["f_fresh"] = ranks, rates, fresh

    def check(self, prep, symbol, i):
        d, p = prep[symbol], self.params
        b, a = d["b5"], d["atr"][i]
        if not d["f_fresh"][i] or not finite(d["f_rank"][i], a) or a <= 0 or d["f_rank"][i] > p["q"]:
            return None
        if not d["f_rate"][i] < 0:
            return None
        return self._signal(d, symbol, i, b.c[i] - p["stop_atr"] * a, None, "funding settled in its lowest tail",
                            {"funding_rank": d["f_rank"][i], "funding_rate": d["f_rate"][i]}, hold=p["hold"])


class SessionDrift1h(Strategy):
    """Pre-registered 2026-10-06, before any test on any data. Intraday seasonality: go long at
    the open of a fixed UTC hour and exit after a fixed number of hours, optionally only in a 4h
    uptrend. Entry hours fixed in advance: 13 and 14 (US pre-open/open), 20 (late US session),
    22 (Asia handover). Stop 2 ATR below the entry-bar close; no target."""
    name = "session_drift_1h"
    base_interval, context_interval = "60M", "4H"
    max_hold_bars = 4
    grid = _grid(hour=[13, 14, 20, 22], hold=[2, 4], trend=[0, 1])

    def check(self, prep, symbol, i):
        d, p = prep[symbol], self.params
        b, a = d["b5"], d["atr"][i]
        if ((b.t[i] + HOUR_MS) // HOUR_MS) % 24 != p["hour"] or not finite(a) or a <= 0:
            return None
        if p["trend"] and not self._uptrend_1h(d, i):
            return None
        return self._signal(d, symbol, i, b.c[i] - 2.0 * a, None, f"session entry at {p['hour']:02d}:00 UTC",
                            {"trend_filter": p["trend"]}, hold=p["hold"])


class DeepPullback1h(Strategy):
    """Pre-registered 2026-10-06, before any test on any data. In an established 4h uptrend
    (EMA20 > EMA50, close above EMA50), an unusually deep 1h dip (close at least k x ATR below
    the 1h EMA20) reverts toward that EMA within 4h; only deep dips leave room above costs.
    Optional confirmation: the decision bar closes green. Target the 1h EMA20; stop stop_atr x
    ATR below the close."""
    name = "deep_pullback_1h"
    base_interval, context_interval = "60M", "4H"
    max_hold_bars = 4
    grid = _grid(k=[1.5, 2.0, 2.5], stop_atr=[1.5, 2.5], confirm=[0, 1])

    def _prepare_symbol(self, d):
        d["ema20"] = ema(d["b5"].c, 20)

    def check(self, prep, symbol, i):
        d, p = prep[symbol], self.params
        b, j, a = d["b5"], d["h1"][i], d["atr"][i]
        if j < 0 or not finite(d["ema20"][i], a, d["ema20_1h"][j], d["ema50_1h"][j]) or a <= 0:
            return None
        if not (d["ema20_1h"][j] > d["ema50_1h"][j] and d["b60"].c[j] > d["ema50_1h"][j]):
            return None
        if b.c[i] > d["ema20"][i] - p["k"] * a or (p["confirm"] and b.c[i] <= b.o[i]):
            return None
        return self._signal(d, symbol, i, b.c[i] - p["stop_atr"] * a, d["ema20"][i],
                            "deep 1h dip below EMA20 in a 4h uptrend", {"depth_atr": (d["ema20"][i] - b.c[i]) / a})


STRATEGIES = {cls.name: cls for cls in (VolatilityBreakout, TrendPullback, RangeReversion, RelativeStrength,
                                        CapitulationReversal, BandSnapbackScalp, UsOpenBreakoutScalp,
                                        FundingSettlementBounce)}


def _hourly(cls):
    """Same hypothesis and frozen grid on 1-hour candles with 4-hour context. Holding is
    capped at 4 bars (4 hours), the mandate's maximum intraday holding period. Grids are
    in bars of the base interval and were fixed before any hourly result was seen."""
    return type(cls.__name__ + "Hourly", (cls,), {
        "name": cls.name + "_1h", "base_interval": "60M", "context_interval": "4H", "max_hold_bars": 4,
        "__doc__": (cls.__doc__ or "") + " [1h base / 4h context variant]"})


HOURLY = {c.name: c for c in (FundingExtreme1h, SessionDrift1h, DeepPullback1h,
                              _hourly(VolatilityBreakout), _hourly(TrendPullback), _hourly(RangeReversion),
                              _hourly(RelativeStrength))}
ALL = {**STRATEGIES, **HOURLY}
TIMEFRAMES = {"5m": ("5M", "60M", STRATEGIES), "1h": ("60M", "4H", HOURLY)}


def build(name: str, params: dict | None = None) -> Strategy:
    return ALL[name](params)
