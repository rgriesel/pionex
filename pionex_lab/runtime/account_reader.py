"""Poll the user's own Pionex account (read-only) into var/account.db for the dashboard.

Enabled only when var/account.json (git-ignored) names the credentials file:
    {"env_file": "C:\\\\path\\\\to\\\\.env", "poll_seconds": 60}
Optional "key_var"/"secret_var" pick the variable names. See exchange/account.py for the
read-only guarantees. Rows hold balances and valuations, never credentials.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path

from ..exchange.account import AccountReadError, load_credentials, signed_get

log = logging.getLogger("pionex_lab.account")
FULL = "/api/v1/wallet/balancesFull"
SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY, at INTEGER NOT NULL, endpoint TEXT NOT NULL,
  equity_usdt TEXT, raw TEXT, error TEXT);
CREATE INDEX IF NOT EXISTS snapshots_at ON snapshots(at);
"""


def config_path(paths) -> Path:
    return paths.root / "account.json"


def db_path(paths) -> Path:
    return paths.root / "account.db"


def connect(paths, readonly: bool = False) -> sqlite3.Connection:
    p = db_path(paths)
    if readonly:
        conn = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(p)
        conn.executescript(SCHEMA)
    conn.row_factory = sqlite3.Row
    return conn


def total_usdt(body: dict):
    """Pionex's own total USDT valuation (all accounts, bots included) from balancesFull."""
    from decimal import Decimal, InvalidOperation
    try:
        v = Decimal(str(body["data"]["totalInUsdt"]))
    except (KeyError, TypeError, InvalidOperation):
        return None
    return v if v.is_finite() and v >= 0 else None


def snapshot_once(paths, conf: dict, creds, now_ms: int | None = None, get=signed_get) -> dict:
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    conn = connect(paths)
    try:
        body = get(creds, FULL)
        eq = total_usdt(body)
        row = {"at": now, "endpoint": FULL, "equity_usdt": None if eq is None else str(eq),
               "raw": json.dumps(body), "error": None}
    except AccountReadError as exc:
        row = {"at": now, "endpoint": FULL, "equity_usdt": None, "raw": None, "error": str(exc)[:500]}
    with conn:
        conn.execute("INSERT INTO snapshots(at, endpoint, equity_usdt, raw, error) VALUES(?,?,?,?,?)",
                     (row["at"], row["endpoint"], row["equity_usdt"], row["raw"], row["error"]))
    conn.close()
    return row


def run(paths, stop, once: bool = False) -> int:
    cfg = config_path(paths)
    if not cfg.exists():
        log.info("account reader disabled: %s not present", cfg)
        return 0
    conf = json.loads(cfg.read_text(encoding="utf-8"))
    creds = load_credentials(conf["env_file"], conf.get("key_var"), conf.get("secret_var"))
    log.info("account reader started (read-only endpoints only), credentials from %s", creds.source)
    poll = max(30.0, float(conf.get("poll_seconds", 60)))
    while True:
        row = snapshot_once(paths, conf, creds)
        if row["error"]:
            log.warning("account read failed: %s", row["error"])
        if once or stop.wait(poll):
            return 0 if not row["error"] else 3
