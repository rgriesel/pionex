"""Forward SHADOW runner for the CTA v1.1 books and Donchian C1 on live Pionex quotes (CLO-31/CLO-32).
PAPER ONLY: public endpoints, no keys, no orders, no order path. A paper result on live quotes is not profit.

PRE-REGISTERED 2026-10-17 (SAST, machine clock), before the first start. Frozen; a changed idea is a new book id.
Books (id, rules, coins, paper USDT):
    defensive    CTA v1.1, tsmom_vote + vol sizing (swing_book.targets "vol")        10 coins   1000
    growth       same signals, 1/N sizing per IN coin (comparison book)              10 coins   1000
    canary       v1.1 vol sizing on BTC+ETH only, 10 USDT minimum buy enforced       2 coins     100
    donchian_c1  Donchian ensemble C1 (swing/donchian.py: share of long channels x v1.1 vol sizing)  10 coins  1000
                 shown everywhere as "PASS - Red Team pending, not a candidate".
Not included: EMA50 filter (inside CTA), C2 point-in-time universe, WL diamonds, every FAIL in docs/STRATEGY_LOG.md.

Rules of evaluation (these are the tested rules, nothing is re-tuned):
  * Signals use ONLY completed Pionex 1D klines (open_time + 1 day <= decision time); the unfinished bar of the current
    UTC day is never read. Decision day D (00:00 UTC) is taken from DECISION_DELAY_S after the close, once every coin's
    bar D-1 is available; if a coin's bar is missing the decision waits (retried every poll, nothing written).
    History: Pionex klines (limit 500); days before a coin's first Pionex bar come from the proxy archive
    (var/proxy_market.db, Binance PROXY); the decision row records the counts per source and the gaps.
  * One rebalance per book per UTC day: the first quote observed after the decision is the fill price. Buys fill at the
    ask, sells at the bid, fee 0.05% per side on the notional, no extra slippage. The 2% band, the 100% gross cap and
    the 10 USDT minimum buy come from cta.rebalance (equity capped at the book's USDT); Pionex precision and minimum
    sell size come from /common/symbols. Weights are of the book's equity, marked at the bid (liquidation value).
  * The first rebalance of a book happens on the day it is created, at the first quote after the decision (flagged
    `late_s`: the fill is not at the 00:00 UTC open). Same for any day the process was down at 00:00.
  * Idempotent: UNIQUE(book, day) on decisions; decision, quotes, fills and the post-trade equity row are one
    transaction, so a restart can neither double-trade nor half-trade a day.
  * Quotes are polled every POLL_S (5 s); marks are stored every SNAP_S (5 min) and at every rebalance.
Storage: var/forward_shadow.db, append-only (UPDATE/DELETE blocked by triggers): books, decisions, quotes, fills,
equity, recon. The existing paper books (var/swing_book/state*.json) are only READ for the daily reconciliation, which
compares the target weights of the two systems and flags a coin set mismatch or a weight difference above 1 point.
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

from ..swing import swing_book
from ..swing.cta import DAY, MIN_BUY_USDT, UNIVERSE, rebalance
from ..swing.donchian import share_long

log = logging.getLogger("forward_shadow")

POLL_S = 5.0
SNAP_S = 300.0
DECISION_DELAY_S = 60
FEE = 0.0005
BAND = swing_book.BAND
DIVERGE = 0.01
C1_LABEL = "PASS - Red Team pending, not a candidate"
LABEL = "PAPER on live Pionex quotes, public data, no orders. Not profit."


@dataclass(frozen=True)
class Book:
    id: str
    sizing: str                       # "vol" | "equal"
    coins: tuple
    usdt: float
    name: str
    donchian: bool = False
    note: str = ""
    swing_file: str | None = None     # existing paper book to reconcile against


BOOKS = [
    Book("defensive", "vol", UNIVERSE, 1000.0, "CTA v1.1 defensive", swing_file="state.json"),
    Book("growth", "equal", UNIVERSE, 1000.0, "CTA growth (1/N)", swing_file="state_growth.json"),
    Book("canary", "vol", ("BTC_USDT", "ETH_USDT"), 100.0, "CTA canary BTC+ETH", swing_file="state_canary.json"),
    Book("donchian_c1", "vol", UNIVERSE, 1000.0, "Donchian ensemble C1", donchian=True, note=C1_LABEL),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS books(id TEXT PRIMARY KEY, params TEXT, created_ts INTEGER);
CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, book TEXT, day INTEGER,
  targets TEXT, signals TEXT, bars TEXT, late_s REAL, skipped TEXT, UNIQUE(book, day));
CREATE TABLE IF NOT EXISTS quotes(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, book TEXT, day INTEGER, symbol TEXT,
  bid REAL, ask REAL, purpose TEXT);
CREATE TABLE IF NOT EXISTS fills(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, book TEXT, day INTEGER, symbol TEXT,
  side TEXT, qty REAL, price REAL, fee REAL, notional REAL);
CREATE TABLE IF NOT EXISTS equity(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, book TEXT, kind TEXT, equity REAL,
  cash REAL, holdings TEXT);
CREATE TABLE IF NOT EXISTS recon(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, book TEXT, day INTEGER, status TEXT,
  max_diff REAL, detail TEXT, UNIQUE(book, day));
CREATE INDEX IF NOT EXISTS equity_book ON equity(book, id);
"""
for _t in ("books", "decisions", "quotes", "fills", "equity", "recon"):
    SCHEMA += (f"CREATE TRIGGER IF NOT EXISTS {_t}_no_upd BEFORE UPDATE ON {_t} BEGIN SELECT RAISE(ABORT,'append-only'); END;"
               f"CREATE TRIGGER IF NOT EXISTS {_t}_no_del BEFORE DELETE ON {_t} BEGIN SELECT RAISE(ABORT,'append-only'); END;")


def open_db(path) -> sqlite3.Connection:
    db = sqlite3.connect(str(path), timeout=30)
    db.executescript(SCHEMA)
    return db


# ---------------------------------------------------------------- signals

def targets_for(book: Book, series: dict) -> dict:
    """series: {sym: [(open_time, open, close)]} of CLOSED days only. Returns {"weights", "info", "available"}."""
    t = swing_book.targets(series, book.sizing)
    if not book.donchian:
        return t
    n, info, w = t["available"], t["info"], {}
    for s in info:
        dc = share_long([r[2] for r in series[s]])[-1]
        info[s]["dc"] = dc
        if dc > 0 and info[s]["vol"] > 0 and n:
            w[s] = (swing_book.TARGET / n) / info[s]["vol"] * dc
    gross = sum(w.values())
    if gross > 1:
        w = {s: v / gross for s, v in w.items()}
    t["weights"] = w
    return t


def build_series(client, symbol, decision_ms, seed=None):
    """Closed daily rows [(open_time, open, close)] oldest first plus a source summary. Pionex wins; the proxy fills
    only the days before the first Pionex bar."""
    kl, _ = client.klines(symbol, "1D", limit=500)
    px = sorted(((k.open_time, float(k.open), float(k.close)) for k in kl if k.open_time + DAY <= decision_ms))
    first = px[0][0] if px else None
    old = []
    if seed is not None:
        old = [r for r in seed(symbol) if r[0] + DAY <= decision_ms and (first is None or r[0] < first)]
    rows = sorted(old) + px
    gaps = sum(1 for a, b in zip(rows, rows[1:]) if b[0] - a[0] != DAY)
    meta = {"pionex": len(px), "proxy": len(old), "gaps": gaps,
            "last_bar": _day(rows[-1][0]) if rows else None, "first_pionex": _day(first) if first else None}
    return rows, meta


def _day(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).date().isoformat()


def proxy_seed(paths):
    """Seed function over var/proxy_market.db (Binance daily bars, PROXY), or None when the archive is absent."""
    if not Path(paths.proxy_market).exists():
        return None
    from ..data.store import MarketView
    view = MarketView(paths.proxy_market)

    def seed(symbol):
        d = view.bars(symbol, "1D")
        return list(zip(d.t, d.o, d.c))
    return seed


# ---------------------------------------------------------------- execution

def floor_to(x: float, precision: int) -> float:
    q = Decimal(1).scaleb(-precision)
    return float(Decimal(repr(x)).quantize(q, rounding=ROUND_DOWN))


def execute(cash, holdings, tgt, quotes, rules, capital):
    """One rebalance at the given quotes. quotes {sym: (bid, ask)}; rules {sym: SymbolRules or None}.
    Returns (new cash, new holdings, fills, skipped notes). Sells first at the bid, then buys at the ask."""
    equity = cash + sum(q * quotes[s][0] for s, q in holdings.items())
    w = {s: q * quotes[s][0] / equity for s, q in holdings.items() if q > 0}
    new, _paid, _traded = rebalance(w, tgt, set(quotes), BAND, min(equity, capital), cost={})
    fills, skipped, buys = [], [], []
    holdings = dict(holdings)
    for s in sorted(set(new) | set(w)):
        a, b = w.get(s, 0.0), new.get(s, 0.0)
        if abs(b - a) < 1e-9:
            continue
        bid, ask = quotes[s]
        r = rules.get(s)
        prec = r.base_precision if r else 8
        if b < a:                                                      # sell at the bid
            held = holdings.get(s, 0.0)
            qty = held if b <= 1e-12 else held - b * equity / bid
            qty = floor_to(min(qty, held), prec)
            floor = float(r.min_dump_size) if r and r.min_dump_size else 0.0
            if qty <= 0 or qty < floor:
                skipped.append(f"{s} sell {qty} below minimum {floor}")
                continue
            fee = qty * bid * FEE
            cash += qty * bid - fee
            holdings[s] = held - qty
            fills.append({"symbol": s, "side": "SELL", "qty": qty, "price": bid, "fee": fee, "notional": qty * bid})
        else:
            buys.append((s, (b - a) * equity, ask, prec, r))
    budget = sum(v for _s, v, *_ in buys)
    scale = min(1.0, cash / budget) if budget > 0 else 1.0
    for s, value, ask, prec, r in buys:
        qty = floor_to(value * scale / (ask * (1 + FEE)), prec)
        floor = float(r.min_amount) if r and r.min_amount else MIN_BUY_USDT
        if qty <= 0 or qty * ask < floor:
            skipped.append(f"{s} buy {qty * ask:.2f} USDT below minimum {floor}")
            continue
        fee = qty * ask * FEE
        cash -= qty * ask + fee
        holdings[s] = holdings.get(s, 0.0) + qty
        fills.append({"symbol": s, "side": "BUY", "qty": qty, "price": ask, "fee": fee, "notional": qty * ask})
    holdings = {s: q for s, q in holdings.items() if q > 0}
    return cash, holdings, fills, skipped


# ---------------------------------------------------------------- store

class Store:
    def __init__(self, path):
        self.db = open_db(path)

    def has_decision(self, book, day):
        return self.db.execute("SELECT 1 FROM decisions WHERE book=? AND day=?", (book, day)).fetchone() is not None

    def started(self, book: Book):
        return self.db.execute("SELECT 1 FROM equity WHERE book=?", (book.id,)).fetchone() is not None

    def state(self, book: Book):
        r = self.db.execute("SELECT cash,holdings FROM equity WHERE book=? ORDER BY id DESC LIMIT 1", (book.id,)).fetchone()
        return (book.usdt, {}) if r is None else (r[0], json.loads(r[1]))

    def add_equity(self, ts, book, kind, equity, cash, holdings):
        self.db.execute("INSERT INTO equity(ts,book,kind,equity,cash,holdings) VALUES(?,?,?,?,?,?)",
                        (ts, book, kind, equity, cash, json.dumps(holdings)))

    def commit_day(self, book: Book, day, ts, dec, quotes, fills, cash, holdings, equity):
        """Decision + quotes + fills + post-trade equity in ONE transaction (UNIQUE(book, day) makes it idempotent)."""
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO books VALUES(?,?,?)",
                            (book.id, json.dumps({"name": book.name, "sizing": book.sizing, "coins": list(book.coins),
                                                  "usdt": book.usdt, "donchian": book.donchian, "label": book.note}), ts))
            self.db.execute("INSERT INTO decisions(ts,book,day,targets,signals,bars,late_s,skipped) VALUES(?,?,?,?,?,?,?,?)",
                            (dec["ts"], book.id, day, json.dumps(dec["targets"]), json.dumps(dec["signals"]),
                             json.dumps(dec["bars"]), dec["late_s"], json.dumps(dec["skipped"])))
            self.db.executemany("INSERT INTO quotes(ts,book,day,symbol,bid,ask,purpose) VALUES(?,?,?,?,?,?,'fill')",
                                [(ts, book.id, day, s, b, a) for s, (b, a) in quotes.items()])
            self.db.executemany("INSERT INTO fills(ts,book,day,symbol,side,qty,price,fee,notional) VALUES(?,?,?,?,?,?,?,?,?)",
                                [(ts, book.id, day, f["symbol"], f["side"], f["qty"], f["price"], f["fee"], f["notional"])
                                 for f in fills])
            self.add_equity(ts, book.id, "rebalance", equity, cash, holdings)

    def add_recon(self, ts, book, day, status, max_diff, detail):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO recon(ts,book,day,status,max_diff,detail) VALUES(?,?,?,?,?,?)",
                            (ts, book, day, status, max_diff, json.dumps(detail)))


def reconcile(book: Book, day_ms, tgt, swing_dir):
    """Compare our target weights with the existing paper book's next_targets. -> (status, max_diff, detail) or None
    while the paper book has not updated since the day began (cannot be compared yet)."""
    if not book.swing_file:
        return "n/a", 0.0, {"note": "no existing paper book for this strategy"}
    p = Path(swing_dir) / book.swing_file
    if not p.exists():
        return None
    st = json.loads(p.read_text(encoding="utf-8"))
    try:
        upd = datetime.fromisoformat(st["updated"]).timestamp() * 1000
    except (KeyError, ValueError):
        return None
    if upd < day_ms + DECISION_DELAY_S * 1000:
        return None
    theirs = {s: float(v) for s, v in st.get("next_targets", {}).items()}
    diffs = {s: abs(tgt.get(s, 0.0) - theirs.get(s, 0.0)) for s in set(tgt) | set(theirs)}
    mx = max(diffs.values(), default=0.0)
    only = sorted(set(tgt) ^ set(theirs))
    ok = mx <= DIVERGE and not only
    return ("ok" if ok else "DIVERGED"), mx, {"only_in_one": only, "diffs": {s: round(v, 4) for s, v in diffs.items() if v > 1e-4}}


# ---------------------------------------------------------------- runner

class Runner:
    """`poll` is one network cycle (also driven directly by tests)."""

    def __init__(self, client, store: Store, books=BOOKS, clock=time.time, seed=None, swing_dir=None):
        self.client, self.store, self.clock, self.seed = client, store, clock, seed
        self.books, self.swing_dir = list(books), swing_dir
        self.quotes: dict[str, tuple] = {}
        self.last_snap = 0.0
        self.last_recon = 0.0
        self._rules: dict = {}
        self._rules_day = None

    def _now_ms(self):
        return int(self.clock() * 1000)

    def fetch_quotes(self, symbols):
        out = {}
        for s in sorted(symbols):
            bt, _ = self.client.book_ticker(s)
            out[s] = (float(bt.bid), float(bt.ask))
        return out

    def symbol_rules(self, symbols, day):
        if self._rules_day != day:
            self._rules, self._rules_day = {}, day
        need = [s for s in symbols if s not in self._rules]
        if need:
            try:
                for r in self.client.symbols(need)[0]:
                    self._rules[r.symbol] = r
            except Exception as exc:                                  # fall back to defaults, noted in the log only
                log.warning("symbol rules unavailable (%s): default precision/minimums", exc)
        return {s: self._rules.get(s) for s in symbols}

    def rebalance_book(self, book: Book, day):
        decision_ms = self._now_ms()
        series, bars = {}, {}
        for s in book.coins:
            rows, meta = build_series(self.client, s, decision_ms, self.seed)
            if not rows or rows[-1][0] != day - DAY:
                log.info("%s: bar %s missing for %s; waiting", book.id, _day(day - DAY), s)
                return False
            series[s], bars[s] = rows, meta
        t = targets_for(book, series)
        # first quote observed AFTER the decision (fetched after decision_ms, then stored with its own time)
        quotes = self.fetch_quotes(book.coins)
        ts = self._now_ms()
        self.quotes.update(quotes)
        rules = self.symbol_rules(list(book.coins), day)
        cash, holdings = self.store.state(book)
        cash, holdings, fills, skipped = execute(cash, holdings, t["weights"], quotes, rules, book.usdt)
        equity = cash + sum(q * quotes[s][0] for s, q in holdings.items())
        dec = {"ts": decision_ms, "targets": {s: round(v, 6) for s, v in t["weights"].items()},
               "signals": t["info"], "bars": bars, "late_s": max(0.0, (decision_ms - day) / 1000.0), "skipped": skipped}
        self.store.commit_day(book, day, ts, dec, quotes, fills, cash, holdings, equity)
        log.info("%s %s: %d fills, equity %.2f", book.id, _day(day), len(fills), equity)
        return True

    def poll(self):
        now = self.clock()
        now_ms = int(now * 1000)
        symbols = {s for b in self.books for s in b.coins}
        self.quotes = self.fetch_quotes(symbols)
        day = now_ms // DAY * DAY
        if now_ms - day >= DECISION_DELAY_S * 1000:
            for b in self.books:
                if not self.store.has_decision(b.id, day):
                    self.rebalance_book(b, day)
        if now - self.last_snap >= SNAP_S:
            for b in self.books:
                if not self.store.started(b):
                    continue
                cash, holdings = self.store.state(b)
                if any(s not in self.quotes for s in holdings):
                    continue
                eq = cash + sum(q * self.quotes[s][0] for s, q in holdings.items())
                with self.store.db:
                    self.store.add_equity(now_ms, b.id, "mark", eq, cash, holdings)
            self.last_snap = now
        if self.swing_dir and now - self.last_recon >= 60:
            self.last_recon = now
            self.reconcile_pending(day)

    def reconcile_pending(self, day):
        for b in self.books:
            if self.store.db.execute("SELECT 1 FROM recon WHERE book=? AND day=?", (b.id, day)).fetchone():
                continue
            r = self.store.db.execute("SELECT targets FROM decisions WHERE book=? AND day=?", (b.id, day)).fetchone()
            if r is None:
                continue
            res = reconcile(b, day, json.loads(r[0]), self.swing_dir)
            if res is not None:
                self.store.add_recon(self._now_ms(), b.id, day, *res)
                if res[0] == "DIVERGED":
                    log.warning("%s: targets diverge from the existing paper book (max %.4f)", b.id, res[1])


def run(paths, stop, once=False, client=None, poll_s=POLL_S):
    from ..exchange.pionex_public import ExchangeError, PionexPublic
    paths.ensure()
    runner = Runner(client or PionexPublic(), Store(paths.root / "forward_shadow.db"), seed=proxy_seed(paths),
                    swing_dir=paths.root / "swing_book")
    backoff = poll_s
    while not stop.is_set():
        try:
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
    now_ms = now_ms or int(time.time() * 1000)
    db = open_db(Path(paths.root) / "forward_shadow.db")
    day0 = now_ms // DAY * DAY
    out = {"label": LABEL, "at_ms": now_ms, "books": []}
    for bid, params, created in db.execute("SELECT id,params,created_ts FROM books ORDER BY created_ts,id").fetchall():
        p = json.loads(params)
        e = db.execute("SELECT ts,equity,cash,holdings FROM equity WHERE book=? ORDER BY id DESC LIMIT 1", (bid,)).fetchone()
        if e is None:
            continue
        prev = db.execute("SELECT equity FROM equity WHERE book=? AND ts<? ORDER BY id DESC LIMIT 1", (bid, day0)).fetchone()
        base = prev[0] if prev else p["usdt"]
        hold = json.loads(e[3])
        rec = db.execute("SELECT day,status,max_diff FROM recon WHERE book=? ORDER BY day DESC LIMIT 1", (bid,)).fetchone()
        dec = db.execute("SELECT day,late_s,skipped FROM decisions WHERE book=? ORDER BY day DESC LIMIT 1", (bid,)).fetchone()
        out["books"].append({
            "id": bid, "name": p["name"], "label": p["label"], "since": created, "last_ts": e[0], "equity": e[1],
            "cash": e[2], "invest": p["usdt"], "day_pct": (e[1] / base - 1) * 100, "since_pct": (e[1] / p["usdt"] - 1) * 100,
            "positions": sorted(s.replace("_USDT", "") for s in hold), "last_decision_day": dec[0] if dec else None,
            "late_s": dec[1] if dec else None, "skipped": json.loads(dec[2]) if dec else [],
            "recon": None if rec is None else {"day": _day(rec[0]), "status": rec[1], "max_diff": rec[2]}})
    db.close()
    return out


def render(rep: dict) -> str:
    lines = [f"Forward shadow books ({rep['label']})", ""]
    for b in rep["books"]:
        tag = f" [{b['label']}]" if b["label"] else ""
        rc = " | recon pending (paper book not updated yet)" if not b["recon"] else f" | recon {b['recon']['status']} ({b['recon']['day']}, max diff {b['recon']['max_diff']:.3f})"
        lines.append(f"{b['id']} - {b['name']}{tag}: equity {b['equity']:.2f} USDT | day {b['day_pct']:+.2f}% | "
                     f"since start {b['since_pct']:+.2f}% | open {len(b['positions'])} "
                     f"({', '.join(b['positions']) or 'cash'}){rc} | paper only")
    if not rep["books"]:
        lines.append("no book started yet")
    return "\n".join(lines)
