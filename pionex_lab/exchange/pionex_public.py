"""Public (unauthenticated) Pionex REST market-data adapter. Standard library only.

Endpoint paths and parameters match Pionex's official AI Kit (@pionex/pionex-ai-kit
0.2.55, inspected 2026-09-28) and the skill's reference list:

  GET /api/v1/common/symbols   symbols=<csv> | type=SPOT
  GET /api/v1/market/bookTickers symbol=<s> | type=SPOT
  GET /api/v1/market/depth     symbol, limit (1-100)
  GET /api/v1/market/klines    symbol, interval (1M..1D), endTime (ms), limit (1-500)
  GET /api/v1/market/trades    symbol, limit (1-100)
  GET /api/v1/market/tickers   symbol | type

All parsers were verified against live api.pionex.com responses on 2026-09-29
(GitHub Actions run 36547328965: symbols, bookTickers, depth, klines, trades).
Observed limit: 5M klines with an endTime older than ~10,000 bars (~34.7 days) are
rejected with code MARKET_INVALID_TIME; 60M history reached 150+ days. Parsers
still validate strictly and raise SchemaError on anything unexpected; the collector
records the failure and the engine freezes entries. There is no signing, no
credential handling, and no order endpoint in this module by design.
"""
from __future__ import annotations

import json
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from decimal import Decimal

from .. import __version__
from ..util import DataError, SystemClock, dec, step_from_precision
from .ratelimit import RateLimited, WeightedLimiter

OFFICIAL_BASE_URL = "https://api.pionex.com"
KLINE_INTERVALS = {"1M": 60_000, "5M": 300_000, "15M": 900_000, "30M": 1_800_000,
                   "60M": 3_600_000, "4H": 14_400_000, "8H": 28_800_000,
                   "12H": 43_200_000, "1D": 86_400_000}


class ExchangeError(RuntimeError):
    def __init__(self, message: str, code: str | None = None, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


class SchemaError(ExchangeError):
    """Response did not match the documented structure. Fail closed."""


@dataclass(frozen=True)
class Envelope:
    data: object
    server_ts: int | None
    sent_ms: int
    recv_ms: int
    endpoint: str

    @property
    def latency_ms(self) -> int:
        return self.recv_ms - self.sent_ms

    @property
    def skew_ms(self) -> int | None:
        """Server clock minus local midpoint (positive: server ahead)."""
        if self.server_ts is None:
            return None
        return self.server_ts - (self.sent_ms + self.recv_ms) // 2


@dataclass(frozen=True)
class SymbolRules:
    symbol: str
    type: str
    base: str
    quote: str
    enabled: bool
    base_precision: int
    quote_precision: int
    min_amount: Decimal | None      # quote notional minimum (market buy amount)
    min_trade_size: Decimal | None  # base size minimum (limit orders)
    max_trade_size: Decimal | None
    min_dump_size: Decimal | None   # base size minimum (market sell)
    max_dump_size: Decimal | None
    raw: dict = field(compare=False, repr=False)

    @property
    def quantity_step(self) -> Decimal:
        return step_from_precision(self.base_precision)

    @property
    def price_step(self) -> Decimal:
        return step_from_precision(self.quote_precision)

    def complete(self) -> tuple[bool, list[str]]:
        missing = [n for n, v in (("minAmount", self.min_amount), ("minTradeSize", self.min_trade_size),
                                  ("maxTradeSize", self.max_trade_size),
                                  ("minTradeDumping", self.min_dump_size)) if v is None]
        return (not missing, missing)


@dataclass(frozen=True)
class BookTicker:
    symbol: str
    bid: Decimal
    bid_size: Decimal
    ask: Decimal
    ask_size: Decimal
    exchange_ts: int | None

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / 2

    @property
    def spread_bps(self) -> Decimal:
        return (self.ask - self.bid) / self.mid * 10000


@dataclass(frozen=True)
class Depth:
    bids: tuple  # ((price, size), ...) best first
    asks: tuple
    update_ts: int | None


@dataclass(frozen=True)
class Kline:
    open_time: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True)
class Trade:
    trade_id: str
    price: Decimal
    size: Decimal
    side: str
    ts: int


# ---------------------------------------------------------------- parsers

def _obj(v, name):
    if not isinstance(v, dict):
        raise SchemaError(f"{name}: expected object")
    return v


def _list(v, name):
    if not isinstance(v, list):
        raise SchemaError(f"{name}: expected array")
    return v


def _int(v, name, required=True):
    if v is None and not required:
        return None
    if isinstance(v, bool):
        raise SchemaError(f"{name}: expected integer")
    try:
        out = int(str(v))
    except ValueError as exc:
        raise SchemaError(f"{name}: expected integer") from exc
    if out < 0:
        raise SchemaError(f"{name}: negative")
    return out


def _dec(v, name, positive=False, required=True):
    if v is None and not required:
        return None
    try:
        return dec(v, name, positive=positive)
    except DataError as exc:
        raise SchemaError(str(exc)) from exc


def parse_envelope(payload) -> tuple[object, int | None]:
    env = _obj(payload, "envelope")
    if env.get("result") is not True:
        raise ExchangeError(f"exchange rejected request: {env.get('code')} {env.get('message')}",
                            code=str(env.get("code")))
    if "data" not in env:
        raise SchemaError("envelope: missing data")
    return env["data"], _int(env.get("timestamp"), "timestamp", required=False)


def parse_symbols(data) -> list[SymbolRules]:
    out = []
    for i, s in enumerate(_list(_obj(data, "data").get("symbols"), "symbols")):
        s = _obj(s, f"symbols[{i}]")
        sym = s.get("symbol")
        if not isinstance(sym, str) or not sym:
            raise SchemaError("symbol name missing")
        enabled = s.get("enable")
        if not isinstance(enabled, bool):
            raise SchemaError(f"{sym}.enable: expected boolean")
        base_p = _int(s.get("basePrecision"), f"{sym}.basePrecision")
        quote_p = _int(s.get("quotePrecision"), f"{sym}.quotePrecision")
        if base_p > 18 or quote_p > 18:
            raise SchemaError(f"{sym}: precision out of range")
        out.append(SymbolRules(
            symbol=sym, type=str(s.get("type", "")),
            base=str(s.get("baseCurrency", "")), quote=str(s.get("quoteCurrency", "")),
            enabled=enabled, base_precision=base_p, quote_precision=quote_p,
            min_amount=_dec(s.get("minAmount"), f"{sym}.minAmount", required=False),
            min_trade_size=_dec(s.get("minTradeSize"), f"{sym}.minTradeSize", required=False),
            max_trade_size=_dec(s.get("maxTradeSize"), f"{sym}.maxTradeSize", required=False),
            min_dump_size=_dec(s.get("minTradeDumping"), f"{sym}.minTradeDumping", required=False),
            max_dump_size=_dec(s.get("maxTradeDumping"), f"{sym}.maxTradeDumping", required=False),
            raw=dict(s)))
    return out


def parse_book_tickers(data) -> list[BookTicker]:
    out = []
    for i, t in enumerate(_list(_obj(data, "data").get("tickers"), "tickers")):
        t = _obj(t, f"tickers[{i}]")
        sym = t.get("symbol")
        if not isinstance(sym, str) or not sym:
            raise SchemaError("bookTicker symbol missing")
        bt = BookTicker(symbol=sym,
                        bid=_dec(t.get("bidPrice"), f"{sym}.bidPrice", positive=True),
                        bid_size=_dec(t.get("bidSize"), f"{sym}.bidSize"),
                        ask=_dec(t.get("askPrice"), f"{sym}.askPrice", positive=True),
                        ask_size=_dec(t.get("askSize"), f"{sym}.askSize"),
                        exchange_ts=_int(t.get("timestamp"), f"{sym}.timestamp", required=False))
        if bt.bid >= bt.ask:
            raise SchemaError(f"{sym}: crossed or locked book bid={bt.bid} ask={bt.ask}")
        out.append(bt)
    return out


def _levels(raw, name, descending):
    levels = []
    for i, lvl in enumerate(_list(raw, name)):
        lvl = _list(lvl, f"{name}[{i}]")
        if len(lvl) < 2:
            raise SchemaError(f"{name}[{i}]: expected [price, size]")
        levels.append((_dec(lvl[0], f"{name}[{i}].price", positive=True),
                       _dec(lvl[1], f"{name}[{i}].size")))
    prices = [p for p, _ in levels]
    if prices != sorted(prices, reverse=descending) or len(set(prices)) != len(prices):
        raise SchemaError(f"{name}: levels not strictly ordered")
    return tuple(levels)


def parse_depth(data) -> Depth:
    d = _obj(data, "data")
    bids = _levels(d.get("bids"), "bids", descending=True)
    asks = _levels(d.get("asks"), "asks", descending=False)
    if bids and asks and bids[0][0] >= asks[0][0]:
        raise SchemaError("depth: crossed book")
    return Depth(bids=bids, asks=asks, update_ts=_int(d.get("updateTime"), "updateTime", required=False))


def parse_klines(data) -> list[Kline]:
    out = {}
    for i, k in enumerate(_list(_obj(data, "data").get("klines"), "klines")):
        k = _obj(k, f"klines[{i}]")
        kl = Kline(open_time=_int(k.get("time"), f"klines[{i}].time"),
                   open=_dec(k.get("open"), "open", positive=True),
                   high=_dec(k.get("high"), "high", positive=True),
                   low=_dec(k.get("low"), "low", positive=True),
                   close=_dec(k.get("close"), "close", positive=True),
                   volume=_dec(k.get("volume"), "volume"))
        if not (kl.low <= min(kl.open, kl.close) and kl.high >= max(kl.open, kl.close)):
            raise SchemaError(f"kline {kl.open_time}: inconsistent OHLC")
        if kl.open_time in out and out[kl.open_time] != kl:
            raise SchemaError(f"kline {kl.open_time}: conflicting duplicate")
        out[kl.open_time] = kl
    return [out[t] for t in sorted(out)]


def parse_trades(data) -> list[Trade]:
    out = []
    for i, t in enumerate(_list(_obj(data, "data").get("trades"), "trades")):
        t = _obj(t, f"trades[{i}]")
        side = t.get("side")
        if side not in ("BUY", "SELL"):
            raise SchemaError(f"trades[{i}].side invalid")
        out.append(Trade(trade_id=str(t.get("tradeId", "")),
                         price=_dec(t.get("price"), "price", positive=True),
                         size=_dec(t.get("size"), "size"), side=side,
                         ts=_int(t.get("timestamp"), "timestamp")))
    return out


# ---------------------------------------------------------------- client

class PionexPublic:
    def __init__(self, base_url: str = OFFICIAL_BASE_URL, limiter: WeightedLimiter | None = None,
                 timeout_s: float = 10.0, clock=None, on_response=None):
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme not in ("https", "http") or not parsed.netloc:
            raise ValueError("base_url must be http(s)://host")
        if parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("plain HTTP is only allowed for a local test server")
        self.base_url = base_url.rstrip("/")
        self.clock = clock or SystemClock()
        self.limiter = limiter or WeightedLimiter(5.0, clock=self.clock)
        self.timeout_s = timeout_s
        self.on_response = on_response  # callback(endpoint, status, text) for capability fixtures
        self._ssl = ssl.create_default_context()

    @property
    def is_official(self) -> bool:
        return self.base_url == OFFICIAL_BASE_URL

    def get(self, path: str, params: dict | None = None, weight: float = 1.0,
            priority: str = "normal") -> Envelope:
        query = {k: v for k, v in (params or {}).items() if v is not None}
        endpoint = path + ("?" + urllib.parse.urlencode(query) if query else "")
        self.limiter.acquire(weight, priority)
        req = urllib.request.Request(self.base_url + endpoint, method="GET", headers={
            "User-Agent": f"pionex-lab/{__version__}", "Accept": "application/json"})
        sent = self.clock.now_ms()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s, context=self._ssl) as resp:
                status, text = resp.status, resp.read(8_000_000).decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read(65536).decode("utf-8", "replace") if exc.fp else ""
            if self.on_response:
                self.on_response(endpoint, exc.code, body)
            if exc.code in (418, 429):
                retry = exc.headers.get("Retry-After") if exc.headers else None
                try:
                    retry_s = float(retry) if retry is not None else None
                except ValueError:
                    retry_s = None
                pause = self.limiter.ban(retry_s)
                raise RateLimited(pause, f"HTTP {exc.code} on {path}") from exc
            raise ExchangeError(f"HTTP {exc.code} on {path}: {body[:200]}", status=exc.code) from exc
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, ssl.SSLError) as exc:
            # A timeout on a read-only request has no side effects; the caller may retry.
            raise ExchangeError(f"network error on {path}: {exc}") from exc
        recv = self.clock.now_ms()
        if self.on_response:
            self.on_response(endpoint, status, text)
        try:
            payload = json.loads(text, parse_float=Decimal)
        except ValueError as exc:
            raise SchemaError(f"{path}: invalid JSON") from exc
        data, server_ts = parse_envelope(payload)
        self.limiter.success()
        return Envelope(data=data, server_ts=server_ts, sent_ms=sent, recv_ms=recv, endpoint=endpoint)

    # Convenience wrappers ------------------------------------------------
    def symbols(self, symbols: list[str] | None = None, type_: str = "SPOT"):
        params = {"symbols": ",".join(symbols)} if symbols else {"type": type_}
        env = self.get("/api/v1/common/symbols", params)
        return parse_symbols(env.data), env

    def book_ticker(self, symbol: str):
        env = self.get("/api/v1/market/bookTickers", {"symbol": symbol})
        tickers = [t for t in parse_book_tickers(env.data) if t.symbol == symbol]
        if len(tickers) != 1:
            raise SchemaError(f"bookTickers: expected exactly one {symbol}")
        return tickers[0], env

    def depth(self, symbol: str, limit: int = 20):
        if not 1 <= int(limit) <= 100:
            raise ValueError("depth limit must be 1-100")
        env = self.get("/api/v1/market/depth", {"symbol": symbol, "limit": int(limit)})
        return parse_depth(env.data), env

    def klines(self, symbol: str, interval: str, end_time: int | None = None, limit: int = 500):
        if interval not in KLINE_INTERVALS:
            raise ValueError(f"unsupported interval {interval}")
        if not 1 <= int(limit) <= 500:
            raise ValueError("klines limit must be 1-500")
        env = self.get("/api/v1/market/klines", {"symbol": symbol, "interval": interval,
                                                 "endTime": end_time, "limit": int(limit)})
        return parse_klines(env.data), env

    def trades(self, symbol: str, limit: int = 100):
        if not 1 <= int(limit) <= 100:
            raise ValueError("trades limit must be 1-100")
        env = self.get("/api/v1/market/trades", {"symbol": symbol, "limit": int(limit)})
        return parse_trades(env.data), env
