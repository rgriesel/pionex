"""Live SHADOW SPOT grid bots on real-time Pionex prices (CLO-30). PAPER ONLY: public endpoints, no keys, no orders.

Pionex demo trading is app-only (no bots) and the Bot API has no sandbox, so this forward-tests the grid mechanics of
`swing/grid.py` (CLO-21) on the live public tape instead. Results are paper results on live quotes, not profit.

PRE-REGISTERED 2026-10-17 (SAST, machine clock), before the first start. Frozen; a changed idea is a new config id.
Owner's Pionex AI-recommended parameters are NOT available (the owner's key has no spot-grid bots to read; the AI
endpoint needs a signed call, which we do not make), so the bands are fixed percentages around the START price:
    id            symbol    band          rows  type       invest   stop-loss        take-profit
    BTC_narrow_v1 BTC_USDT  start +-4%     20   geometric  1000     bottom * 0.97    none
    BTC_medium_v1 BTC_USDT  start +-8%     40   geometric  1000     bottom * 0.97    none
    BTC_wide_v1   BTC_USDT  start +-16%    80   geometric  1000     bottom * 0.97    none
    ETH_medium_v1 ETH_USDT  start +-8%     40   geometric  1000     bottom * 0.97    none
Each has a step of ~0.40% (>= 4x the 0.10% round-trip fee), >= 12.5 USDT per grid (Pionex minimum 10), 1000 paper USDT.

Mechanics (same as grid.py, but event driven on the live tape):
  * Start: market buy at the ask of the base needed for every cell whose buy level is >= start price; the rest of the
    quote is reserved for buy orders below. Fee 0.05% per fill, no extra slippage (the initial buy pays the spread).
  * A resting order fills only when a real trade prints THROUGH its level (strict: buy when trade price < level, sell
    when > level), replayed in time order from the public trades feed (last 100 trades, polled every 5 s). This is
    stricter than a touch fill but ignores queue position. If more than 100 trades happened between polls (or the
    process was down) the oldest are lost: a `gap` event is written and the price is bridged straight to the current
    one (fills on the way are still booked, flagged in the event).
  * Stop-loss: market sell of all base at the bid (or a trade at/below the stop) once price <= stop; the grid is then
    stopped for good. Equity is marked at the bid (liquidation value).
  * GRID PROFIT = sum over completed buy/sell pairs of q*(upper-lower) minus both fees. FLOAT PROFIT = equity - invest
    - grid profit (the base inventory marked against its cost, plus the initial-buy and unmatched-fill frictions).
Storage: var/shadow_grid.db, append-only (UPDATE/DELETE blocked by triggers): `grids` (frozen params), `events` (start,
every fill, gap, stop) and `snaps` (full state, written on every event and every minute; the latest row restores the
grid after a restart).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from pathlib import Path

from ..swing.grid import FEE, MIN_GRID_USDT, levels

log = logging.getLogger("shadow_grid")

POLL_S = 5.0
SNAP_S = 60.0
STOP_FACTOR = 0.97


@dataclass(frozen=True)
class Config:
    id: str
    symbol: str
    band: float
    rows: int
    invest: float = 1000.0
    grid_type: str = "geometric"


CONFIGS = [
    Config("BTC_narrow_v1", "BTC_USDT", 0.04, 20),
    Config("BTC_medium_v1", "BTC_USDT", 0.08, 40),
    Config("BTC_wide_v1", "BTC_USDT", 0.16, 80),
    Config("ETH_medium_v1", "ETH_USDT", 0.08, 40),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS grids(id TEXT PRIMARY KEY, symbol TEXT, params TEXT, created_ts INTEGER, start_price REAL);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, grid_id TEXT, kind TEXT, side TEXT,
  level INTEGER, price REAL, qty REAL, fee REAL, grid_profit REAL, note TEXT);
CREATE TABLE IF NOT EXISTS snaps(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, grid_id TEXT, price REAL, equity REAL,
  grid_profit REAL, float_profit REAL, b INTEGER, cash REAL, base REAL, fills INTEGER, trips INTEGER, status TEXT,
  cursor_ts INTEGER, cursor_ids TEXT);
CREATE INDEX IF NOT EXISTS snaps_grid ON snaps(grid_id, id);
CREATE INDEX IF NOT EXISTS events_grid ON events(grid_id, id);
"""
for _t in ("grids", "events", "snaps"):
    SCHEMA += (f"CREATE TRIGGER IF NOT EXISTS {_t}_no_upd BEFORE UPDATE ON {_t} BEGIN SELECT RAISE(ABORT,'append-only'); END;"
               f"CREATE TRIGGER IF NOT EXISTS {_t}_no_del BEFORE DELETE ON {_t} BEGIN SELECT RAISE(ABORT,'append-only'); END;")


def open_db(path) -> sqlite3.Connection:
    db = sqlite3.connect(str(path), timeout=30)
    db.executescript(SCHEMA)
    return db


class ShadowGrid:
    """One grid. `on_price` / `stop` mutate state and return the events to be stored."""

    def __init__(self, cfg: Config, bottom, top, q, b, cash, base, gp=0.0, fills=0, trips=0, status="running",
                 last_px=None):
        self.cfg, self.bottom, self.top, self.q = cfg, bottom, top, q
        self.lv = levels(bottom, top, cfg.rows, cfg.grid_type)
        self.stop_price = bottom * STOP_FACTOR
        self.b, self.cash, self.base, self.gp = b, cash, base, gp
        self.fills, self.trips, self.status, self.last_px = fills, trips, status, last_px

    @classmethod
    def start(cls, cfg: Config, ask: float, ts: int):
        if cfg.invest / cfg.rows < MIN_GRID_USDT:
            raise ValueError(f"{cfg.id}: below the {MIN_GRID_USDT} USDT minimum per grid")
        bottom, top = ask * (1 - cfg.band), ask * (1 + cfg.band)
        lv = levels(bottom, top, cfg.rows, cfg.grid_type)
        b = min(cfg.rows, bisect_left(lv, ask))
        n_base = cfg.rows - b
        need = n_base * ask * (1 + FEE) + sum(lv[i] * (1 + FEE) for i in range(b))
        q = cfg.invest / need
        g = cls(cfg, bottom, top, q, b, cfg.invest - q * n_base * ask * (1 + FEE), q * n_base, last_px=ask)
        ev = [{"ts": ts, "kind": "start", "side": "BUY", "level": None, "price": ask, "qty": q * n_base,
               "fee": q * n_base * ask * FEE, "grid_profit": 0.0,
               "note": json.dumps({"bottom": bottom, "top": top, "q": q, "rows": cfg.rows})}]
        return g, ev

    def equity(self, px):
        return self.cash + self.base * px

    def _fill(self, ts, side, i, price, note=""):
        fee = self.q * price * FEE
        self.fills += 1
        if side == "BUY":
            self.cash -= self.q * price + fee
            self.base += self.q
        else:
            self.cash += self.q * price - fee
            self.base -= self.q
            self.trips += 1
            self.gp += self.q * (self.lv[i + 1] - self.lv[i]) - self.q * self.lv[i + 1] * FEE - self.q * self.lv[i] * FEE
        return {"ts": ts, "kind": "fill", "side": side, "level": i, "price": price, "qty": self.q, "fee": fee,
                "grid_profit": self.gp, "note": note}

    def on_price(self, px, ts, note=""):
        if self.status != "running":
            return []
        out = []
        x = self.last_px if self.last_px is not None else px
        if px < x:
            lo = bisect_right(self.lv, px)                       # levels strictly above px
            for i in range(min(self.b, self.cfg.rows) - 1, lo - 1, -1):    # nearest level first, as the price falls
                out.append(self._fill(ts, "BUY", i, self.lv[i], note))
            self.b = min(self.b, lo)
        elif px > x:
            nb = min(self.cfg.rows, max(self.b, bisect_left(self.lv, px) - 1))   # sells at lv[i+1] < px
            for i in range(self.b, nb):
                out.append(self._fill(ts, "SELL", i, self.lv[i + 1], note))
            self.b = nb
        self.last_px = px
        if px <= self.stop_price:
            out += self.stop(px, ts, "stop_loss")
        return out

    def stop(self, px, ts, why):
        if self.status != "running":
            return []
        fee = self.base * px * FEE
        base = self.base
        self.cash += base * px - fee
        self.base = 0.0
        self.status = "stopped"
        return [{"ts": ts, "kind": "stop", "side": "SELL", "level": None, "price": px, "qty": base, "fee": fee,
                 "grid_profit": self.gp, "note": why}]

    def snapshot(self, mark_px):
        eq = self.equity(mark_px)
        return {"price": mark_px, "equity": eq, "grid_profit": self.gp,
                "float_profit": eq - self.cfg.invest - self.gp, "b": self.b, "cash": self.cash, "base": self.base,
                "fills": self.fills, "trips": self.trips, "status": self.status}


class Store:
    def __init__(self, path):
        self.db = open_db(path)

    def add_grid(self, g: ShadowGrid, ts, events):
        params = {"symbol": g.cfg.symbol, "band": g.cfg.band, "rows": g.cfg.rows, "invest": g.cfg.invest,
                  "type": g.cfg.grid_type, "bottom": g.bottom, "top": g.top, "q": g.q, "stop": g.stop_price}
        with self.db:
            self.db.execute("INSERT INTO grids VALUES(?,?,?,?,?)",
                            (g.cfg.id, g.cfg.symbol, json.dumps(params), ts, g.last_px))
            self._events(g.cfg.id, events)

    def _events(self, gid, events):
        self.db.executemany(
            "INSERT INTO events(ts,grid_id,kind,side,level,price,qty,fee,grid_profit,note) VALUES(?,?,?,?,?,?,?,?,?,?)",
            [(e["ts"], gid, e["kind"], e["side"], e["level"], e["price"], e["qty"], e["fee"], e["grid_profit"],
              e["note"]) for e in events])

    def write(self, g: ShadowGrid, ts, mark_px, events, cursor_ts, cursor_ids):
        s = g.snapshot(mark_px)
        with self.db:
            self._events(g.cfg.id, events)
            self.db.execute(
                "INSERT INTO snaps(ts,grid_id,price,equity,grid_profit,float_profit,b,cash,base,fills,trips,status,"
                "cursor_ts,cursor_ids) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ts, g.cfg.id, s["price"], s["equity"], s["grid_profit"], s["float_profit"], s["b"], s["cash"],
                 s["base"], s["fills"], s["trips"], s["status"], cursor_ts, json.dumps(sorted(cursor_ids))))

    def load(self, cfg: Config):
        """Returns (grid, cursor_ts, cursor_ids) or None if this config was never started."""
        row = self.db.execute("SELECT params FROM grids WHERE id=?", (cfg.id,)).fetchone()
        if row is None:
            return None
        p = json.loads(row[0])
        snap = self.db.execute("SELECT b,cash,base,grid_profit,fills,trips,status,cursor_ts,cursor_ids,price FROM snaps "
                               "WHERE grid_id=? ORDER BY id DESC LIMIT 1", (cfg.id,)).fetchone()
        if snap is None:
            return None
        b, cash, base, gp, fills, trips, status, cts, cids, px = snap
        g = ShadowGrid(cfg, p["bottom"], p["top"], p["q"], b, cash, base, gp, fills, trips, status, last_px=px)
        return g, cts, set(json.loads(cids))


class Runner:
    """Owns the grids of all configs; `poll` is one network cycle (also driven directly by tests)."""

    def __init__(self, client, store: Store, configs=CONFIGS, clock=time.time):
        self.client, self.store, self.clock = client, store, clock
        self.grids: dict[str, ShadowGrid] = {}
        self.cursor: dict[str, tuple[int, set]] = {}        # symbol -> (last trade ts, ids at that ts)
        self.last_snap: dict[str, float] = {}
        self.configs = list(configs)

    def _now_ms(self):
        return int(self.clock() * 1000)

    def init(self):
        """Idempotent: restores stored grids and starts the ones never started (retried until all exist)."""
        for cfg in self.configs:
            if cfg.id in self.grids:
                continue
            loaded = self.store.load(cfg)
            if loaded:
                g, cts, cids = loaded
                self.grids[cfg.id] = g
                prev = self.cursor.get(cfg.symbol)
                if prev is None or cts > prev[0]:
                    self.cursor[cfg.symbol] = (cts, cids)
                log.info("restored %s (%s, %d fills)", cfg.id, g.status, g.fills)
                continue
            bt, _ = self.client.book_ticker(cfg.symbol)
            ts = self._now_ms()
            g, ev = ShadowGrid.start(cfg, float(bt.ask), ts)
            if cfg.symbol not in self.cursor:
                trades, _ = self.client.trades(cfg.symbol, 100)
                last = max((t.ts for t in trades), default=ts)
                self.cursor[cfg.symbol] = (last, {t.trade_id for t in trades if t.ts == last})
            cts, cids = self.cursor[cfg.symbol]
            self.store.add_grid(g, ts, ev)
            self.store.write(g, ts, float(bt.bid), [], cts, cids)
            self.grids[cfg.id] = g
            self.last_snap[cfg.id] = self.clock()
            log.info("started %s at ask %.2f (bottom %.2f top %.2f)", cfg.id, float(bt.ask), g.bottom, g.top)

    def poll(self):
        now = self.clock()
        for symbol in sorted({c.symbol for c in self.configs}):
            gs = [g for g in self.grids.values() if g.cfg.symbol == symbol]
            if not any(g.status == "running" for g in gs):
                continue
            cts, cids = self.cursor.get(symbol, (0, set()))
            trades, _ = self.client.trades(symbol, 100)
            new = sorted((t for t in trades if t.ts > cts or (t.ts == cts and t.trade_id not in cids)),
                         key=lambda t: (t.ts, t.trade_id))
            gap = len(trades) >= 100 and cts > 0 and min(t.ts for t in trades) > cts
            bt, _ = self.client.book_ticker(symbol)
            bid = float(bt.bid)
            events = {g.cfg.id: [] for g in gs}
            if gap:
                for g in gs:
                    if g.status == "running":
                        events[g.cfg.id].append({"ts": self._now_ms(), "kind": "gap", "side": None, "level": None,
                                                 "price": float(new[0].price), "qty": 0.0, "fee": 0.0,
                                                 "grid_profit": g.gp, "note": "trades feed gap: price bridged"})
            for k, t in enumerate(new):
                for g in gs:
                    events[g.cfg.id] += g.on_price(float(t.price), t.ts, "bridged" if gap and k == 0 else "")
            if new:
                last = new[-1].ts
                cids = {t.trade_id for t in new if t.ts == last} | (cids if last == cts else set())
                cts = last
                self.cursor[symbol] = (cts, cids)
            for g in gs:
                if g.status == "running" and bid <= g.stop_price:
                    events[g.cfg.id] += g.stop(bid, self._now_ms(), "stop_loss")
                ev = events[g.cfg.id]
                if ev or now - self.last_snap.get(g.cfg.id, 0) >= SNAP_S:
                    self.store.write(g, self._now_ms(), bid, ev, cts, cids)
                    self.last_snap[g.cfg.id] = now


def run(paths, stop, once=False, client=None, poll_s=POLL_S):
    from ..exchange.pionex_public import ExchangeError, PionexPublic
    paths.ensure()
    runner = Runner(client or PionexPublic(), Store(paths.root / "shadow_grid.db"))
    backoff = poll_s
    while not stop.is_set():
        try:
            if len(runner.grids) < len(runner.configs):
                runner.init()
            runner.poll()
            backoff = poll_s
        except ExchangeError as exc:                       # includes rate limits and network errors
            backoff = min(backoff * 2, 120.0)
            log.warning("poll failed (%s); retry in %.0f s", exc, backoff)
        except Exception:                                   # keep the service alive; the watchdog sees the log
            log.exception("unexpected error")
            backoff = min(backoff * 2, 120.0)
        if once:
            return 0
        stop.wait(backoff)
    return 0


# ---------------------------------------------------------------- report

def report(paths, now_ms=None) -> dict:
    """Latest state of each shadow grid (24 h deltas) next to the owner's real bots from var/account.db."""
    now_ms = now_ms or int(time.time() * 1000)
    db = open_db(Path(paths.root) / "shadow_grid.db")
    out = {"label": "PAPER on live Pionex quotes, public data, no orders. Not profit.", "at_ms": now_ms,
           "shadow": [], "real_bots": []}
    for gid, sym, params, created in db.execute("SELECT id,symbol,params,created_ts FROM grids ORDER BY created_ts,id").fetchall():
        s = db.execute("SELECT ts,price,equity,grid_profit,float_profit,fills,trips,status FROM snaps WHERE grid_id=? "
                       "ORDER BY id DESC LIMIT 1", (gid,)).fetchone()
        if s is None:
            continue
        p = json.loads(params)
        old = db.execute("SELECT equity,grid_profit,fills FROM snaps WHERE grid_id=? AND ts<=? ORDER BY id DESC LIMIT 1",
                         (gid, now_ms - 86_400_000)).fetchone()
        out["shadow"].append({
            "id": gid, "symbol": sym, "range": f"{p['bottom']:.2f}-{p['top']:.2f}", "rows": p["rows"],
            "since": created, "last_ts": s[0], "price": s[1], "equity": s[2], "invest": p["invest"],
            "return_pct": (s[2] / p["invest"] - 1) * 100, "grid_profit": s[3], "float_profit": s[4], "fills": s[5],
            "round_trips": s[6], "status": s[7],
            "d_equity_24h": None if old is None else s[2] - old[0],
            "d_grid_profit_24h": None if old is None else s[3] - old[1],
            "fills_24h": s[5] if old is None else s[5] - old[2]})
    db.close()
    acc = Path(paths.root) / "account.db"
    if acc.exists():
        a = sqlite3.connect(f"file:{acc.as_posix()}?mode=ro", uri=True)
        try:
            for r in a.execute("SELECT type,pair,range,grids,investment,grid_profit,float_profit,status FROM bots "
                               "WHERE id IN (SELECT MAX(id) FROM bots GROUP BY bu_order_id) AND status='running' "
                               "ORDER BY at DESC"):
                out["real_bots"].append(dict(zip(("type", "pair", "range", "grids", "investment", "grid_profit",
                                                  "float_profit", "status"), r)))
        except sqlite3.Error as exc:
            out["real_bots_error"] = str(exc)
        finally:
            a.close()
    return out


def render(rep: dict) -> str:
    lines = [f"Shadow SPOT grids ({rep['label']})", "",
             "| grid | range | equity | return | grid profit | float | fills (24h) | status |",
             "|---|---|---|---|---|---|---|---|"]
    for g in rep["shadow"]:
        lines.append(f"| {g['id']} | {g['range']} | {g['equity']:.2f} | {g['return_pct']:+.2f}% | {g['grid_profit']:+.2f} | "
                     f"{g['float_profit']:+.2f} | {g['fills']} ({g['fills_24h']}) | {g['status']} |")
    lines += ["", "Owner's real running bots (account.db, read-only):"]
    for b in rep["real_bots"]:
        lines.append(f"- {b['type']} {b['pair']} {b['range']} x{b['grids']}, invested {b['investment']}, "
                     f"grid profit {b['grid_profit']}, float {b['float_profit']}")
    if not rep["real_bots"]:
        lines.append("- none running")
    return "\n".join(lines)
