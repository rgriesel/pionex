"""Point-in-time data validation: gaps, duplicates, OHLC consistency, freshness."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..exchange.pionex_public import KLINE_INTERVALS


@dataclass
class BarQuality:
    count: int
    first: int | None
    last: int | None
    gaps: list = field(default_factory=list)          # (missing_from_open_time, missing_count)
    invalid: list = field(default_factory=list)       # open_times with bad OHLC/volume
    non_monotonic: int = 0

    @property
    def missing_bars(self) -> int:
        return sum(n for _, n in self.gaps)

    @property
    def ok(self) -> bool:
        return not self.gaps and not self.invalid and self.non_monotonic == 0

    def summary(self) -> dict:
        return {"count": self.count, "first": self.first, "last": self.last, "gap_count": len(self.gaps),
                "missing_bars": self.missing_bars, "invalid_bars": len(self.invalid),
                "non_monotonic": self.non_monotonic}


def check_bars(bars) -> BarQuality:
    step = KLINE_INTERVALS[bars.interval]
    q = BarQuality(count=len(bars), first=bars.t[0] if len(bars) else None, last=bars.t[-1] if len(bars) else None)
    for i in range(len(bars)):
        vals = (bars.o[i], bars.h[i], bars.l[i], bars.c[i], bars.v[i])
        if (not all(math.isfinite(x) for x in vals) or min(vals[:4]) <= 0 or bars.v[i] < 0
                or bars.l[i] > min(bars.o[i], bars.c[i]) or bars.h[i] < max(bars.o[i], bars.c[i])):
            q.invalid.append(bars.t[i])
        if bars.t[i] % step:
            q.invalid.append(bars.t[i])
        if i:
            d = bars.t[i] - bars.t[i - 1]
            if d <= 0:
                q.non_monotonic += 1
            elif d > step:
                q.gaps.append((bars.t[i - 1] + step, d // step - 1))
    return q


def expected_last_complete(now_ms: int, interval: str) -> int:
    """Open time of the most recent bar that has fully closed by now_ms."""
    step = KLINE_INTERVALS[interval]
    return (now_ms // step) * step - step


def window_ready(bars, need: int, now_ms: int, grace_ms: int = 90_000) -> tuple[bool, str]:
    """True if the last `need` bars are contiguous, valid, and current.

    A bar that closed less than `grace_ms` ago may not be published yet, so the
    previous bar is also accepted during that grace period.
    """
    step = KLINE_INTERVALS[bars.interval]
    if len(bars) < need:
        return False, "INSUFFICIENT_HISTORY"
    tail = bars.slice(len(bars) - need, len(bars))
    q = check_bars(tail)
    if q.gaps:
        return False, "DATA_GAP"
    if q.invalid or q.non_monotonic:
        return False, "INVALID_BARS"
    expected = expected_last_complete(now_ms, bars.interval)
    if tail.t[-1] == expected:
        return True, "OK"
    if tail.t[-1] == expected - step and now_ms - (expected + step) < grace_ms:
        return True, "OK_GRACE"
    return False, "STALE_BARS"
