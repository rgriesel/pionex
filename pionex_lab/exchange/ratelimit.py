"""Shared weighted token bucket with exit/recovery headroom and 429 ban handling.

The mandate sets a conservative local budget of 5 weight/second. Normal requests may
not consume the reserved headroom, so exit and reconciliation calls can still run
while collection is saturated. A 429/418 response bans all traffic until the
server's retry interval (or a bounded jittered backoff) has elapsed.
"""
from __future__ import annotations

import random
import threading

from ..util import SystemClock


class RateLimited(RuntimeError):
    def __init__(self, retry_after_s: float, detail: str = ""):
        super().__init__(f"rate limited; retry after {retry_after_s:.1f}s {detail}".strip())
        self.retry_after_s = retry_after_s


class WeightedLimiter:
    PRIORITIES = ("normal", "exit")

    def __init__(self, rate_per_s: float = 5.0, burst: float | None = None,
                 exit_reserve: float = 1.0, clock=None, rng=None):
        if rate_per_s <= 0:
            raise ValueError("rate must be positive")
        self.rate = float(rate_per_s)
        self.capacity = float(burst if burst is not None else rate_per_s)
        self.exit_reserve = float(exit_reserve)
        self.clock = clock or SystemClock()
        self.rng = rng or random.Random()
        self._tokens = self.capacity
        self._last_ms = self.clock.now_ms()
        self._ban_until_ms = 0
        self._consecutive_bans = 0
        self._lock = threading.Lock()

    def _refill(self, now_ms: int) -> None:
        elapsed = max(0, now_ms - self._last_ms) / 1000.0
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last_ms = now_ms

    def wait_time(self, weight: float, priority: str = "normal") -> float:
        """Seconds until `weight` could be granted (0 if now)."""
        if priority not in self.PRIORITIES:
            raise ValueError(priority)
        with self._lock:
            now = self.clock.now_ms()
            self._refill(now)
            ban_wait = max(0, self._ban_until_ms - now) / 1000.0
            floor = 0.0 if priority == "exit" else self.exit_reserve
            deficit = weight + floor - self._tokens
            token_wait = max(0.0, deficit / self.rate)
            return max(ban_wait, token_wait)

    def try_acquire(self, weight: float, priority: str = "normal") -> bool:
        if weight <= 0 or weight > self.capacity:
            raise ValueError("weight out of range")
        with self._lock:
            now = self.clock.now_ms()
            self._refill(now)
            if now < self._ban_until_ms:
                return False
            floor = 0.0 if priority == "exit" else self.exit_reserve
            if self._tokens - weight < floor - 1e-9:
                return False
            self._tokens -= weight
            return True

    def acquire(self, weight: float = 1.0, priority: str = "normal", max_wait_s: float = 30.0) -> None:
        waited = 0.0
        while not self.try_acquire(weight, priority):
            delay = min(max(self.wait_time(weight, priority), 0.01), 5.0)
            if waited + delay > max_wait_s:
                raise RateLimited(self.wait_time(weight, priority), "local budget exhausted")
            self.clock.sleep(delay)
            waited += delay

    def ban(self, retry_after_s: float | None) -> float:
        """Record a server-side limit. Returns the enforced pause in seconds."""
        with self._lock:
            self._consecutive_bans += 1
            if retry_after_s is None or retry_after_s <= 0:
                base = min(60.0, 2.0 ** self._consecutive_bans)
                retry_after_s = base / 2 + self.rng.random() * base / 2  # bounded jitter
            pause = min(float(retry_after_s), 3600.0)
            self._ban_until_ms = max(self._ban_until_ms, self.clock.now_ms() + int(pause * 1000))
            self._tokens = 0.0
            return pause

    def success(self) -> None:
        with self._lock:
            self._consecutive_bans = 0

    @property
    def banned_until_ms(self) -> int:
        return self._ban_until_ms
