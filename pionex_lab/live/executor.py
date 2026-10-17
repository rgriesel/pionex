"""Capped live executor (CLO-43 part B). The ONLY order path in the repo; dormant until the owner arms it.

What it can do: create / cancel SPOT grid bots and place SPOT orders, for strategies the proof gate
(live/gate.py) computes as ELIGIBLE, through signed Pionex endpoints (docs/PIONEX_GRID_API.md).
What it cannot do: futures (mandate spot_only), withdraw grid profit, transfer, edit the mandate or lock,
raise any limit, or run any endpoint outside ALLOWED_ENDPOINTS.

Every action passes `_vet()` in this order; the first failing rule refuses it (journalled, notified):
  1 kill switch: var/LIVE_STOP exists, or a halt latch (daily loss / absolute loss) is set
  2 mandate loads and hash-matches config/mandate.lock.json; live_enabled is true; mode == "LIVE";
    the owner-written var/live.json "approved_mandate_sha256" equals its hash (a mandate cannot contain its own hash)
  3 strategy is ELIGIBLE per the gate computed now from the databases (cancel of an own bot is risk-reducing
    and exempt from this rule only), and is in the owner's optional var/live.json "strategy_allowlist"
  4 symbol is in mandate execution.allowed_symbols (empty list = nothing may trade)
  5 caps, all from the mandate: capital = min(initial_capital, 100 USDT hard cap); per-position size =
    capital x position_notional_fraction (canary fraction while authority.canary_required); open exposure <=
    capital x gross_exposure_fraction; open bots <= max_positions; leverage <= risk.leverage; futures refused
Red Team fixes (CLO-43): every spot order is valued at the live Pionex bid/ask fetched here, never a caller price;
LIMIT prices must be within LIMIT_BAND of the touch; a SELL may not exceed the base quantity this executor's own
journalled buys hold; var/live.json strategy_allowlist is mandatory; a create is refused while a running "cw:" bot
the journal does not know exists; any ambiguous response (timeout, 5xx, unparseable, no id) journals UNKNOWN and
latches a permanent halt until the owner reconciles.
Red Team round 2 (CLO-43): N1 every grid close is TO_USDT (create closeSellModel and cancel; NOT_SELL is refused) so no
base coins are left outside the journal, and bots Pionex finishes itself are journalled closed by poll_pnl; N2 bot lists
follow pageToken and a journalled bot missing from the exchange list halts the day; N3 LIMIT BUYs are refused (fills are
not tracked); N4 a grid create must equal the proof-gated parameters (invest may only be lower) and book spot orders are
refused until a signal-driven planner exists (BOOK_ORDERS_ENABLED).
Loss stop: poll_pnl() computes equity P&L = bots (realized/total, plus any float loss field) + spot fills marked at
the live bid; the daily drop is measured from the day's high-water mark; cumulative loss of absolute_experiment_loss_usd
halts permanently. A failed poll halts the day (fail closed) and new actions are refused when the last poll is older
than PNL_MAX_AGE_MS. Latches live in var/live_journal.db; only the owner clears them. poll_pnl must be scheduled
(`py -m pionex_lab live-poll`) whenever the executor is armed.
Dry-run (default, no transport, no credentials read) journals what WOULD happen and why it would be refused.
Credentials are read only by `Executor.armed()` from the owner's key file and never logged or journalled.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from ..exchange.account import AccountReadError, load_credentials, sign
from ..mandate import DEFAULT_CONFIG_DIR, PolicyError, load_mandate
from . import gate

BASE_URL = "https://api.pionex.com"
LIVE_CAP_USDT = Decimal(100)           # owner policy: never more than 100 USDT of the account
MAX_ROWS = 200                         # create spec limit (checkParams says 1000; docs disagree)
ALLOWED_ENDPOINTS = {
    ("POST", "/api/v1/bot/orders/spotGrid/checkParams"),
    ("POST", "/api/v1/bot/orders/spotGrid/create"),
    ("POST", "/api/v1/bot/orders/spotGrid/cancel"),
    ("GET", "/api/v1/bot/orders/spotGrid/order"),
    ("GET", "/api/v1/bot/orders"),
    ("POST", "/api/v1/trade/order"),
}
LIMIT_BAND = Decimal("0.01")               # LIMIT price must be within 1% of the touch
PNL_MAX_AGE_MS = 30 * 60 * 1000
NOTE_PREFIX = "cw:"                    # marks bots this executor creates, so unknown ones can be detected
BOOK_ORDERS_ENABLED = False            # no signal-driven order planner for books exists, so caller-built orders are refused
MAX_PAGES = 50
ACTION_KINDS = {"grid_create", "grid_cancel", "spot_order", "futures_order"}


class Refused(RuntimeError):
    pass


class Ambiguous(Refused):
    """The request may have reached Pionex (timeout, 5xx, unparseable, no id returned): outcome unknown."""


@dataclass
class Action:
    strategy_id: str
    kind: str
    symbol: str                       # BTC_USDT
    params: dict = field(default_factory=dict)


def _d(x) -> Decimal:
    return Decimal(str(x))


def _fmt(x) -> str:
    return format(_d(x).normalize(), "f")


def load_live_config(var: Path) -> dict:
    try:
        cfg = json.loads((Path(var) / "live.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refused(f"LIVE_CONFIG_UNREADABLE: {type(exc).__name__}") from None
    if not isinstance(cfg, dict):
        raise Refused("LIVE_CONFIG_INVALID")
    return cfg


class Transport:
    """Signed requests, restricted to ALLOWED_ENDPOINTS. Holds credentials; repr and errors never show them."""

    def __init__(self, creds, base_url=BASE_URL, opener=urllib.request.urlopen):
        self._c, self._base, self._open = creds, base_url, opener

    def __repr__(self):
        return "Transport(<redacted>)"

    def request(self, method: str, path: str, query: dict | None = None, body: dict | None = None) -> dict:
        if (method, path) not in ALLOWED_ENDPOINTS:
            raise Refused(f"ENDPOINT_NOT_ALLOWED: {method} {path}")
        q = {**(query or {}), "timestamp": str(int(time.time() * 1000))}
        payload = json.dumps(body, separators=(",", ":")) if body is not None else ""
        path_url, _ = sign(self._c._secret, method, path, q)
        sig = hmac.new(self._c._secret.encode(), f"{method}{path_url}{payload}".encode(), hashlib.sha256).hexdigest()
        req = urllib.request.Request(self._base + path_url, method=method, data=payload.encode() if payload else None,
                                     headers={"PIONEX-KEY": self._c._key, "PIONEX-SIGNATURE": sig,
                                              "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with self._open(req, timeout=15) as r:
                out = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise (Ambiguous if exc.code >= 500 else Refused)(f"HTTP {exc.code} on {path}") from None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise Ambiguous(f"request to {path} failed: {type(exc).__name__}") from None
        if isinstance(out, dict) and out.get("result") is False:
            raise Refused(f"Pionex rejected {path}: {str(out.get('code'))[:40]} {str(out.get('message'))[:120]}")
        return out


class Journal:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path), timeout=30)
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS actions(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, mode TEXT,
          strategy_id TEXT, kind TEXT, symbol TEXT, params TEXT, status TEXT, detail TEXT, bu_order_id TEXT,
          commit_usdt REAL, mandate_sha TEXT, base_qty REAL DEFAULT 0, cash_usdt REAL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS pnl_obs(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, total REAL);
        CREATE TABLE IF NOT EXISTS halts(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, kind TEXT, day TEXT,
          detail TEXT);""")
        for col in ("base_qty", "cash_usdt"):                    # journals created before the Red Team fixes
            try:
                self.db.execute(f"ALTER TABLE actions ADD COLUMN {col} REAL DEFAULT 0")
            except sqlite3.OperationalError:
                pass

    def add(self, ts, mode, a: Action, status, detail, sha, bu=None, commit=0.0, base_qty=0.0, cash=0.0):
        self.db.execute("INSERT INTO actions(ts,mode,strategy_id,kind,symbol,params,status,detail,bu_order_id,"
                        "commit_usdt,mandate_sha,base_qty,cash_usdt) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (ts, mode, a.strategy_id, a.kind, a.symbol, json.dumps(a.params, default=str), status,
                         detail[:300], bu, commit, sha, base_qty, cash))
        self.db.commit()

    def open_bots(self) -> list:
        """(bu_order_id, strategy_id, symbol, commit) for LIVE-sent creates not cancelled by a LIVE-sent cancel."""
        rows = self.db.execute("SELECT bu_order_id, strategy_id, symbol, commit_usdt FROM actions WHERE mode='LIVE' "
                               "AND status='SENT' AND kind='grid_create' AND bu_order_id IS NOT NULL").fetchall()
        closed = {r[0] for r in self.db.execute("SELECT bu_order_id FROM actions WHERE mode='LIVE' AND status='SENT' "
                                                "AND kind IN ('grid_cancel','grid_closed')")}
        return [r for r in rows if r[0] not in closed]

    def spot_commit(self) -> float:
        """Net live spot-order exposure: BUY notional minus SELL notional, floored at 0."""
        return max(0.0, self.db.execute("SELECT COALESCE(SUM(commit_usdt),0) FROM actions WHERE mode='LIVE' AND "
                                        "status='SENT' AND kind='spot_order'").fetchone()[0])

    def held(self, symbol: str) -> float:
        """Base quantity this executor's LIVE spot orders hold (estimate; unfilled LIMIT buys count as 0)."""
        return max(0.0, self.db.execute("SELECT COALESCE(SUM(base_qty),0) FROM actions WHERE mode='LIVE' AND "
                                        "status='SENT' AND kind='spot_order' AND symbol=?", (symbol,)).fetchone()[0])

    def spot_symbols(self) -> list:
        return [r[0] for r in self.db.execute("SELECT DISTINCT symbol FROM actions WHERE mode='LIVE' AND "
                                              "status='SENT' AND kind='spot_order'")]

    def spot_cash(self, symbol: str) -> float:
        return self.db.execute("SELECT COALESCE(SUM(cash_usdt),0) FROM actions WHERE mode='LIVE' AND status='SENT' "
                               "AND kind='spot_order' AND symbol=?", (symbol,)).fetchone()[0]

    def halted(self, day: str):
        r = self.db.execute("SELECT kind, detail FROM halts WHERE kind IN ('ABS','UNKNOWN') OR (kind='DAY' AND day=?) "
                            "ORDER BY id DESC LIMIT 1", (day,)).fetchone()
        return r

    def halt(self, ts, kind, day, detail):
        self.db.execute("INSERT INTO halts(ts,kind,day,detail) VALUES(?,?,?,?)", (ts, kind, day, detail[:300]))
        self.db.commit()


def _public_quote(symbol: str):
    """(bid, ask) from the public Pionex book ticker; no credentials."""
    from ..exchange.pionex_public import PionexPublic
    t, _ = PionexPublic().book_ticker(symbol)
    return t.bid, t.ask


def _day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


class Executor:
    def __init__(self, paths, log_path: Path, transport=None, clock=time.time, notifier=None, _armed=False,
                 config_dir=None, quote_fn=None):
        self.config_dir = config_dir or DEFAULT_CONFIG_DIR
        self.paths, self.log_path, self.clock = paths, Path(log_path), clock
        self.var = Path(paths.root)
        self.journal = Journal(self.var / "live_journal.db")
        self.transport = transport if _armed else None       # dry-run can never hold a transport
        self.armed_mode = bool(_armed)
        self._notify = notifier or self._default_notify
        self.quote_fn = quote_fn or _public_quote

    # ---- construction -------------------------------------------------------------------------
    @classmethod
    def armed(cls, paths, log_path, transport=None, **kw):
        """Live executor. Refuses unless preflight passes NOW. Reads the owner's key file at runtime."""
        ex = cls(paths, log_path, transport=transport, _armed=True, **kw)
        reasons, _ = ex.preflight()
        if reasons:
            ex.journal.db.close()
            raise Refused("NOT_ARMED: " + "; ".join(reasons))
        if ex.transport is None:
            cfg = load_live_config(ex.var)
            try:
                ex.transport = Transport(load_credentials(cfg["key_file"], cfg.get("key_var"), cfg.get("secret_var")))
            except (KeyError, AccountReadError) as exc:
                raise Refused(f"NOT_ARMED: key file unusable ({type(exc).__name__})") from None
        return ex

    def _default_notify(self, text: str, level: str = "important"):
        try:
            from ..notify import notify
            notify(self.var, text, level=level, key="live-exec")
        except Exception:               # a notify failure must not break the audit trail, which is the journal
            pass

    def now_ms(self) -> int:
        return int(self.clock() * 1000)

    # ---- rules --------------------------------------------------------------------------------
    def preflight(self):
        """-> (reasons that forbid live action, mandate or None). Empty reasons == armed-capable."""
        why, m = [], None
        if (self.var / "LIVE_STOP").exists():
            why.append("kill switch var/LIVE_STOP present")
        try:
            m = load_mandate(self.config_dir)
        except PolicyError as exc:
            why.append(f"mandate: {str(exc)[:80]}")
            return why, None
        auth = m.raw["authority"]
        if not m.live_enabled:
            why.append("mandate live_enabled is false")
        if m.mode != "LIVE":
            why.append(f"mandate mode is {m.mode}, not LIVE")
        try:
            cfg = load_live_config(self.var)
            if cfg.get("approved_mandate_sha256") != m.sha256:
                why.append("var/live.json approved_mandate_sha256 != mandate hash")
            if not cfg.get("key_file"):
                why.append("var/live.json has no key_file")
            if not isinstance(cfg.get("strategy_allowlist"), list):
                why.append("var/live.json has no strategy_allowlist (owner must list strategies explicitly)")
        except Refused as exc:
            why.append(str(exc))
        if not m.get("execution", "allowed_symbols"):
            why.append("mandate allowed_symbols is empty")
        h = self.journal.halted(_day(self.now_ms()))
        if h:
            why.append(f"halt latch {h[0]}: {h[1]}")
        return why, m

    def limits(self, m) -> dict:
        capital = min(m.initial_capital, LIVE_CAP_USDT)
        frac = m.get("risk", "canary_position_notional_fraction" if m.raw["authority"]["canary_required"]
                     else "position_notional_fraction")
        return {"capital": capital, "position": capital * _d(frac),
                "gross": capital * _d(m.get("risk", "gross_exposure_fraction")),
                "max_positions": int(m.get("risk", "max_positions")), "leverage": _d(m.get("risk", "leverage")),
                "daily_loss": capital * _d(m.get("risk", "daily_loss_fraction")),
                "abs_loss": _d(m.get("risk", "absolute_experiment_loss_usd")),
                "symbols": {str(s).upper() for s in m.get("execution", "allowed_symbols")}}

    def _exposure(self) -> Decimal:
        return sum((_d(c) for _, _, _, c in self.journal.open_bots()), Decimal(0)) + _d(self.journal.spot_commit())

    def _quote(self, symbol: str):
        try:
            bid, ask = (_d(x) for x in self.quote_fn(symbol))
        except Exception as exc:
            raise Refused(f"QUOTE_UNAVAILABLE {symbol}: {type(exc).__name__}") from None
        if bid <= 0 or ask <= 0 or bid >= ask:
            raise Refused(f"QUOTE_INVALID {symbol}")
        return bid, ask

    def _notional(self, a: Action):
        """-> (notional USDT, est. base qty change, est. USDT cash change). Spot orders are valued at the live touch."""
        p = a.params
        if a.kind == "grid_create":
            return _d(p["invest"]), 0.0, 0.0
        side, typ = p.get("side"), p.get("type")
        if side not in ("BUY", "SELL") or typ not in ("LIMIT", "MARKET"):
            raise Refused("spot order needs side BUY|SELL and type LIMIT|MARKET")
        bid, ask = self._quote(a.symbol.upper())
        touch = ask if side == "BUY" else bid
        if typ == "LIMIT":
            price = _d(p["price"])
            if price <= 0 or abs(price / touch - 1) > LIMIT_BAND:
                raise Refused(f"LIMIT price {price} more than {LIMIT_BAND:.0%} from touch {touch}")
        if side == "BUY":
            if typ == "LIMIT":
                raise Refused("LIMIT BUY refused: fills are not tracked, so held coins and cash cannot be known")
            n = _d(p["amount"])
            return n, float(n / (ask * Decimal("1.01"))), -float(n)
        size = _d(p["size"])
        if size <= 0:
            raise Refused("non-positive size")
        held = self.journal.held(a.symbol)
        if float(size) > held:
            raise Refused(f"sell {size} exceeds base this executor holds ({held:.8f}); owner coins are never sold")
        n = size * bid
        return n, -float(size), float(n)

    def _vet(self, a: Action, m, eligible: dict, cfg_allow, pinned: dict | None = None):
        """Returns (notional, base qty change, cash change) or raises Refused. m is a loaded, hash-checked mandate."""
        if a.kind not in ACTION_KINDS:
            raise Refused(f"unknown action kind {a.kind}")
        if a.kind == "futures_order":
            raise Refused("futures refused: mandate risk.spot_only")
        L = self.limits(m)
        pinned = pinned or {}
        if a.kind != "grid_cancel":
            if a.strategy_id not in eligible:
                raise Refused(f"strategy {a.strategy_id} is not ELIGIBLE per the proof gate")
            if eligible[a.strategy_id] != ("grid" if a.kind == "grid_create" else "book"):
                raise Refused(f"strategy {a.strategy_id} is a {eligible[a.strategy_id]} strategy; action {a.kind}")
        if a.kind == "grid_create":
            r = pinned.get(a.strategy_id)
            p = a.params
            want = {"symbol": r.params.get("symbol"), "rows": r.params.get("rows"), "top": r.params.get("top"),
                    "bottom": r.params.get("bottom"), "type": r.params.get("type", "geometric"),
                    "stop": r.params.get("stop")} if r else {}
            got = {"symbol": a.symbol, "rows": p.get("rows"), "top": p.get("top"), "bottom": p.get("bottom"),
                   "type": p.get("type", "geometric"), "stop": p.get("stop")}
            same = all((str(want[k]) == str(got[k])) if k in ("symbol", "type", "stop") else
                       (want[k] is not None and got[k] is not None and _d(want[k]) == _d(got[k])) for k in want)
            if not want or not same:
                raise Refused("grid parameters differ from the proof-gated parameters")
            if _d(p["invest"]) > _d(r.params.get("invest", 0)):
                raise Refused("invest above the proof-gated amount")
        if a.kind == "spot_order" and not BOOK_ORDERS_ENABLED:
            raise Refused("book spot orders refused: no signal-driven order planner exists yet")
        if a.kind != "grid_cancel" and self.armed_mode:
            last = self.journal.db.execute("SELECT MAX(ts) FROM pnl_obs").fetchone()[0]
            if last is None or self.now_ms() - last > PNL_MAX_AGE_MS:
                raise Refused("PNL_STALE: no loss-stop observation in the last 30 minutes (run live-poll)")
        if cfg_allow is not None and a.strategy_id not in cfg_allow:
            raise Refused(f"strategy {a.strategy_id} not in owner strategy_allowlist")
        if a.symbol.upper() not in L["symbols"]:
            raise Refused(f"symbol {a.symbol} not in mandate allowed_symbols")
        if a.kind == "grid_cancel":
            if a.params.get("bu_order_id") not in {b[0] for b in self.journal.open_bots()}:
                raise Refused("cancel refused: not an open bot opened by this executor")
            if a.params.get("close_model", "TO_USDT") != "TO_USDT":
                raise Refused("close_model must be TO_USDT: NOT_SELL would leave coins outside the cap")
            return Decimal(0), 0.0, 0.0
        if _d(a.params.get("leverage", 1)) > L["leverage"]:
            raise Refused("leverage above mandate")
        n, qty, cash = self._notional(a)
        if n <= 0:
            raise Refused("non-positive size")
        sells = a.kind == "spot_order" and a.params.get("side") == "SELL"
        if n > L["position"] and not sells:        # a sell is bounded by what we hold, which was capped when bought
            raise Refused(f"size {n} above per-position cap {L['position']}")
        if not sells:
            if self._exposure() + n > L["gross"]:
                raise Refused(f"exposure would exceed gross cap {L['gross']}")
            if a.kind == "grid_create":
                if len(self.journal.open_bots()) + 1 > L["max_positions"]:
                    raise Refused("max_positions reached")
                if int(a.params["rows"]) > MAX_ROWS or int(a.params["rows"]) < 2:
                    raise Refused("rows out of range")
        return n, qty, cash

    # ---- execution ----------------------------------------------------------------------------
    def execute(self, a: Action) -> dict:
        ts = self.now_ms()
        mode = "LIVE" if self.armed_mode else "DRYRUN"
        reasons, m = self.preflight()
        sha = m.sha256 if m else ""
        try:
            if reasons and self.armed_mode:
                raise Refused("; ".join(reasons))
            if m is None:
                raise Refused("; ".join(reasons))
            results = gate.evaluate_all(self.var, self.log_path, m, ts)
            eligible = {r.strategy_id: r.kind for r in results if r.eligible}
            allow = load_live_config(self.var).get("strategy_allowlist") if (self.var / "live.json").exists() else None
            n, qty, cash = self._vet(a, m, eligible, allow, {r.strategy_id: r for r in results if r.eligible})
            if reasons:                          # dry-run: record what would stop live
                self.journal.add(ts, mode, a, "PLANNED", "would pass caps; live blocked by: " + "; ".join(reasons),
                                 sha, commit=float(n))
                return {"status": "PLANNED", "blocked_by": reasons}
            if not self.armed_mode:
                self.journal.add(ts, mode, a, "PLANNED", "passes every rule", sha, commit=float(n))
                return {"status": "PLANNED", "blocked_by": []}
            try:
                resp = self._send(a, n)
            except Ambiguous as exc:             # may have reached Pionex: never retry, never assume, stop everything
                self.journal.add(ts, mode, a, "UNKNOWN", str(exc), sha)
                self.journal.halt(ts, "UNKNOWN", _day(ts), f"{a.kind} {a.strategy_id}: {str(exc)[:200]}")
                self._notify(f"[live LIVE] UNKNOWN outcome {a.kind} {a.strategy_id} {a.symbol}: HALTED until the owner "
                             f"reconciles on Pionex ({str(exc)[:120]})", "critical")
                return {"status": "UNKNOWN", "reason": str(exc)}
        except Refused as exc:
            self.journal.add(ts, mode, a, "REFUSED", str(exc), sha)
            self._notify(f"[live {mode}] REFUSED {a.kind} {a.strategy_id} {a.symbol}: {str(exc)[:160]}")
            return {"status": "REFUSED", "reason": str(exc)}
        bu = resp.get("bu")
        commit = float(n)
        if a.kind == "grid_cancel":
            commit = 0.0
        elif a.kind == "spot_order" and a.params.get("side") == "SELL":
            commit = -min(float(n), self.journal.spot_commit())     # only reduces what this executor bought
        self.journal.add(ts, mode, a, "SENT", "ok", sha, bu=bu, commit=commit, base_qty=qty, cash=cash)
        self._notify(f"[live LIVE] SENT {a.kind} {a.strategy_id} {a.symbol} {n} USDT")
        return {"status": "SENT", "bu_order_id": bu}

    def _send(self, a: Action, n: Decimal) -> dict:
        if not self.armed_mode or self.transport is None:
            raise Refused("not armed")
        t, p = self.transport, a.params
        base, quote = a.symbol.upper().split("_")
        if a.kind == "grid_create":
            self._reconcile()
            data = {"top": _fmt(p["top"]), "bottom": _fmt(p["bottom"]), "row": int(p["rows"]),
                    "grid_type": p.get("type", "geometric"), "quote_total_investment": _fmt(p["invest"])}
            chk = t.request("POST", "/api/v1/bot/orders/spotGrid/checkParams",
                            body={"base": base, "quote": quote, "buOrderData": data})
            lo = _d((chk.get("data") or {}).get("min_investment", 0))
            if lo > _d(p["invest"]):
                raise Refused(f"investment {p['invest']} below Pionex minimum {lo}")
            create = {"top": data["top"], "bottom": data["bottom"], "row": data["row"], "gridType": data["grid_type"],
                      "quoteTotalInvestment": data["quote_total_investment"], "closeSellModel": "TO_USDT"}
            if p.get("stop"):
                create.update({"lossStopType": "price", "lossStop": _fmt(p["stop"])})
            out = t.request("POST", "/api/v1/bot/orders/spotGrid/create",
                            body={"base": base, "quote": quote, "note": (NOTE_PREFIX + a.strategy_id)[:40],
                                           "buOrderData": create})
            return {"bu": self._need_id((out.get("data") or {}).get("buOrderId"), "create")}
        if a.kind == "grid_cancel":
            t.request("POST", "/api/v1/bot/orders/spotGrid/cancel",
                      body={"buOrderId": p["bu_order_id"], "closeSellModel": p.get("close_model", "TO_USDT")})
            return {"bu": p["bu_order_id"]}
        body = {"symbol": a.symbol.upper(), "side": p["side"], "type": p["type"]}
        if p["type"] == "LIMIT":
            body.update({"price": _fmt(p["price"]), "size": _fmt(p["size"])})
        elif p["side"] == "BUY":
            body["amount"] = _fmt(p["amount"])
        else:
            body["size"] = _fmt(p["size"])
        out = t.request("POST", "/api/v1/trade/order", body=body)
        return {"bu": self._need_id((out.get("data") or {}).get("orderId"), "order")}

    @staticmethod
    def _need_id(v, what):
        if not v:
            raise Ambiguous(f"{what} response carried no id; outcome unknown")
        return str(v)

    def _list_bots(self, status: str) -> list:
        """Every bot with `status`, following pageToken. A repeated or runaway token is an error (fail closed)."""
        orders, token, seen = [], None, set()
        for _ in range(MAX_PAGES):
            out = self.transport.request("GET", "/api/v1/bot/orders",
                                         query={"status": status, **({"pageToken": token} if token else {})})
            data = out.get("data") or {}
            orders += data.get("orders", [])
            token = data.get("nextPageToken") or data.get("pageToken")
            if not token:
                return orders
            if token in seen:
                raise Refused("bot list paging did not terminate")
            seen.add(token)
        raise Refused("bot list has too many pages")

    def _reconcile(self):
        """Refuse (and latch) while Pionex shows a running bot of ours that the journal does not know."""
        try:
            running = self._list_bots("running")
        except Refused as exc:
            raise Refused(f"RECONCILE_FAILED: {exc}") from None
        known = {b[0] for b in self.journal.open_bots()}
        for o in running:
            d = o.get("buOrderData") or {}
            bid = str(o.get("buOrderId") or d.get("buOrderId") or "")
            note = str(o.get("note") or d.get("note") or "")
            if note.startswith(NOTE_PREFIX) and bid not in known:
                ts = self.now_ms()
                self.journal.halt(ts, "UNKNOWN", _day(ts), f"unknown running bot {bid} ({note[:40]})")
                raise Refused(f"RECONCILE_UNKNOWN_BOT {bid}: halted until the owner reconciles")

    # ---- loss stop ----------------------------------------------------------------------------
    @staticmethod
    def _bot_pnl(o: dict) -> float:
        """Conservative P&L of one bot: lowest of realized/total, plus any reported float LOSS."""
        d = o.get("buOrderData") or {}
        vals = [float(d[k]) for k in ("realizedProfit", "totalProfit") if d.get(k) not in (None, "")]
        pnl = min(vals) if vals else 0.0
        for k in ("unrealizedProfit", "floatProfit", "unrealizedPnl", "floatPnl"):
            if d.get(k) not in (None, ""):
                pnl += min(0.0, float(d[k]))
        return pnl

    def poll_pnl(self) -> dict:
        """Armed only. Equity P&L of everything this executor holds, from the exchange and live quotes; trips the
        loss stops. Any failure halts the rest of the UTC day (fail closed)."""
        if not self.armed_mode or self.transport is None:
            raise Refused("not armed")
        ids = {b[0] for b in self.journal.db.execute("SELECT DISTINCT bu_order_id FROM actions WHERE mode='LIVE' "
                                                     "AND status='SENT' AND kind='grid_create'")}
        try:
            total, seen, finished = 0.0, set(), set()
            for status in ("running", "finished"):
                for o in self._list_bots(status):
                    d = o.get("buOrderData") or {}
                    bid = str(o.get("buOrderId") or d.get("buOrderId") or "")
                    if bid in ids and bid not in seen:
                        seen.add(bid)
                        total += self._bot_pnl(o)
                        if status == "finished":
                            finished.add(bid)
            missing = ids - seen
            if missing:                      # its P&L would silently count as 0: fail closed
                raise Refused(f"journalled bot(s) not visible on Pionex: {sorted(missing)[:3]}")
            open_now = {b[0] for b in self.journal.open_bots()}
            for bid in sorted(finished & open_now):      # Pionex ended it (TP/SL/closed): free its cap and slot
                self.journal.db.execute(
                    "INSERT INTO actions(ts,mode,strategy_id,kind,symbol,params,status,detail,bu_order_id,commit_usdt,"
                    "mandate_sha) SELECT ?,'LIVE',strategy_id,'grid_closed',symbol,'{}','SENT','finished on Pionex',"
                    "bu_order_id,0,mandate_sha FROM actions WHERE bu_order_id=? AND kind='grid_create' LIMIT 1",
                    (self.now_ms(), bid))
                self.journal.db.commit()
            for sym in self.journal.spot_symbols():
                bid, _ask = self._quote(sym)
                total += self.journal.held(sym) * float(bid) + self.journal.spot_cash(sym)
        except Refused as exc:
            ts = self.now_ms()
            self.journal.halt(ts, "DAY", _day(ts), f"pnl poll failed: {str(exc)[:200]}")
            self._notify(f"[live] HALT DAY: loss-stop poll failed ({str(exc)[:120]}); no new actions today", "critical")
            return {"total": None, "halt": "DAY", "error": str(exc)}
        return self.observe_pnl(total)

    def observe_pnl(self, total: float) -> dict:
        ts = self.now_ms()
        day = _day(ts)
        _, m = self.preflight()
        if m is None:
            raise Refused("mandate unavailable")
        L = self.limits(m)
        start = int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
        prev = self.journal.db.execute("SELECT total FROM pnl_obs WHERE ts < ? ORDER BY id DESC LIMIT 1",
                                       (start,)).fetchone()
        top = self.journal.db.execute("SELECT MAX(total) FROM pnl_obs WHERE ts >= ?", (start,)).fetchone()[0]
        base = max(prev[0] if prev else 0.0, top if top is not None else float("-inf"))   # day high-water mark
        self.journal.db.execute("INSERT INTO pnl_obs(ts,total) VALUES(?,?)", (ts, total))
        self.journal.db.commit()
        out = {"total": total, "day_pnl": total - base, "halt": None}
        if -total >= float(L["abs_loss"]):
            self.journal.halt(ts, "ABS", day, f"cumulative P&L {total:.2f} <= -{L['abs_loss']}")
            out["halt"] = "ABS"
        elif base - total >= float(L["daily_loss"]):
            self.journal.halt(ts, "DAY", day, f"day P&L {total - base:.2f} <= -{L['daily_loss']}")
            out["halt"] = "DAY"
        if out["halt"]:
            self._notify(f"[live] HALT {out['halt']}: all new actions stopped; positions left as they are", "critical")
        return out


def plan_grid_creates(executor: Executor, results, m) -> list:
    """One create per ELIGIBLE grid strategy that has no open live bot, size clamped to the caps."""
    L = executor.limits(m)
    open_ids = {b[1] for b in executor.journal.open_bots()}
    out = []
    for r in results:
        if r.eligible and r.kind == "grid" and r.strategy_id not in open_ids:
            p = r.params
            room = min(L["position"], L["gross"] - executor._exposure())
            out.append(Action(r.strategy_id, "grid_create", p["symbol"], {
                "invest": float(min(_d(p["invest"]), room)), "rows": p["rows"], "top": p["top"], "bottom": p["bottom"],
                "type": p.get("type", "geometric"), "stop": p.get("stop")}))
    return out


def run_daily_dry(paths, log_path) -> dict:
    """Part C: dry-run against the gate. Writes var/reports/live_gate.json, notifies when the ELIGIBLE set changes."""
    ex = Executor(paths, log_path)
    reasons, m = ex.preflight()
    ts = ex.now_ms()
    mand = m
    if mand is None:
        try:
            mand = load_mandate(ex.config_dir)
        except PolicyError as exc:
            return {"error": str(exc)}
    results = gate.evaluate_all(ex.var, ex.log_path, mand, ts)
    planned = [{"action": a.kind, "strategy": a.strategy_id, "result": ex.execute(a)}
               for a in plan_grid_creates(ex, results, mand)] if m else []
    rep = {"at_ms": ts, "mode": "DRYRUN", "live_blocked_by": reasons, "eligible": sorted(gate.eligible_ids(results)),
           "strategies": [r.as_dict() for r in results], "planned": planned,
           "note": "forward paper record on live prices; gate output is not profit"}
    f = ex.var / "reports" / "live_gate.json"
    try:
        old = set(json.loads(f.read_text(encoding="utf-8")).get("eligible", []))
    except (OSError, ValueError):
        old = set()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    if set(rep["eligible"]) != old:
        ex._notify(f"[live DRYRUN] ELIGIBLE set changed: {rep['eligible'] or 'none'}. Live blocked by: "
                   f"{'; '.join(reasons) or 'nothing'}")
    return rep
