"""Candle sources for Wave Lab. Every response names its source so the UI can label it.

* PionexFeed: public, unauthenticated Pionex klines (no keys, no order endpoints).
* StoreFeed:  bars already collected into var/market.db by `pionex_lab collect`.
* DemoFeed:   deterministic SYNTHETIC prices for offline use and tests. Not market data.
"""
from __future__ import annotations

import hashlib
import math
import re
import threading
import time

from ..exchange.pionex_public import KLINE_INTERVALS, ExchangeError, PionexPublic

SYMBOL_RE = re.compile(r"^[A-Z0-9]{1,20}_[A-Z0-9]{1,10}$")
MAX_BARS = 1000
DEMO_SYMBOLS = ("BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", "BNB_USDT", "DOGE_USDT", "ADA_USDT",
                "AVAX_USDT", "LINK_USDT", "DOT_USDT", "LTC_USDT", "TRX_USDT")


def validate(symbol: str, interval: str) -> None:
    if not isinstance(symbol, str) or not SYMBOL_RE.match(symbol):
        raise ValueError("invalid symbol")
    if interval not in KLINE_INTERVALS:
        raise ValueError("invalid interval")


def _empty():
    return {"t": [], "o": [], "h": [], "l": [], "c": [], "v": []}


class DemoFeed:
    name = "demo"
    label = "DEMO: synthetic prices, not market data"

    def __init__(self, clock=time.time):
        self.clock = clock

    def symbols(self):
        return list(DEMO_SYMBOLS)

    @staticmethod
    def _seed(symbol: str) -> int:
        return int.from_bytes(hashlib.sha256(symbol.encode()).digest()[:8], "big")

    def _base(self, symbol: str) -> float:
        known = {"BTC_USDT": 60000.0, "ETH_USDT": 3000.0, "SOL_USDT": 150.0, "BNB_USDT": 550.0}
        return known.get(symbol, 0.5 + (self._seed(symbol) % 20000) / 100.0)

    PERIODS_H = (0.4, 1.1, 3.0, 8.0, 21.0, 55.0, 144.0, 377.0, 987.0, 2584.0)

    def _logp(self, symbol: str, t_ms: float) -> float:
        """Log price at time t: layered cycles from minutes to months (so every timeframe shows
        swings at its own scale and timeframes agree). A pure function of (symbol, t)."""
        s = self._seed(symbol)
        hours = t_ms / 3_600_000
        x = 0.0
        for j, period in enumerate(self.PERIODS_H):
            phase = ((s >> (6 * j)) & 0x3F) / 63.0 * 2 * math.pi
            x += 0.004 * math.sqrt(period) * math.sin(2 * math.pi * hours / period + phase)
        return x

    def candles(self, symbol: str, interval: str, limit: int = 500):
        validate(symbol, interval)
        step = KLINE_INTERVALS[interval]
        now = int(self.clock() * 1000)
        cur = now // step
        base = self._base(symbol)
        out = _empty()
        for k in range(cur - limit + 1, cur + 1):
            t0 = k * step
            t1 = min(now, t0 + step)
            pts = [self._logp(symbol, t0 + f * (t1 - t0) / 8) for f in range(9)]
            noise = (self._seed(f"{symbol}:{interval}:{k}") % 1000) / 1000.0
            o, cl = base * math.exp(pts[0]), base * math.exp(pts[-1])
            hi = base * math.exp(max(pts)) * (1 + 0.0015 * noise)
            lo = base * math.exp(min(pts)) * (1 - 0.0015 * (1 - noise))
            out["t"].append(t0)
            out["o"].append(o)
            out["h"].append(max(hi, o, cl))
            out["l"].append(min(lo, o, cl))
            out["c"].append(cl)
            out["v"].append(1000 * (step / 3_600_000) * (1 + noise) * (1 + abs(pts[-1] - pts[0]) * 50))
        return out


class PionexFeed:
    name = "pionex"
    label = "Pionex public market data"

    def __init__(self, client: PionexPublic | None = None, ttl_s: float = 10.0, clock=time.time):
        self.client = client or PionexPublic()
        self.ttl_s = ttl_s
        self.clock = clock
        self._cache: dict = {}
        self._symbols = None
        self._lock = threading.Lock()

    def symbols(self):
        if self._symbols is None:
            rules, _ = self.client.symbols()
            self._symbols = sorted(r.symbol for r in rules if r.enabled)
        return list(self._symbols)

    def candles(self, symbol: str, interval: str, limit: int = 500):
        validate(symbol, interval)
        limit = max(1, min(MAX_BARS, int(limit)))
        key = (symbol, interval)
        now = self.clock()
        with self._lock:
            hit = self._cache.get(key)
        if hit and now - hit[0] < self.ttl_s and len(hit[1]["t"]) >= limit:
            return _tail(hit[1], limit)
        bars, end = {}, None
        while len(bars) < limit:
            page, _ = self.client.klines(symbol, interval, end_time=end, limit=min(500, limit - len(bars)))
            if not page:
                break
            for k in page:
                bars[k.open_time] = k
            first = page[0].open_time
            if end is not None and first >= end:
                break
            end = first - 1
            if len(page) < 500:
                break
        out = _empty()
        for t in sorted(bars):
            k = bars[t]
            out["t"].append(t)
            for f, v in (("o", k.open), ("h", k.high), ("l", k.low), ("c", k.close), ("v", k.volume)):
                out[f].append(float(v))
        with self._lock:
            self._cache[key] = (now, out)
        return _tail(out, limit)


class StoreFeed:
    name = "store"
    label = "Collected Pionex bars (var/market.db)"

    def __init__(self, market_path):
        from ..data.store import MarketView
        self.view = MarketView(market_path)
        self._lock = threading.Lock()

    def symbols(self):
        with self._lock:
            rows = self.view.conn.execute("SELECT DISTINCT symbol FROM klines ORDER BY symbol").fetchall()
        return [r[0] for r in rows]

    def candles(self, symbol: str, interval: str, limit: int = 500):
        from ..data.store import resample
        validate(symbol, interval)
        with self._lock:
            have = [r[0] for r in self.view.conn.execute(
                "SELECT DISTINCT interval FROM klines WHERE symbol=?", (symbol,)).fetchall()]
            if interval in have:
                bars = self.view.bars(symbol, interval, limit=limit, complete_only=False)
            else:
                src = [iv for iv in have if KLINE_INTERVALS[interval] % KLINE_INTERVALS[iv] == 0
                       and KLINE_INTERVALS[iv] < KLINE_INTERVALS[interval]]
                if not src:
                    return _empty()
                iv = max(src, key=lambda x: KLINE_INTERVALS[x])
                need = limit * (KLINE_INTERVALS[interval] // KLINE_INTERVALS[iv]) + 1
                bars = resample(self.view.bars(symbol, iv, limit=need), interval)
        return _tail({"t": bars.t, "o": bars.o, "h": bars.h, "l": bars.l, "c": bars.c, "v": bars.v}, limit)


def _tail(d, n):
    return {k: list(v[-n:]) for k, v in d.items()}


def pick_feed(kind: str, market_path=None, client=None):
    """'pionex', 'store', 'demo', or 'auto' (Pionex if reachable, else collected bars, else demo).
    The choice is made once at startup and reported in every API response."""
    if kind == "demo":
        return DemoFeed()
    if kind == "store":
        return StoreFeed(market_path)
    if kind == "pionex":
        return PionexFeed(client)
    if kind != "auto":
        raise ValueError(f"unknown feed {kind}")
    feed = PionexFeed(client)
    try:
        feed.symbols()
        return feed
    except (ExchangeError, OSError) as exc:
        reason = str(exc)[:120]
    if market_path is not None and market_path.exists():
        st = StoreFeed(market_path)
        if st.symbols():
            st.fallback_reason = reason
            return st
    d = DemoFeed()
    d.fallback_reason = reason
    return d
