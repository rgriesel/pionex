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
CREATE TABLE IF NOT EXISTS bots(id INTEGER PRIMARY KEY, at INTEGER NOT NULL, bu_order_id TEXT, type TEXT, pair TEXT,
  "range" TEXT, grids INTEGER, investment TEXT, grid_profit TEXT, float_profit TEXT, status TEXT, raw TEXT, error TEXT);
CREATE INDEX IF NOT EXISTS bots_at ON bots(at);
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


BOT_LIST, BOT_DETAIL = "/api/v1/bot/orders", {"spot_grid": "/api/v1/bot/orders/spotGrid/order",
                                                "futures_grid": "/api/v1/bot/orders/futuresGrid/order"}
BOT_EVERY_MS = 3_600_000
MAX_PAGES, MAX_BOTS = 5, 100


def _first(d: dict, *names):
    for n in names:
        if isinstance(d, dict) and d.get(n) not in (None, ""):
            return d[n]
    return None


def _num(v):
    try:
        return str(float(v)) if v is not None else None
    except (TypeError, ValueError):
        return None


def _orders(body: dict) -> tuple[list, str | None]:
    data = body.get("data") if isinstance(body, dict) else None
    if isinstance(data, list):
        return data, None
    if isinstance(data, dict):
        for k in ("orders", "list", "buOrders", "rows"):
            if isinstance(data.get(k), list):
                return data[k], data.get("pageToken") or None
    return [], None


def bot_row(now: int, summary: dict, detail: dict | None) -> dict:
    """One `bots` row. The docs give no separate float-profit field for spot grids; realizedProfit is
    documented as grid profit + float P&L, so float = realizedProfit - gridProfit when both exist (futures: NULL).
    `raw` keeps the full responses so any of this can be re-derived."""
    d = detail.get("data", {}) if isinstance(detail, dict) else {}
    o = d.get("buOrderData", d) if isinstance(d, dict) else {}
    if not isinstance(o, dict):
        o = {}
    s = summary if isinstance(summary, dict) else {}
    grid, realized = _num(_first(o, "gridProfit")), _num(_first(o, "realizedProfit"))
    fl = None if grid is None or realized is None else str(float(realized) - float(grid))
    top, bottom = _first(o, "top"), _first(o, "bottom")
    return {"at": now, "bu_order_id": _first(s, "buOrderId") or _first(o, "buOrderId"),
            "type": _first(s, "buOrderType"), "pair": _first(s, "base") and f"{s.get('base')}_{s.get('quote')}",
            "range": None if top is None or bottom is None else f"{bottom}-{top}",
            "grids": _first(o, "row"), "investment": _num(_first(o, "quoteTotalInvestment", "quoteInvestment")),
            "grid_profit": grid, "float_profit": fl, "status": _first(o, "status") or _first(s, "status"),
            "raw": json.dumps({"summary": s, "detail": detail}), "error": None}


def bots_once(paths, creds, now_ms: int | None = None, get=signed_get) -> list[dict]:
    """GET-only: list running + finished bots, fetch each one's detail, store rows. A failure (e.g. the key
    lacks `Bot reading`) is stored as one error row and the pass ends; there is no retry here."""
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    rows = []
    try:
        for status in ("running", "finished"):
            token, seen = None, 0
            for _ in range(MAX_PAGES):
                q = {"status": status, **({"pageToken": token} if token else {})}
                items, token = _orders(get(creds, BOT_LIST, q))
                for s in items[:max(0, MAX_BOTS - len(rows))]:
                    path, bid = BOT_DETAIL.get(s.get("buOrderType")), s.get("buOrderId")
                    detail = get(creds, path, {"buOrderId": bid}) if path and bid else None
                    rows.append(bot_row(now, s, detail))
                if not token or len(rows) >= MAX_BOTS:
                    break
    except AccountReadError as exc:
        rows.append({"at": now, "bu_order_id": None, "type": None, "pair": None, "range": None, "grids": None,
                     "investment": None, "grid_profit": None, "float_profit": None, "status": None,
                     "raw": None, "error": str(exc)[:500]})
    cols = ("at", "bu_order_id", "type", "pair", "range", "grids", "investment", "grid_profit", "float_profit",
            "status", "raw", "error")
    conn = connect(paths)
    with conn:
        conn.executemany(f"INSERT INTO bots({','.join(chr(34) + c + chr(34) for c in cols)}) "
                         f"VALUES({','.join('?' * len(cols))})", [tuple(r[c] for c in cols) for r in rows])
    conn.close()
    return rows


def bots_due(paths, now_ms: int) -> bool:
    conn = connect(paths)
    try:
        last = conn.execute("SELECT MAX(at) FROM bots").fetchone()[0]
    finally:
        conn.close()
    return last is None or now_ms - last >= BOT_EVERY_MS


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
        if bots_due(paths, row["at"]):
            for b in bots_once(paths, creds, row["at"]):
                if b["error"]:
                    log.warning("bot read failed: %s", b["error"])
        if once or stop.wait(poll):
            return 0 if not row["error"] else 3
