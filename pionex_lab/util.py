"""Shared helpers: exact decimals, UTC time, canonical JSON, hashing, clocks."""
from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN, getcontext
from pathlib import Path

getcontext().prec = 40
D = Decimal
ZERO = Decimal(0)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class DataError(ValueError):
    """Input failed validation; callers must fail closed."""


def dec(value, name="value", positive=False, allow_zero=True) -> Decimal:
    """Strict Decimal parse: rejects bool, None, NaN, infinities, negatives."""
    if isinstance(value, bool) or value is None:
        raise DataError(f"{name}: invalid {value!r}")
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DataError(f"{name}: not a number {value!r}") from exc
    if not out.is_finite() or out < 0:
        raise DataError(f"{name}: must be finite and non-negative, got {value!r}")
    if (positive or not allow_zero) and out == 0:
        raise DataError(f"{name}: must be positive")
    return out


def fnum(value, name="value") -> float:
    """Strict float parse for research code (not used for sizing)."""
    out = float(dec(value, name))
    if not math.isfinite(out):
        raise DataError(f"{name}: non-finite")
    return out


def round_down(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        raise DataError("step must be positive")
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def step_from_precision(precision: int) -> Decimal:
    if isinstance(precision, bool) or not isinstance(precision, int) or not 0 <= precision <= 18:
        raise DataError(f"precision out of range: {precision!r}")
    return Decimal(1).scaleb(-precision)


def iso_ms(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(ms) % 1000:03d}Z"


def parse_iso_ms(text: str) -> int:
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise DataError("timestamp without timezone")
    return int(round(dt.timestamp() * 1000))


def utc_day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def utc_week(ms: int) -> str:
    """ISO week label; ISO weeks start Monday 00:00 UTC as the mandate requires."""
    y, w, _ = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isocalendar()
    return f"{y}-W{w:02d}"


def _json_default(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (set, tuple)):
        return list(obj)
    raise TypeError(f"not JSON serializable: {type(obj).__name__}")


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=_json_default, allow_nan=False)


def pretty_json(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, default=_json_default, allow_nan=False)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path) -> str:
    return sha256_bytes(Path(path).read_bytes())


class SystemClock:
    def now_ms(self) -> int:
        return int(time.time() * 1000)

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)


class FakeClock:
    """Deterministic clock for tests and replays."""

    def __init__(self, start_ms: int):
        self.t = int(start_ms)

    def now_ms(self) -> int:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)

    def advance(self, seconds: float) -> None:
        self.t += int(round(seconds * 1000))


def ro_uri(path) -> str:
    """Read-only SQLite URI that is valid on Windows drive paths and paths with spaces, # or ?."""
    return Path(path).resolve().as_uri() + "?mode=ro"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
