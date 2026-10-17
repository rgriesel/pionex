"""Live-data freshness rule (CLO-44, FIRM_RULES.md "Pionex is the source of truth").

Any value a trading decision uses is fetched from Pionex at decision time, carries its timestamp, and is rejected
when older than its limit: quotes 5 s, account state 5 min, symbol rules 1 day. Stale data means no action (the
caller refuses) plus a critical notice. This module never reads a log, report, cache or status file; it only
calls the public Pionex client it is given and compares timestamps. Read-only, no order code.

Age is measured on the exchange clock where the exchange supplies one: the quote's own timestamp, else the
response's server time, corrected by the measured skew; a response with no exchange time at all is aged from its
local receive time and its round trip must itself be inside the limit. A timestamp from the future by more than
FUTURE_TOLERANCE_S is rejected too (a broken clock is not fresh data).
"""
from __future__ import annotations

import time
from dataclasses import dataclass

LIMITS_S = {"quote": 5.0, "account": 300.0, "symbol_rules": 86_400.0}
FUTURE_TOLERANCE_S = 5.0


class StaleData(RuntimeError):
    """Data too old (or from the future) to decide on. Callers must refuse to act."""


@dataclass(frozen=True)
class Stamped:
    value: object
    kind: str            # key of LIMITS_S
    source_ms: int       # when the value was true, on the exchange clock (or local receive time as a last resort)
    skew_ms: int         # exchange clock minus local clock, 0 when unknown
    latency_ms: int
    exchange_clock: bool

    def age_s(self, now_ms: int) -> float:
        return (now_ms + self.skew_ms - self.source_ms) / 1000.0

    def require(self, now_ms: int | None = None, limit_s: float | None = None):
        """-> value, or raises StaleData."""
        now_ms = int(time.time() * 1000) if now_ms is None else now_ms
        limit = LIMITS_S[self.kind] if limit_s is None else limit_s
        age = self.age_s(now_ms)
        if age > limit:
            raise StaleData(f"{self.kind} is {age:.1f} s old (limit {limit:g} s)")
        if age < -FUTURE_TOLERANCE_S:
            raise StaleData(f"{self.kind} timestamp is {-age:.1f} s in the future (clock problem)")
        if self.latency_ms / 1000.0 > limit:
            raise StaleData(f"{self.kind} response took {self.latency_ms} ms (limit {limit:g} s)")
        return self.value


def stamp(value, kind: str, env, exchange_ts: int | None = None) -> Stamped:
    """Wrap a parsed value with the freshest exchange timestamp available on its response envelope."""
    skew = env.skew_ms if getattr(env, "skew_ms", None) is not None else 0
    if exchange_ts:
        return Stamped(value, kind, int(exchange_ts), skew, env.latency_ms, True)
    if env.server_ts:
        return Stamped(value, kind, int(env.server_ts), skew, env.latency_ms, True)
    return Stamped(value, kind, int(env.recv_ms), 0, env.latency_ms, False)


def fetch_quote(symbol: str, client=None) -> Stamped:
    """Live book ticker from Pionex; .require() before use."""
    if client is None:
        from ..exchange.pionex_public import PionexPublic
        client = PionexPublic()
    t, env = client.book_ticker(symbol)
    return stamp(t, "quote", env, t.exchange_ts)


def fetch_symbol_rules(symbol: str, client=None) -> Stamped:
    """Live symbol rules (minimums, precision) from Pionex; refetch instead of caching past one day."""
    if client is None:
        from ..exchange.pionex_public import PionexPublic
        client = PionexPublic()
    rules, env = client.symbols([symbol])
    hit = [r for r in rules if r.symbol == symbol]
    if len(hit) != 1:
        raise StaleData(f"no live symbol rules for {symbol}")
    return stamp(hit[0], "symbol_rules", env)


def stamp_account(value, env_or_ms) -> Stamped:
    """Account state from the read-only reader: pass the response envelope, or the epoch ms it was read at."""
    if isinstance(env_or_ms, int):
        return Stamped(value, "account", env_or_ms, 0, 0, False)
    return stamp(value, "account", env_or_ms)
