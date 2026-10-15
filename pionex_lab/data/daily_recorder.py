"""Daily recorder for free public series that cannot be bought back later -> var/alpha/recorded.db.
Spec: research/edge_candidates_2026-10-14.md section 8. Public endpoints only, no keys. PROXY/observational data.

  deribit_iv      BTC/ETH ATM implied vol by expiry (from public/get_book_summary_by_currency, kind=option)
  deribit_skew    25-delta risk reversal (call IV - put IV) and butterfly at the expiries nearest 7/30/90 days
  pionex_spread   Pionex SPOT bookTickers bid/ask spread (bps) for every enabled USDT pair
  premium_kline   Binance USD-M premiumIndexKlines daily bars: the 10 basket coins plus PAXG
  cb_binance      Coinbase BTC-USD vs Binance BTCUSDT daily close and the premium in bps
Deribit mark_iv is in percent; deltas are Black-Scholes with r=0 and the option's own underlying price as the
forward. Snapshot rows are keyed by the UTC snapshot day, so a second run on the same day does not duplicate.
Kline-style rows are keyed by bar time and only closed bars are stored (INSERT OR IGNORE: history is never
rewritten). One failing source never stops the others.
"""
from __future__ import annotations

import json
import math
import sqlite3
import time
import urllib.request
from datetime import datetime, timezone

UA = {"User-Agent": "pionex-lab-research"}
D = 86_400_000
BASKET = ("BTC", "ETH", "SOL", "XRP", "DOGE", "LINK", "ADA", "BNB", "AVAX", "LTC")
PREMIUM_SYMBOLS = tuple(c + "USDT" for c in BASKET) + ("PAXGUSDT",)
TENORS = (7, 30, 90)
SCHEMA = """
CREATE TABLE IF NOT EXISTS deribit_iv(day INTEGER, currency TEXT, expiry INTEGER, dte REAL, forward REAL, atm_iv REAL,
  PRIMARY KEY(day, currency, expiry));
CREATE TABLE IF NOT EXISTS deribit_skew(day INTEGER, currency TEXT, tenor INTEGER, expiry INTEGER, dte REAL,
  atm_iv REAL, rr25 REAL, bfly25 REAL, PRIMARY KEY(day, currency, tenor));
CREATE TABLE IF NOT EXISTS pionex_spread(day INTEGER, symbol TEXT, bid REAL, ask REAL, spread_bps REAL,
  PRIMARY KEY(day, symbol));
CREATE TABLE IF NOT EXISTS premium_kline(symbol TEXT, t INTEGER, open REAL, high REAL, low REAL, close REAL,
  PRIMARY KEY(symbol, t));
CREATE TABLE IF NOT EXISTS cb_binance(t INTEGER PRIMARY KEY, cb_close REAL, bn_close REAL, premium_bps REAL);
"""


def get_json(url, tries=3):
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.loads(r.read())
        except Exception:  # noqa: BLE001 - public endpoints throttle; back off and retry
            if k == tries - 1:
                raise
            time.sleep(2 * (k + 1))


def _day(now_ms):
    return now_ms - now_ms % D


# ---- Deribit options -------------------------------------------------------------------------------------------
def _ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_delta(fwd, strike, vol, years, is_call):
    """Black-Scholes forward delta (r=0). vol is a fraction."""
    if vol <= 0 or years <= 0:
        return None
    d1 = (math.log(fwd / strike) + 0.5 * vol * vol * years) / (vol * math.sqrt(years))
    return _ncdf(d1) if is_call else _ncdf(d1) - 1


def parse_expiry(name):
    """'BTC-27MAR26-80000-C' -> (expiry ms at 08:00 UTC, strike, is_call)."""
    cur, exp, strike, cp = name.split("-")
    dt = datetime.strptime(exp.title(), "%d%b%y").replace(hour=8, tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000), float(strike.replace("d", ".")), cp == "C"


def _interp(points, x):
    """Linear interpolation of y at x over (x, y) points; None if x is outside their range."""
    pts = sorted(points)
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1 and x1 > x0:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return None


def option_surface(summaries, now_ms):
    """-> {expiry_ms: {"dte", "forward", "atm_iv", "rr25", "bfly25"}} from book summaries (mark_iv in percent)."""
    by_exp = {}
    for s in summaries:
        iv, fwd = s.get("mark_iv"), s.get("underlying_price")
        if not iv or not fwd:
            continue
        try:
            exp, k, call = parse_expiry(s["instrument_name"])
        except (ValueError, KeyError):
            continue
        if exp <= now_ms:
            continue
        by_exp.setdefault(exp, []).append((k, call, float(iv) / 100, float(fwd)))
    out = {}
    for exp, rows in by_exp.items():
        years = (exp - now_ms) / (365 * D)
        fwd = sorted(r[3] for r in rows)[len(rows) // 2]
        strikes = {}
        for k, call, iv, _ in rows:
            strikes.setdefault(k, {})[call] = iv
        mid = [(k, sum(v.values()) / len(v)) for k, v in strikes.items()]
        atm = _interp(mid, fwd)
        calls, puts = [], []
        for k, call, iv, _ in rows:
            d = bs_delta(fwd, k, iv, years, call)
            if d is None:
                continue
            (calls if call else puts).append((abs(d), iv))
        c25, p25 = _interp(calls, 0.25), _interp(puts, 0.25)
        rec = {"dte": (exp - now_ms) / D, "forward": fwd, "atm_iv": atm, "rr25": None, "bfly25": None}
        if c25 is not None and p25 is not None:
            rec["rr25"] = c25 - p25
            rec["bfly25"] = (c25 + p25) / 2 - atm if atm is not None else None
        out[exp] = rec
    return out


def record_deribit(con, now_ms, fetch):
    n = 0
    for cur in ("BTC", "ETH"):
        url = f"https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency={cur}&kind=option"
        surf = option_surface(fetch(url)["result"], now_ms)
        day = _day(now_ms)
        for exp, r in surf.items():
            con.execute("INSERT OR REPLACE INTO deribit_iv VALUES(?,?,?,?,?,?)",
                        (day, cur, exp, r["dte"], r["forward"], r["atm_iv"]))
            n += 1
        for tenor in TENORS:
            cand = [(abs(r["dte"] - tenor), exp) for exp, r in surf.items() if r["rr25"] is not None]
            if not cand:
                continue
            exp = min(cand)[1]
            r = surf[exp]
            con.execute("INSERT OR REPLACE INTO deribit_skew VALUES(?,?,?,?,?,?,?,?)",
                        (day, cur, tenor, exp, r["dte"], r["atm_iv"], r["rr25"], r["bfly25"]))
            n += 1
    return n


# ---- Pionex spreads --------------------------------------------------------------------------------------------
def record_pionex(con, now_ms, fetch):
    syms = fetch("https://api.pionex.com/api/v1/common/symbols?type=SPOT")["data"]["symbols"]
    enabled = {s["symbol"] for s in syms if s.get("enable") and s.get("quoteCurrency") == "USDT"}
    tickers = fetch("https://api.pionex.com/api/v1/market/bookTickers?type=SPOT")["data"]["tickers"]
    day, n = _day(now_ms), 0
    for t in tickers:
        if t.get("symbol") not in enabled:
            continue
        try:
            bid, ask = float(t["bidPrice"]), float(t["askPrice"])
        except (KeyError, TypeError, ValueError):
            continue
        if bid <= 0 or ask < bid:
            continue
        con.execute("INSERT OR REPLACE INTO pionex_spread VALUES(?,?,?,?,?)",
                    (day, t["symbol"], bid, ask, (ask - bid) / ((ask + bid) / 2) * 1e4))
        n += 1
    return n


# ---- Binance premium index klines ------------------------------------------------------------------------------
def record_premium(con, now_ms, fetch, symbols=PREMIUM_SYMBOLS):
    n = 0
    for sym in symbols:
        rows = fetch(f"https://fapi.binance.com/fapi/v1/premiumIndexKlines?symbol={sym}&interval=1d&limit=10")
        for r in rows:
            t = int(r[0])
            if t + D > now_ms:      # bar still open
                continue
            cur = con.execute("INSERT OR IGNORE INTO premium_kline VALUES(?,?,?,?,?,?)",
                              (sym, t, float(r[1]), float(r[2]), float(r[3]), float(r[4])))
            n += cur.rowcount
    return n


# ---- Coinbase vs Binance ---------------------------------------------------------------------------------------
def record_coinbase(con, now_ms, fetch):
    cb = fetch("https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=86400")
    bn = fetch("https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=10")
    bn_close = {int(r[0]): float(r[4]) for r in bn}
    n = 0
    for c in cb:                    # [time_s, low, high, open, close, volume]
        t = int(c[0]) * 1000
        if t + D > now_ms or t not in bn_close:
            continue
        cbc = float(c[4])
        cur = con.execute("INSERT OR IGNORE INTO cb_binance VALUES(?,?,?,?)",
                          (t, cbc, bn_close[t], (cbc / bn_close[t] - 1) * 1e4))
        n += cur.rowcount
    return n


SOURCES = {"deribit": record_deribit, "pionex_spread": record_pionex, "premium": record_premium,
           "coinbase_binance": record_coinbase}


def record_daily(db_path, now_ms=None, fetch=get_json):
    """Run every source once; -> {source: rows written or 'error: ...'}."""
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    report = {}
    for name, fn in SOURCES.items():
        try:
            with con:
                report[name] = fn(con, now_ms, fetch)
        except Exception as e:  # noqa: BLE001 - one failing source must not stop the others
            report[name] = f"error: {e}"
    con.close()
    return report
