"""Market-data store (SQLite, WAL). The collector is the only writer.

Prices are stored as exact decimal strings. Every row carries the local receive time
(`fetched_at`, ms UTC) and, where available, the server envelope timestamp, so
decisions can be replayed point-in-time and feed age / clock skew can be audited.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from ..exchange.pionex_public import KLINE_INTERVALS, BookTicker, Depth, SymbolRules, parse_symbols
from ..util import canonical_json

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS symbols(symbol TEXT PRIMARY KEY, raw TEXT NOT NULL, enabled INTEGER NOT NULL,
  fetched_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS book_ticks(id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, bid TEXT NOT NULL,
  bid_size TEXT NOT NULL, ask TEXT NOT NULL, ask_size TEXT NOT NULL, exchange_ts INTEGER, server_ts INTEGER,
  fetched_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS book_ticks_sym_t ON book_ticks(symbol, fetched_at);
CREATE TABLE IF NOT EXISTS depth_snaps(id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, bids TEXT NOT NULL,
  asks TEXT NOT NULL, update_ts INTEGER, server_ts INTEGER, fetched_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS depth_sym_t ON depth_snaps(symbol, fetched_at);
CREATE TABLE IF NOT EXISTS klines(symbol TEXT NOT NULL, interval TEXT NOT NULL, open_time INTEGER NOT NULL,
  open TEXT NOT NULL, high TEXT NOT NULL, low TEXT NOT NULL, close TEXT NOT NULL, volume TEXT NOT NULL,
  complete INTEGER NOT NULL, fetched_at INTEGER NOT NULL, PRIMARY KEY(symbol, interval, open_time));
CREATE TABLE IF NOT EXISTS fetch_log(id INTEGER PRIMARY KEY, at INTEGER NOT NULL, endpoint TEXT NOT NULL,
  ok INTEGER NOT NULL, latency_ms INTEGER, skew_ms INTEGER, error TEXT);
CREATE INDEX IF NOT EXISTS fetch_log_at ON fetch_log(at);
CREATE TABLE IF NOT EXISTS status(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at INTEGER NOT NULL);
"""


def connect(path: Path | str, readonly: bool = False) -> sqlite3.Connection:
    path = Path(path)
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10, check_same_thread=False)
        conn.execute("PRAGMA query_only=ON")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@dataclass
class Bars:
    """Completed bars as parallel float arrays (research/strategy use only)."""
    symbol: str
    interval: str
    t: list
    o: list
    h: list
    l: list
    c: list
    v: list

    def __len__(self):
        return len(self.t)

    @property
    def interval_ms(self) -> int:
        return KLINE_INTERVALS[self.interval]

    def slice(self, start: int, end: int) -> "Bars":
        return Bars(self.symbol, self.interval, self.t[start:end], self.o[start:end], self.h[start:end],
                    self.l[start:end], self.c[start:end], self.v[start:end])

    @classmethod
    def from_rows(cls, symbol, interval, rows) -> "Bars":
        b = cls(symbol, interval, [], [], [], [], [], [])
        for r in rows:
            b.t.append(int(r["open_time"]))
            b.o.append(float(r["open"]))
            b.h.append(float(r["high"]))
            b.l.append(float(r["low"]))
            b.c.append(float(r["close"]))
            b.v.append(float(r["volume"]))
        return b


class MarketView:
    """Read access used by the engine, research, and dashboard."""

    def __init__(self, path: Path | str, readonly: bool = True):
        self.path = Path(path)
        self.conn = connect(path, readonly=readonly)

    def close(self):
        self.conn.close()

    def latest_book(self, symbol: str, at_or_before: int | None = None):
        if at_or_before is None:
            row = self.conn.execute("SELECT * FROM book_ticks WHERE symbol=? ORDER BY fetched_at DESC, id DESC LIMIT 1",
                                    (symbol,)).fetchone()
        else:
            row = self.conn.execute("SELECT * FROM book_ticks WHERE symbol=? AND fetched_at<=? "
                                    "ORDER BY fetched_at DESC, id DESC LIMIT 1", (symbol, at_or_before)).fetchone()
        return _book(row)

    def first_book_after(self, symbol: str, after_ms: int):
        row = self.conn.execute("SELECT * FROM book_ticks WHERE symbol=? AND fetched_at>? "
                                "ORDER BY fetched_at ASC, id ASC LIMIT 1", (symbol, after_ms)).fetchone()
        return _book(row)

    def depth_near(self, symbol: str, after_ms: int, at_or_before: int):
        """Most recent depth snapshot fetched in (after_ms, at_or_before]."""
        row = self.conn.execute("SELECT * FROM depth_snaps WHERE symbol=? AND fetched_at>? AND fetched_at<=? "
                                "ORDER BY fetched_at DESC, id DESC LIMIT 1", (symbol, after_ms, at_or_before)).fetchone()
        if row is None:
            return None
        return {"bids": [(Decimal(p), Decimal(s)) for p, s in json.loads(row["bids"])],
                "asks": [(Decimal(p), Decimal(s)) for p, s in json.loads(row["asks"])],
                "fetched_at": row["fetched_at"], "update_ts": row["update_ts"]}

    def bars(self, symbol: str, interval: str, limit: int | None = None, end_ms: int | None = None,
             start_ms: int | None = None, complete_only: bool = True) -> Bars:
        q = "SELECT * FROM klines WHERE symbol=? AND interval=?"
        args: list = [symbol, interval]
        if complete_only:
            q += " AND complete=1"
        if end_ms is not None:  # bars whose close time is <= end_ms
            q += " AND open_time+?<=?"
            args += [KLINE_INTERVALS[interval], end_ms]
        if start_ms is not None:
            q += " AND open_time>=?"
            args.append(start_ms)
        if limit:
            q += " ORDER BY open_time DESC LIMIT ?"
            args.append(int(limit))
            rows = list(reversed(self.conn.execute(q, args).fetchall()))
        else:
            q += " ORDER BY open_time ASC"
            rows = self.conn.execute(q, args).fetchall()
        return Bars.from_rows(symbol, interval, rows)

    def symbol_rules(self, symbol: str):
        row = self.conn.execute("SELECT raw, fetched_at FROM symbols WHERE symbol=?", (symbol,)).fetchone()
        if row is None:
            return None, None
        rules = parse_symbols({"symbols": [json.loads(row["raw"])]})[0]
        return rules, row["fetched_at"]

    def status(self, key: str):
        row = self.conn.execute("SELECT value, updated_at FROM status WHERE key=?", (key,)).fetchone()
        return (json.loads(row["value"]), row["updated_at"]) if row else (None, None)

    def median_spread_bps(self, symbol: str, since_ms: int) -> float | None:
        rows = self.conn.execute("SELECT bid, ask FROM book_ticks WHERE symbol=? AND fetched_at>=?",
                                 (symbol, since_ms)).fetchall()
        spreads = sorted((float(r["ask"]) - float(r["bid"])) / ((float(r["ask"]) + float(r["bid"])) / 2) * 1e4
                         for r in rows)
        if not spreads:
            return None
        return spreads[len(spreads) // 2]

    def fetch_errors(self, since_ms: int) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM fetch_log WHERE at>=? AND ok=0", (since_ms,)).fetchone()[0]


def _book(row):
    if row is None:
        return None
    return {"symbol": row["symbol"], "bid": Decimal(row["bid"]), "bid_size": Decimal(row["bid_size"]),
            "ask": Decimal(row["ask"]), "ask_size": Decimal(row["ask_size"]), "exchange_ts": row["exchange_ts"],
            "server_ts": row["server_ts"], "fetched_at": row["fetched_at"]}


class MarketStore(MarketView):
    """Writer. Only the collector process should instantiate this."""

    def __init__(self, path: Path | str):
        super().__init__(path, readonly=False)
        self.conn.executescript(SCHEMA)

    def upsert_symbols(self, rules: list[SymbolRules], fetched_at: int) -> None:
        with self.conn:
            for r in rules:
                self.conn.execute("INSERT INTO symbols(symbol, raw, enabled, fetched_at) VALUES(?,?,?,?) "
                                  "ON CONFLICT(symbol) DO UPDATE SET raw=excluded.raw, enabled=excluded.enabled, "
                                  "fetched_at=excluded.fetched_at",
                                  (r.symbol, canonical_json(r.raw), int(r.enabled), fetched_at))

    def insert_book(self, bt: BookTicker, server_ts, fetched_at: int) -> None:
        with self.conn:
            self.conn.execute("INSERT INTO book_ticks(symbol, bid, bid_size, ask, ask_size, exchange_ts, server_ts, "
                              "fetched_at) VALUES(?,?,?,?,?,?,?,?)",
                              (bt.symbol, str(bt.bid), str(bt.bid_size), str(bt.ask), str(bt.ask_size),
                               bt.exchange_ts, server_ts, fetched_at))

    def insert_depth(self, symbol: str, depth: Depth, server_ts, fetched_at: int) -> None:
        with self.conn:
            self.conn.execute("INSERT INTO depth_snaps(symbol, bids, asks, update_ts, server_ts, fetched_at) "
                              "VALUES(?,?,?,?,?,?)",
                              (symbol, json.dumps([[str(p), str(s)] for p, s in depth.bids]),
                               json.dumps([[str(p), str(s)] for p, s in depth.asks]),
                               depth.update_ts, server_ts, fetched_at))

    def upsert_klines(self, symbol: str, interval: str, klines, server_ts, fetched_at: int) -> dict:
        """Mark a bar complete only when its close time is at or before the server time
        (or local receive time minus 1s if the server time is absent)."""
        ref = server_ts if server_ts is not None else fetched_at - 1000
        step = KLINE_INTERVALS[interval]
        revised = inserted = 0
        with self.conn:
            for k in klines:
                complete = int(k.open_time + step <= ref)
                prev = self.conn.execute("SELECT open, high, low, close, volume, complete FROM klines "
                                         "WHERE symbol=? AND interval=? AND open_time=?",
                                         (symbol, interval, k.open_time)).fetchone()
                vals = (str(k.open), str(k.high), str(k.low), str(k.close), str(k.volume))
                if prev is None:
                    inserted += 1
                elif prev["complete"] and tuple(prev[i] for i in range(5)) != vals:
                    revised += 1
                elif prev["complete"] and not complete:
                    continue  # never downgrade a completed bar
                self.conn.execute(
                    "INSERT INTO klines(symbol, interval, open_time, open, high, low, close, volume, complete, "
                    "fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(symbol, interval, open_time) DO UPDATE SET "
                    "open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close, "
                    "volume=excluded.volume, complete=MAX(klines.complete, excluded.complete), "
                    "fetched_at=excluded.fetched_at",
                    (symbol, interval, k.open_time, *vals, complete, fetched_at))
        return {"inserted": inserted, "revised": revised}

    def log_fetch(self, at: int, endpoint: str, ok: bool, latency_ms=None, skew_ms=None, error=None) -> None:
        with self.conn:
            self.conn.execute("INSERT INTO fetch_log(at, endpoint, ok, latency_ms, skew_ms, error) VALUES(?,?,?,?,?,?)",
                              (at, endpoint[:200], int(ok), latency_ms, skew_ms, (error or "")[:500] or None))

    def set_status(self, key: str, value, now_ms: int) -> None:
        with self.conn:
            self.conn.execute("INSERT INTO status(key, value, updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE "
                              "SET value=excluded.value, updated_at=excluded.updated_at",
                              (key, canonical_json(value), now_ms))

    def prune(self, now_ms: int, full_res_hours: float = 6.0, keep_days: float = 45.0) -> None:
        """Keep full-resolution quotes for recent hours, then one sample per minute."""
        cut = now_ms - int(full_res_hours * 3_600_000)
        old = now_ms - int(keep_days * 86_400_000)
        with self.conn:
            for table in ("book_ticks", "depth_snaps"):
                self.conn.execute(f"DELETE FROM {table} WHERE fetched_at<? AND id NOT IN (SELECT MIN(id) FROM {table} "
                                  f"WHERE fetched_at<? GROUP BY symbol, fetched_at/60000)", (cut, cut))
                self.conn.execute(f"DELETE FROM {table} WHERE fetched_at<?", (old,))
            self.conn.execute("DELETE FROM fetch_log WHERE at<?", (now_ms - 7 * 86_400_000,))
