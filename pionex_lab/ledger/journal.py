"""Canonical append-only journal (SQLite) with a SHA-256 hash chain.

UPDATE and DELETE are rejected by triggers; each row commits to its predecessor's
hash, so any out-of-band edit is detectable with verify(). The engine is the only
writer (guarded by the risk service's lease). Readers open the file read-only.
"""
from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from pathlib import Path

from ..util import canonical_json, ro_uri, sha256_bytes

GENESIS = "0" * 64

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS journal(
  seq INTEGER PRIMARY KEY,
  at_ms INTEGER NOT NULL,
  kind TEXT NOT NULL,
  payload TEXT NOT NULL,
  prev_hash TEXT NOT NULL,
  hash TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS journal_kind ON journal(kind, seq);
CREATE TRIGGER IF NOT EXISTS journal_no_update BEFORE UPDATE ON journal
  BEGIN SELECT RAISE(ABORT, 'journal is append-only'); END;
CREATE TRIGGER IF NOT EXISTS journal_no_delete BEFORE DELETE ON journal
  BEGIN SELECT RAISE(ABORT, 'journal is append-only'); END;
CREATE TABLE IF NOT EXISTS runtime_status(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_ms INTEGER NOT NULL);
"""

KINDS = {
    "MANDATE_LOADED", "STATE_TRANSITION", "EXPERIMENT_STARTED", "EXPERIMENT_COMPLETE", "UNIVERSE_DECISION",
    "DECISION", "RISK_DECISION", "ORDER_INTENT", "FILL", "ORDER_FINAL", "POSITION_OPENED", "POSITION_CLOSED",
    "SNAPSHOT", "BENCHMARK_STARTED", "LATCH_SET", "LATCH_CLEARED", "INCIDENT", "SHADOW_OPEN", "SHADOW_CLOSE",
    "OPERATING_COST", "DAILY_REVIEW", "RECOVERY", "RECONCILIATION", "LIVE_PREFLIGHT",
}


def _row_hash(prev_hash: str, seq: int, at_ms: int, kind: str, payload: str) -> str:
    return sha256_bytes(f"{prev_hash}|{seq}|{at_ms}|{kind}|{payload}".encode("utf-8"))


class Journal:
    def __init__(self, path: Path | str, readonly: bool = False):
        self.path = Path(path)
        self.readonly = readonly
        if readonly:
            self.conn = sqlite3.connect(ro_uri(self.path), uri=True, timeout=10, check_same_thread=False)
            self.conn.execute("PRAGMA query_only=ON")
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(self.path, timeout=10, check_same_thread=False, isolation_level=None)
            self.conn.executescript(SCHEMA)
        self.conn.row_factory = sqlite3.Row

    def close(self):
        self.conn.close()

    def append(self, kind: str, payload: dict, at_ms: int) -> int:
        if self.readonly:
            raise PermissionError("journal opened read-only")
        if kind not in KINDS:
            raise ValueError(f"unknown journal kind {kind}")
        body = canonical_json(payload)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            last = self.conn.execute("SELECT seq, hash FROM journal ORDER BY seq DESC LIMIT 1").fetchone()
            seq = (last["seq"] + 1) if last else 1
            prev = last["hash"] if last else GENESIS
            h = _row_hash(prev, seq, int(at_ms), kind, body)
            self.conn.execute("INSERT INTO journal(seq, at_ms, kind, payload, prev_hash, hash) VALUES(?,?,?,?,?,?)",
                              (seq, int(at_ms), kind, body, prev, h))
            self.conn.execute("COMMIT")
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        return seq

    def events(self, kinds=None, since_seq: int = 0):
        q = "SELECT seq, at_ms, kind, payload FROM journal WHERE seq>?"
        args: list = [since_seq]
        if kinds:
            kinds = list(kinds)
            q += " AND kind IN (%s)" % ",".join("?" * len(kinds))
            args += kinds
        q += " ORDER BY seq"
        for row in self.conn.execute(q, args):
            yield row["seq"], row["at_ms"], row["kind"], json.loads(row["payload"], parse_float=Decimal)

    def last(self, kind: str):
        row = self.conn.execute("SELECT seq, at_ms, payload FROM journal WHERE kind=? ORDER BY seq DESC LIMIT 1",
                                (kind,)).fetchone()
        if row is None:
            return None
        return row["seq"], row["at_ms"], json.loads(row["payload"], parse_float=Decimal)

    def count(self, kind: str | None = None) -> int:
        if kind:
            return self.conn.execute("SELECT COUNT(*) FROM journal WHERE kind=?", (kind,)).fetchone()[0]
        return self.conn.execute("SELECT COUNT(*) FROM journal").fetchone()[0]

    def head(self):
        row = self.conn.execute("SELECT seq, hash FROM journal ORDER BY seq DESC LIMIT 1").fetchone()
        return (row["seq"], row["hash"]) if row else (0, GENESIS)

    def verify(self) -> tuple[bool, int | None, int]:
        """Recompute the chain. Returns (ok, first_bad_seq, rows_checked)."""
        prev = GENESIS
        expected_seq = 1
        n = 0
        for row in self.conn.execute("SELECT seq, at_ms, kind, payload, prev_hash, hash FROM journal ORDER BY seq"):
            n += 1
            if (row["seq"] != expected_seq or row["prev_hash"] != prev
                    or _row_hash(prev, row["seq"], row["at_ms"], row["kind"], row["payload"]) != row["hash"]):
                return False, row["seq"], n
            prev = row["hash"]
            expected_seq += 1
        return True, None, n

    # Mutable operational telemetry (heartbeats) lives outside the canonical chain.
    def set_status(self, key: str, value, now_ms: int) -> None:
        if self.readonly:
            raise PermissionError("journal opened read-only")
        self.conn.execute("INSERT INTO runtime_status(key, value, updated_ms) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE "
                          "SET value=excluded.value, updated_ms=excluded.updated_ms", (key, canonical_json(value), now_ms))

    def get_status(self, key: str):
        row = self.conn.execute("SELECT value, updated_ms FROM runtime_status WHERE key=?", (key,)).fetchone()
        return (json.loads(row["value"], parse_float=Decimal), row["updated_ms"]) if row else (None, None)
