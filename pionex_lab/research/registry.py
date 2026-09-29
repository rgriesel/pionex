"""Experiment registry: every trial, candidate, and rejection is retained."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..util import canonical_json, ro_uri, utc_day

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS cycles(id TEXT PRIMARY KEY, started_at INTEGER NOT NULL, finished_at INTEGER,
  utc_day TEXT NOT NULL, hypotheses INTEGER NOT NULL, trials INTEGER NOT NULL, budget TEXT NOT NULL,
  data TEXT NOT NULL, note TEXT);
CREATE TABLE IF NOT EXISTS trials(id INTEGER PRIMARY KEY, cycle_id TEXT NOT NULL, strategy TEXT NOT NULL,
  params TEXT NOT NULL, window TEXT NOT NULL, n INTEGER NOT NULL, expectancy_bps REAL, total_bps REAL,
  profit_factor REAL, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS candidates(id INTEGER PRIMARY KEY, cycle_id TEXT NOT NULL, strategy TEXT NOT NULL,
  version TEXT NOT NULL, params TEXT, status TEXT NOT NULL, gates TEXT NOT NULL, metrics TEXT NOT NULL,
  edge_lower_gross_bps REAL, data_hash TEXT NOT NULL, code_hash TEXT NOT NULL, created_at INTEGER NOT NULL,
  frozen_at INTEGER);
CREATE TRIGGER IF NOT EXISTS trials_no_update BEFORE UPDATE ON trials BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS trials_no_delete BEFORE DELETE ON trials BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS cand_no_delete BEFORE DELETE ON candidates BEGIN SELECT RAISE(ABORT, 'append-only'); END;
"""


class Registry:
    def __init__(self, path: Path | str, readonly: bool = False):
        self.path = Path(path)
        if readonly:
            self.conn = sqlite3.connect(ro_uri(self.path), uri=True, check_same_thread=False)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(self.path, check_same_thread=False)
            self.conn.executescript(SCHEMA)
        self.conn.row_factory = sqlite3.Row

    def cycles_on(self, day: str) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM cycles WHERE utc_day=?", (day,)).fetchone()[0]

    def start_cycle(self, cycle_id, now, hypotheses, trials, budget, data, note=""):
        with self.conn:
            self.conn.execute("INSERT INTO cycles(id, started_at, utc_day, hypotheses, trials, budget, data, note) "
                              "VALUES(?,?,?,?,?,?,?,?)", (cycle_id, now, utc_day(now), hypotheses, trials,
                                                         canonical_json(budget), canonical_json(data), note))

    def finish_cycle(self, cycle_id, now):
        with self.conn:
            self.conn.execute("UPDATE cycles SET finished_at=? WHERE id=?", (now, cycle_id))

    def add_trial(self, cycle_id, strategy, params, window, summary, now):
        with self.conn:
            self.conn.execute("INSERT INTO trials(cycle_id, strategy, params, window, n, expectancy_bps, total_bps, "
                              "profit_factor, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                              (cycle_id, strategy, canonical_json(params), window, summary["n"],
                               summary["expectancy_bps"], summary["total_bps"], summary["profit_factor"], now))

    def add_candidate(self, cycle_id, strategy, version, params, status, gates, metrics, edge, data_hash,
                      code_hash, now):
        with self.conn:
            self.conn.execute("INSERT INTO candidates(cycle_id, strategy, version, params, status, gates, metrics, "
                              "edge_lower_gross_bps, data_hash, code_hash, created_at, frozen_at) "
                              "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                              (cycle_id, strategy, version, canonical_json(params) if params is not None else None,
                               status, canonical_json(gates), canonical_json(metrics), edge, data_hash, code_hash,
                               now, now))

    def latest_candidates(self) -> dict:
        """Most recent candidate per strategy/version (the frozen parameter set)."""
        rows = self.conn.execute("SELECT * FROM candidates c WHERE id=(SELECT MAX(id) FROM candidates d WHERE "
                                 "d.strategy=c.strategy AND d.version=c.version)").fetchall()
        out = {}
        for r in rows:
            d = dict(r)
            d["params"] = json.loads(d["params"]) if d["params"] else None
            d["gates"] = json.loads(d["gates"])
            d["metrics"] = json.loads(d["metrics"])
            out[f"{d['strategy']}/{d['version']}"] = d
        return out

    def trial_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM trials").fetchone()[0]

    def rejected(self) -> list:
        return [dict(r) for r in self.conn.execute(
            "SELECT strategy, version, status, gates, created_at FROM candidates WHERE status!='QUALIFIED_FOR_PAPER' "
            "ORDER BY id")]
