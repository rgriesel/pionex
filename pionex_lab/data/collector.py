"""Public market-data collector: symbol rules, book tickers, depth, klines, backfill.

Runs as its own process and is the only component that calls the exchange in paper
mode. Failures are logged and surfaced through the `collector` status row; the
engine treats missing/old data as stale and freezes entries.
"""
from __future__ import annotations

import logging
import threading

from ..exchange.pionex_public import KLINE_INTERVALS, ExchangeError, PionexPublic, SchemaError
from ..exchange.ratelimit import RateLimited
from .store import MarketStore

log = logging.getLogger("pionex_lab.collector")


class Collector:
    def __init__(self, client: PionexPublic, store: MarketStore, cfg: dict, clock):
        self.client = client
        self.store = store
        self.cfg = cfg
        self.clock = clock
        self.poll = cfg["poll"]
        self.symbols = list(cfg["research_universe"])
        self.depeg_symbol = cfg.get("depeg_monitor_symbol")
        self.intervals = list(cfg["bar_intervals"])
        self._next: dict[str, int] = {}
        self._errors = 0
        self._last_error = None
        self._last_ok = None
        self._skew_ms = None
        self._schema_errors = 0

    # -------------------------------------------------------------- helpers
    def _call(self, name: str, fn, *args, **kwargs):
        now = self.clock.now_ms()
        try:
            result, env = fn(*args, **kwargs)
        except RateLimited as exc:
            self._fail(name, now, exc)
            self.clock.sleep(min(exc.retry_after_s, 60.0))
            return None, None
        except ExchangeError as exc:
            if isinstance(exc, SchemaError):
                self._schema_errors += 1
            self._fail(name, now, exc)
            return None, None
        self._last_ok = env.recv_ms
        self._skew_ms = env.skew_ms if env.skew_ms is not None else self._skew_ms
        self.store.log_fetch(now, env.endpoint, True, env.latency_ms, env.skew_ms)
        return result, env

    def _fail(self, name, now, exc):
        self._errors += 1
        self._last_error = f"{name}: {exc}"[:300]
        self.store.log_fetch(now, name, False, error=str(exc))
        log.warning("fetch failed %s: %s", name, exc)

    def _due(self, key: str, every_s: float, now: int) -> bool:
        if now >= self._next.get(key, 0):
            self._next[key] = now + int(every_s * 1000)
            return True
        return False

    # -------------------------------------------------------------- tasks
    def refresh_symbols(self):
        wanted = self.symbols + ([self.depeg_symbol] if self.depeg_symbol else [])
        rules, env = self._call("symbols", self.client.symbols, wanted)
        if rules is not None:
            self.store.upsert_symbols(rules, env.recv_ms)
            seen = {r.symbol for r in rules}
            missing = [s for s in wanted if s not in seen]
            self.store.set_status("symbols", {"requested": wanted, "missing": missing}, env.recv_ms)
        return rules

    def poll_book(self, symbol: str):
        bt, env = self._call(f"bookTicker:{symbol}", self.client.book_ticker, symbol)
        if bt is not None:
            self.store.insert_book(bt, env.server_ts, env.recv_ms)
        return bt

    def poll_depth(self, symbol: str):
        depth, env = self._call(f"depth:{symbol}", self.client.depth, symbol, int(self.poll["depth_levels"]))
        if depth is not None:
            self.store.insert_depth(symbol, depth, env.server_ts, env.recv_ms)
        return depth

    def poll_klines(self, symbol: str, interval: str, limit: int = 5):
        kl, env = self._call(f"klines:{symbol}:{interval}", self.client.klines, symbol, interval, None, limit)
        if kl is not None:
            self.store.upsert_klines(symbol, interval, kl, env.server_ts, env.recv_ms)
        return kl

    def backfill(self, symbol: str, interval: str, days: float, max_pages: int = 400) -> dict:
        step = KLINE_INTERVALS[interval]
        target = self.clock.now_ms() - int(days * 86_400_000)
        end = None
        earliest = None
        pages = total = 0
        reason = "TARGET_REACHED"
        while pages < max_pages:
            kl, env = self._call(f"backfill:{symbol}:{interval}", self.client.klines, symbol, interval, end, 500)
            pages += 1
            if kl is None:
                reason = "FETCH_ERROR"
                break
            if not kl:
                reason = "NO_MORE_HISTORY"
                break
            self.store.upsert_klines(symbol, interval, kl, env.server_ts, env.recv_ms)
            total += len(kl)
            first = kl[0].open_time
            if earliest is not None and first >= earliest:
                reason = "NO_OLDER_DATA"
                break
            earliest = first
            if first <= target:
                break
            end = first - 1  # endTime is inclusive in ms; request strictly older bars
        coverage = {"symbol": symbol, "interval": interval, "earliest_open_time": earliest, "target": target,
                    "pages": pages, "bars_received": total, "stop_reason": reason,
                    "bars_expected": int(days * 86_400_000 // step)}
        self.store.set_status(f"coverage:{symbol}:{interval}", coverage, self.clock.now_ms())
        return coverage

    def poll_once(self) -> None:
        now = self.clock.now_ms()
        if self._due("symbols", self.poll["symbols_seconds"], now):
            self.refresh_symbols()
        for s in self.symbols:
            if self._due(f"book:{s}", self.poll["book_seconds"], now):
                self.poll_book(s)
            if self._due(f"depth:{s}", self.poll["depth_seconds"], now):
                self.poll_depth(s)
            for iv in self.intervals:
                if self._due(f"klines:{s}:{iv}", self.poll["klines_seconds"], now):
                    self.poll_klines(s, iv)
        if self.depeg_symbol and self._due("depeg", self.poll["depeg_seconds"], now):
            self.poll_book(self.depeg_symbol)
        if self._due("prune", 3600, now):
            self.store.prune(now)
        self.heartbeat()

    def heartbeat(self):
        now = self.clock.now_ms()
        self.store.set_status("collector", {
            "at": now, "base_url": self.client.base_url, "official": self.client.is_official,
            "last_ok": self._last_ok, "errors": self._errors, "schema_errors": self._schema_errors,
            "last_error": self._last_error, "skew_ms": self._skew_ms,
            "ban_until": self.client.limiter.banned_until_ms}, now)

    def run(self, stop: threading.Event, backfill_days: float | None = None) -> None:
        self.refresh_symbols()
        if backfill_days:
            for s in self.symbols:
                for iv in self.intervals:
                    if stop.is_set():
                        return
                    cov = self.backfill(s, iv, backfill_days)
                    log.info("backfill %s %s: %s", s, iv, cov)
        while not stop.is_set():
            self.poll_once()
            nxt = min(self._next.values()) if self._next else self.clock.now_ms() + 1000
            stop.wait(max(0.05, min(1.0, (nxt - self.clock.now_ms()) / 1000)))
