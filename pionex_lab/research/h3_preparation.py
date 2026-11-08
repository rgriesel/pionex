"""Data-only preparation of existing CLO-247 trial 171; no signal or return evaluation."""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path

from ..data.store import Bars, resample
from . import own_edge_clo247 as frozen

HOUR = 3_600_000
START, END = 1672531200000, 1790812800000  # 2023-01-01, 2026-10-01 UTC
SOURCE_LF = "f150c7211e6adadce88f48d7a545d8fc14bf491aa8e00bfecd982dbabeee368c"
SOURCE_CRLF = "4d18507a0149f011e54661e12e67eea47dff6b8608e5d75775d51703069cbbbb"


def prepare_rows(rows, symbol, start=START, end=END):
    """Frozen 2026-11-08 03:55:31 SAST BEFORE data inspection/test execution.

    Data acceptance only; not a new strategy trial or performance pass criterion.
    Use the existing fixed [2023-01-01,2026-10-01) interval, BTC/ETH spot hourly
    Binance PROXY, base-asset volume from archive CSV column 5 (zero based).
    Require exact UTC-hour timestamps, finite valid OHLCV, complete=1, unique
    ordered rows. Reject malformed input; never interpolate. Emit 4h bars only
    with all four exact hourly constituents; reuse store.resample AFTER validation.
    Certify continuity only when all expected hours and 4h bins exist. Gaps
    remain explicit and prohibit running the frozen strategy on concatenated
    segments. Source, 24h hold, active stop/TP, costs, gates and trial count stay
    unchanged. No calls to signal builders/replay on market observations.
    """
    if start % frozen.BAR_MS or end % frozen.BAR_MS or end <= start:
        raise ValueError("interval must contain whole UTC 4h bins")
    b = Bars(symbol, "60M", [], [], [], [], [], [])
    previous = None
    for row in rows:
        t, *values, complete, fetched_at = row
        vals = list(map(float, values))
        o, h, l, c, v = vals
        if (type(t) is not int or t % HOUR or not start <= t < end or
                (previous is not None and t <= previous) or complete != 1 or
                not all(math.isfinite(x) for x in vals) or min(o, h, l, c) <= 0 or
                v < 0 or h < max(o, c) or l > min(o, c) or h < l):
            raise ValueError("invalid, incomplete, duplicate or unordered hourly row")
        b.t.append(t)
        for k, value in zip("ohlcv", vals):
            getattr(b, k).append(value)
        previous = t
    missing = sorted(set(range(start, end, HOUR)) - set(b.t))
    four = resample(b, "4H")
    missing_four = sorted(set(range(start, end, frozen.BAR_MS)) - set(four.t))
    # Only a contiguous full sample can be passed to the unmodified strategy.
    if not missing:
        frozen.validate_bars({k: getattr(four, k) for k in "tohlcv"})
    return {"symbol": symbol, "hourly_rows": len(b), "expected_hours": (end-start)//HOUR,
            "missing_hours": missing, "four_hour_rows": len(four),
            "missing_four_hour_bins": missing_four,
            "continuous": not missing and not missing_four,
            "base_volume_sum_hourly": sum(b.v), "base_volume_sum_4h": sum(four.v),
            "zero_volume_hours": sum(x == 0 for x in b.v)}


def freeze(database, destination):
    """Freeze selected SQLite rows in one read transaction, plus content hashes.

    Data protocol pre-registered 2026-11-08 03:55:31 SAST in prepare_rows.
    Refuse overwrite: later data changes require a separately named manifest.
    """
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    source = Path(frozen.__file__).read_bytes()
    lf = source.replace(b"\r\n", b"\n")
    if hashlib.sha256(lf).hexdigest() != SOURCE_LF:
        raise ValueError("frozen source differs from existing trial 171")
    report = {"kind": "DATA_PREPARATION_NOT_PERFORMANCE", "trial": 171,
              "venue": "Binance spot PROXY; not Pionex", "interval_utc":
              ["2023-01-01T00:00:00Z", "2026-10-01T00:00:00Z"],
              "start_ms": START, "end_exclusive_ms": END,
              "source_sha256_lf": SOURCE_LF, "original_source_sha256_crlf": SOURCE_CRLF,
              "source_identity": "same bytes after line-ending normalization; no rule edits",
              "volume": "base BTC or ETH units; CSV col 5, parser pionex_lab/data/proxy.py",
              "database": str(Path(database).resolve()), "symbols": [],
              "market_evaluations": 0, "new_trial_registrations": 0,
              "approval_dependency": "CLO-247: CEO/board confirm proposed screen gates",
              "other_dependencies": ["proxy tracking evidence before research use",
                  "untouched Pionex forward evidence remains required; archive is screening only"],
              "strategy_verdict": None, "return_evaluation_authorized": False}
    snapshots = {}
    with sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True) as conn:
        conn.execute("BEGIN")
        for symbol in ("BTC_USDT", "ETH_USDT"):
            rows = conn.execute("SELECT open_time,open,high,low,close,volume,complete,fetched_at "
                                "FROM klines WHERE symbol=? AND interval='60M' "
                                "AND open_time>=? AND open_time<? ORDER BY open_time",
                                (symbol, START, END)).fetchall()
            summary = prepare_rows(rows, symbol)
            payload = json.dumps(rows, separators=(",", ":")).encode()
            summary["snapshot_sha256"] = hashlib.sha256(payload).hexdigest()
            summary["snapshot_file"] = symbol + "_60M.json"
            snapshots[summary["snapshot_file"]] = payload
            report["symbols"].append(summary)
    destination.mkdir(parents=True)
    for name, payload in snapshots.items():
        (destination / name).write_bytes(payload)
    (destination / "manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
