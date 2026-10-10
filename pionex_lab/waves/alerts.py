"""Wave alerts: watch-only Elliott wave entry and close alerts for the user's own manual trading.

On every closed bar (1h by default) this runs the Wave Lab engine (`elliott.analyze`) on completed
Pionex bars, applies fixed confirmation rules, and notifies: always to var/logs/wave_alerts.log and
var/wave_alerts.db, and to Telegram when the user has configured a bot. It never places orders.

Rules v1 (fixed 2026-10-10, before any alert was produced):
  OPEN  when the primary count has just entered a driving wave (wave 3 or 5 of an impulse, wave C
        of a correction, or a new wave 1 after a completed A-B-C), in the wave's direction, and
        ALL confirmations agree: Elliott Wave Oscillator sign, RSI(14) vs 50, close vs EMA(50),
        count score >= min_score, and the count's invalidation level on the correct side and at
        most max_risk_pct away. "Just entered" means the previous closed bar's primary count was
        not in that same wave and direction, so one setup yields one alert.
  CLOSE when the close breaks the invalidation recorded at entry (stop), reaches the target
        recorded at entry (the nearest Fibonacci target ahead), the primary count's wave in
        progress points against the position on two consecutive closes, or after max_hold_bars.
One open position per symbol. Every alert is journaled with its price; closed positions record
gross and net basis points (taker fee per side charged twice; spread, slippage and futures funding
are NOT included), so the rules can be judged on evidence. Alerts are rule outputs, not advice.

Telegram credentials are loaded at runtime from the env file named in var/wave_alerts.json
(TELEGRAM_BOT_TOKEN, optional TELEGRAM_CHAT_ID). They are never printed, logged or stored.
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from ..strategies.indicators import ema, rsi
from ..util import iso_ms
from .elliott import analyze, scan_summary, wave_oscillator

log = logging.getLogger("pionex_lab.wave_alerts")
RULES_VERSION = "wave-alerts v1 (2026-10-10)"
DEFAULTS = {"symbols": ["BTC_USDT"], "interval": "60M", "degree": "intermediate", "bars": 500,
            "min_score": 60.0, "max_risk_pct": 5.0, "max_hold_bars": 168, "fee_bps_per_side": 5.0,
            "stale_after_minutes": 10, "poll_seconds": 30, "telegram_env_file": None}
DRIVING = {"3", "5", "C"}
SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS evaluations(id INTEGER PRIMARY KEY, at INTEGER NOT NULL, symbol TEXT NOT NULL,
  interval TEXT NOT NULL, bar_t INTEGER NOT NULL, close REAL NOT NULL, wave TEXT, move TEXT, pattern TEXT,
  score REAL, invalidation REAL, next_target REAL, ewo REAL, rsi REAL, ema50 REAL, action TEXT, reason TEXT,
  UNIQUE(symbol, interval, bar_t));
CREATE TABLE IF NOT EXISTS positions(id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, side TEXT NOT NULL,
  opened_bar INTEGER NOT NULL, entry REAL NOT NULL, invalidation REAL NOT NULL, target REAL, wave TEXT,
  closed_bar INTEGER, exit REAL, exit_reason TEXT, gross_bps REAL, net_bps REAL, adverse INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY, at INTEGER NOT NULL, symbol TEXT NOT NULL,
  kind TEXT NOT NULL, price REAL NOT NULL, text TEXT NOT NULL, telegram TEXT);
"""


class TelegramError(RuntimeError):
    pass


# ---------------------------------------------------------------- decisions (pure, testable)
def driving_entry(primary) -> str | None:
    """'LONG'/'SHORT' if the primary count's wave in progress is a driving wave, else None."""
    if not primary or primary.get("invalidated"):
        return None
    wave, status = str(primary.get("current_wave")), primary.get("status") or ""
    driving = wave in DRIVING or (wave == "1" and "A-B-C complete" in status)
    if not driving:
        return None
    return "LONG" if primary.get("move") == "up" else "SHORT"


def confirmations(side, close, ewo, rsi_v, ema50, primary, cfg) -> list:
    """Failed confirmations (empty list means all confirmations agree)."""
    long = side == "LONG"
    ok = lambda x: x is not None and math.isfinite(x)  # noqa: E731 - NaN must never pass a comparison
    fails = []
    if not ok(ewo) or (ewo <= 0 if long else ewo >= 0):
        fails.append("EWO")
    if not ok(rsi_v) or (rsi_v <= 50 if long else rsi_v >= 50):
        fails.append("RSI")
    if not ok(ema50) or (close <= ema50 if long else close >= ema50):
        fails.append("EMA50")
    if (primary.get("score") or 0) < cfg["min_score"]:
        fails.append("score")
    inv = primary.get("invalidation")
    if not ok(inv) or (inv >= close if long else inv <= close) or abs(close - inv) / close * 100 > cfg["max_risk_pct"]:
        fails.append("invalidation")
    return fails


def exit_reason(pos: dict, close: float, primary, held_bars: int, cfg) -> tuple:
    """(reason or None, new adverse streak) for an open position at this close."""
    long = pos["side"] == "LONG"
    if (close <= pos["invalidation"]) if long else (close >= pos["invalidation"]):
        return "invalidation broken (stop)", 0
    if pos["target"] is not None and ((close >= pos["target"]) if long else (close <= pos["target"])):
        return "target reached", 0
    against = bool(primary) and primary.get("move") == ("down" if long else "up")
    streak = pos["adverse"] + 1 if against else 0
    if streak >= 2:
        return "count turned against the position on two closes", streak
    if held_bars >= cfg["max_hold_bars"]:
        return "maximum holding time reached", streak
    return None, streak


def bps(side, entry, exit_, fee_bps):
    gross = ((exit_ / entry - 1) if side == "LONG" else (entry / exit_ - 1)) * 1e4
    return gross, gross - 2 * fee_bps


# ---------------------------------------------------------------- telegram
def load_telegram(env_file) -> dict | None:
    if not env_file:
        return None
    from ..exchange.account import _parse_env
    try:
        env = _parse_env(Path(env_file).read_text(encoding="utf-8-sig"))
    except OSError:
        return None
    tok = env.get("TELEGRAM_BOT_TOKEN")
    return {"token": tok, "chat_id": env.get("TELEGRAM_CHAT_ID")} if tok else None


def _tg(token, method, params, opener=urllib.request.urlopen):
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}",
                                 data=urllib.parse.urlencode(params).encode(), method="POST")
    try:
        with opener(req, timeout=15) as r:
            body = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise TelegramError(f"HTTP {exc.code} on {method}") from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise TelegramError(f"{method} failed: {str(exc).replace(token, '<redacted>')}") from None
    if not body.get("ok"):
        raise TelegramError(f"{method} rejected: {str(body.get('description', ''))[:120]}")
    return body.get("result")


def telegram_send(tg: dict, text: str, opener=urllib.request.urlopen) -> str:
    """Send to the configured chat; if no chat id is set, use the latest chat that messaged the bot."""
    chat = tg.get("chat_id")
    if not chat:
        updates = _tg(tg["token"], "getUpdates", {"limit": 20}, opener) or []
        chats = [u[k]["chat"]["id"] for u in updates for k in ("message", "channel_post") if k in u]
        if not chats:
            raise TelegramError("no chat yet: send any message to your bot first")
        chat = tg["chat_id"] = chats[-1]
    _tg(tg["token"], "sendMessage", {"chat_id": chat, "text": text, "disable_web_page_preview": "true"}, opener)
    return "sent"


# ---------------------------------------------------------------- runner
def _fmt(x):
    return f"{x:,.2f}" if x is not None else "-"


def connect(path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.row_factory = sqlite3.Row
    return conn


class WaveAlerts:
    def __init__(self, conn, view, cfg: dict, notify=None, clock=time.time):
        self.conn, self.view, self.cfg, self.notify, self.clock = conn, view, {**DEFAULTS, **cfg}, notify, clock

    def _alert(self, symbol, kind, price, text):
        status = None
        if self.notify:
            try:
                status = self.notify(text)
            except TelegramError as exc:
                status = f"error: {exc}"
                log.warning("telegram: %s", exc)
        with self.conn:
            self.conn.execute("INSERT INTO alerts(at, symbol, kind, price, text, telegram) VALUES(?,?,?,?,?,?)",
                              (int(self.clock() * 1000), symbol, kind, price, text, status))
        log.info("%s %s @ %s", kind, symbol, _fmt(price))

    def step(self) -> list:
        """Evaluate every symbol's newest completed bar once. Returns the actions taken."""
        now_ms = int(self.clock() * 1000)
        out = []
        for sym in self.cfg["symbols"]:
            out.append(self.evaluate(sym, now_ms))
        return out

    def evaluate(self, sym, now_ms):
        cfg, iv = self.cfg, self.cfg["interval"]
        b = self.view.bars(sym, iv, limit=cfg["bars"], end_ms=now_ms, complete_only=True)
        if len(b) < 60:
            return (sym, "NOT_ENOUGH_BARS")
        bar_t, step = b.t[-1], b.interval_ms
        if self.conn.execute("SELECT 1 FROM evaluations WHERE symbol=? AND interval=? AND bar_t=?",
                             (sym, iv, bar_t)).fetchone():
            return (sym, "ALREADY_EVALUATED")
        a = analyze(b.t, b.o, b.h, b.l, b.c, degree=cfg["degree"], history=False)
        p, close = a.get("primary"), b.c[-1]
        row = scan_summary(sym, iv, a, close)
        ewo = wave_oscillator(b.h, b.l)[-1]
        r = rsi(b.c, 14)[-1]
        e = ema(b.c, 50)[-1]
        stale = now_ms - (bar_t + step) > cfg["stale_after_minutes"] * 60_000
        action, reason = "NONE", ""
        pos = self.conn.execute("SELECT * FROM positions WHERE symbol=? AND closed_bar IS NULL", (sym,)).fetchone()
        prev = self.conn.execute("SELECT wave, move FROM evaluations WHERE symbol=? AND interval=? ORDER BY bar_t "
                                 "DESC LIMIT 1", (sym, iv)).fetchone()
        if stale:
            action, reason = "SKIP", "bar closed too long ago (catch-up after a restart); no alert"
        elif pos is not None:
            pos = dict(pos)
            held = (bar_t - pos["opened_bar"]) // step
            why, streak = exit_reason(pos, close, p, held, cfg)
            if why:
                gross, net = bps(pos["side"], pos["entry"], close, cfg["fee_bps_per_side"])
                with self.conn:
                    self.conn.execute("UPDATE positions SET closed_bar=?, exit=?, exit_reason=?, gross_bps=?, net_bps=?, "
                                      "adverse=? WHERE id=?", (bar_t, close, why, gross, net, streak, pos["id"]))
                action, reason = "CLOSE", why
                self._alert(sym, "CLOSE", close, (
                    f"CLOSE {pos['side']} {sym} @ {_fmt(close)} ({iso_ms(bar_t + step)[:16]} UTC close)\n"
                    f"Why: {why}\nEntry {_fmt(pos['entry'])} -> {gross:+.0f} bps before fees, {net:+.0f} bps after "
                    f"{cfg['fee_bps_per_side']:g} bps/side (spread and funding not included)\n{RULES_VERSION}"))
            else:
                with self.conn:
                    self.conn.execute("UPDATE positions SET adverse=? WHERE id=?", (streak, pos["id"]))
                action, reason = "HOLD", f"in {pos['side']}; adverse streak {streak}"
        else:
            side = driving_entry(p)
            fresh = side is not None and (prev is None or (prev["wave"], prev["move"]) != (str(p["current_wave"]), p["move"]))
            if side and not fresh:
                action, reason = "NONE", "same wave as the previous close (one alert per setup)"
            elif side:
                fails = confirmations(side, close, ewo, r, e, p, cfg)
                if fails:
                    action, reason = "NO_CONFIRM", "unconfirmed: " + ", ".join(fails)
                else:
                    target = row.get("next_target")
                    with self.conn:
                        self.conn.execute("INSERT INTO positions(symbol, side, opened_bar, entry, invalidation, target, wave) "
                                          "VALUES(?,?,?,?,?,?,?)", (sym, side, bar_t, close, p["invalidation"], target,
                                                                    str(p["current_wave"])))
                    action, reason = f"OPEN_{side}", f"{p['type']} wave {p['current_wave']} {p['move']}"
                    risk = abs(close - p["invalidation"]) / close * 100
                    self._alert(sym, f"OPEN_{side}", close, (
                        f"OPEN {side} {sym} @ {_fmt(close)} ({iso_ms(bar_t + step)[:16]} UTC close, {iv})\n"
                        f"Count: {p['type']}, wave {p['current_wave']} {p['move']}, score {p['score']}\n"
                        f"Invalidation (stop): {_fmt(p['invalidation'])} ({risk:.2f}% away)\n"
                        f"Target: {_fmt(target)}\n"
                        f"Confirmed: EWO {'+' if ewo and ewo > 0 else '-'}, RSI {r:.0f}, "
                        f"{'above' if close > e else 'below'} EMA50\n"
                        f"{RULES_VERSION}. Rule output, not financial advice; you decide and place the trade."))
        with self.conn:
            self.conn.execute(
                "INSERT INTO evaluations(at, symbol, interval, bar_t, close, wave, move, pattern, score, invalidation, "
                "next_target, ewo, rsi, ema50, action, reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (now_ms, sym, iv, bar_t, close, str(p["current_wave"]) if p else None, p["move"] if p else None,
                 p["type"] if p else None, p["score"] if p else None, p["invalidation"] if p else None,
                 row.get("next_target"), ewo, r, e, action, reason))
        return (sym, action)


def config_path(paths) -> Path:
    return Path(paths.root) / "wave_alerts.json"


def run(paths, stop, once: bool = False) -> int:
    from ..data.store import MarketView
    cfg_file = config_path(paths)
    if not cfg_file.exists():
        log.info("wave alerts disabled: %s not present", cfg_file)
        return 0
    cfg = {**DEFAULTS, **json.loads(cfg_file.read_text(encoding="utf-8"))}
    tg = load_telegram(cfg.get("telegram_env_file"))
    notify = (lambda text: telegram_send(tg, text)) if tg else None
    log.info("wave alerts started: %s %s %s, telegram %s", ",".join(cfg["symbols"]), cfg["interval"], RULES_VERSION,
             "on" if tg else "off (log only)")
    wa = WaveAlerts(connect(Path(paths.root) / "wave_alerts.db"), MarketView(paths.market), cfg, notify)
    while True:
        for sym, action in wa.step():
            if action not in ("ALREADY_EVALUATED",):
                log.info("%s: %s", sym, action)
        if once or stop.wait(cfg["poll_seconds"]):
            return 0
