"""CLO-141 verifiable trade ledger (2026-10-26 SAST). Read-only: opens var/forward_shadow.db and var/shadow_grid.db
with mode=ro and writes one CSV. Every row is SIMULATED (paper book fill or shadow-grid fill), none is a real order.

Sources
- forward_shadow.db `fills`  : CTA paper books (defensive, growth, canary, donchian_c1). Realized P&L is computed here
  by average cost (buy fees go into the cost basis, sell fee is deducted from the sell). Equity = latest `equity` row
  of that book at or before the fill time.
- shadow_grid.db `events`    : shadow grids. kind 'fill' and 'start' (the opening base purchase) are rows; 'gap' rows are
  feed notes, not trades. Realized P&L = change of the cumulative `grid_profit` the simulator books for that grid
  (as booked, not recomputed). Equity = latest `snaps` row of that grid at or before the fill time.

Check (check_ledger): each fill price must lie inside [low, high] of the Pionex public 1m kline of the minute of the fill
(strict, no tolerance). Mismatches are listed with their distance in bps; nothing is excused except a `note` copied into
the report (e.g. 'bridged' = trade-feed gap, price was interpolated). Pass = zero mismatches.
"""
from __future__ import annotations

import bisect
import csv
import datetime as dt
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

from pionex_lab.util import PROJECT_ROOT

SINCE_MS = int(dt.datetime(2026, 10, 14, tzinfo=dt.timezone.utc).timestamp() * 1000)
COLUMNS = ["time_utc", "ts_ms", "book", "source", "symbol", "side", "qty", "fill_price", "fee_usdt",
           "realized_pnl_usdt", "running_equity_usdt", "note", "simulated"]
OUT_CSV = PROJECT_ROOT / "docs" / "status" / "ledger-latest.csv"
OUT_CHECK = PROJECT_ROOT / "docs" / "status" / "ledger-check-latest.json"
KLINE_CACHE = PROJECT_ROOT / "var" / "ledger_kline_cache.json"


def _ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def iso(ts_ms: int) -> str:
    return dt.datetime.fromtimestamp(ts_ms / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _equity_lookup(rows):
    """rows: [(ts, equity)] sorted by ts -> f(ts) = equity of latest row with row.ts <= ts (None if none)."""
    keys = [r[0] for r in rows]

    def f(ts):
        i = bisect.bisect_right(keys, ts) - 1
        return rows[i][1] if i >= 0 else None
    return f


def avg_cost_realized(fills):
    """fills: [(symbol, side, qty, price, fee)] in time order -> realized P&L per fill (None for buys... 0.0 for buys)."""
    pos, cost, out = defaultdict(float), defaultdict(float), []
    for sym, side, qty, price, fee in fills:
        if side == "BUY":
            pos[sym] += qty
            cost[sym] += qty * price + fee
            out.append(0.0)
        else:
            avg = cost[sym] / pos[sym] if pos[sym] > 0 else price
            q = min(qty, pos[sym]) if pos[sym] > 0 else qty
            out.append((price - avg) * q - fee)
            pos[sym] -= q
            cost[sym] -= avg * q
    return out


def forward_rows(root: Path = PROJECT_ROOT):
    c = _ro(root / "var" / "forward_shadow.db")
    eq = defaultdict(list)
    for ts, book, e in c.execute("select ts,book,equity from equity order by ts,id"):
        eq[book].append((ts, e))
    look = {b: _equity_lookup(v) for b, v in eq.items()}
    rows = []
    for book in sorted({r[0] for r in c.execute("select distinct book from fills")}):
        f = c.execute("select ts,symbol,side,qty,price,fee from fills where book=? order by ts,id", (book,)).fetchall()
        pnl = avg_cost_realized([(s, sd, q, p, fee) for _, s, sd, q, p, fee in f])
        for (ts, sym, side, qty, price, fee), r in zip(f, pnl):
            if ts >= SINCE_MS:
                rows.append(dict(ts_ms=ts, book=book, source="forward_shadow", symbol=sym, side=side, qty=qty,
                                 fill_price=price, fee_usdt=fee, realized_pnl_usdt=r,
                                 running_equity_usdt=look[book](ts), note="CTA paper book rebalance"))
    return rows


def grid_rows(root: Path = PROJECT_ROOT):
    c = _ro(root / "var" / "shadow_grid.db")
    sym = dict(c.execute("select id,symbol from grids"))
    snaps = defaultdict(list)
    for ts, gid, e in c.execute("select ts,grid_id,equity from snaps order by ts,id"):
        snaps[gid].append((ts, e))
    look = {g: _equity_lookup(v) for g, v in snaps.items()}
    prev, rows = defaultdict(float), []
    for ts, gid, kind, side, price, qty, fee, gp, note in c.execute(
            "select ts,grid_id,kind,side,price,qty,fee,grid_profit,note from events "
            "where kind in ('start','fill') order by ts,id"):
        d = (gp or 0.0) - prev[gid]
        prev[gid] = gp or 0.0
        if ts >= SINCE_MS:
            n = "grid start: opening base purchase" if kind == "start" else \
                "shadow grid fill" + (f"; {note}" if note else "")
            rows.append(dict(ts_ms=ts, book=gid, source="shadow_grid", symbol=sym[gid], side=side, qty=qty,
                             fill_price=price, fee_usdt=fee, realized_pnl_usdt=d,
                             running_equity_usdt=look[gid](ts), note=n))
    return rows


def build_rows(root: Path = PROJECT_ROOT):
    rows = forward_rows(root) + grid_rows(root)
    rows.sort(key=lambda r: (r["ts_ms"], r["book"]))
    for r in rows:
        r["time_utc"] = iso(r["ts_ms"])
        r["simulated"] = "SIMULATED"
    return rows


def write_csv(rows, path: Path = OUT_CSV) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (repr(round(v, 10)) if isinstance(v, float) else v) for k, v in r.items()})


# ---------------------------------------------------------------- checker

def check_price(price: float, low: float, high: float):
    """Strict: None if low <= price <= high else distance outside the bar in bps."""
    if low <= price <= high:
        return None
    edge = low if price < low else high
    return abs(price - edge) / edge * 1e4


def check_rows(rows, client=None, now_ms: int | None = None, cache_path: Path | None = None):
    """Compare each row to the Pionex kline of its minute. Pionex serves 1m bars for ~7 days only, so every 1m bar
    used is stored in cache_path (daily runs keep fills verified at 1m resolution); fills older than that with no
    stored 1m bar fall back to the 5m bar (labelled bar=5M, a weaker check). Returns report dict."""
    import time
    from pionex_lab.exchange.pionex_public import PionexPublic
    client = client or PionexPublic()
    now_ms = now_ms or int(time.time() * 1000)
    stored = json.loads(cache_path.read_text()) if cache_path and cache_path.exists() else {}
    bars: dict[tuple[str, str, int], tuple[float, float]] = {}
    for key, lh in stored.items():
        sym, m = key.rsplit("|", 1)
        bars[(sym, "1M", int(m))] = tuple(lh)

    def load(sym, iv, step, m):
        try:
            ks, _ = client.klines(sym, iv, end_time=min(m + step * 250, now_ms), limit=500)
            for k in ks:
                bars[(sym, iv, k.open_time)] = (float(k.low), float(k.high))
            return None
        except Exception as exc:  # network / schema / retention: report, never excuse
            return str(exc)[:120]
    unavailable, mismatches, ok, by_bar = [], [], 0, defaultdict(int)
    for r in sorted(rows, key=lambda r: (r["symbol"], r["ts_ms"])):
        sym, m1, m5 = r["symbol"], r["ts_ms"] // 60_000 * 60_000, r["ts_ms"] // 300_000 * 300_000
        err = None
        if (sym, "1M", m1) in bars:
            iv, m = "1M", m1
        else:
            err = load(sym, "1M", 60_000, m1)
            if (sym, "1M", m1) in bars:
                iv, m = "1M", m1
            else:
                if (sym, "5M", m5) not in bars:
                    err = load(sym, "5M", 300_000, m5) or err
                iv, m = "5M", m5
        if (sym, iv, m) not in bars:
            unavailable.append(_brief(dict(r, error=err or "no bar returned")))
            continue
        low, high = bars[(sym, iv, m)]
        dist = check_price(r["fill_price"], low, high)
        by_bar[iv] += 1
        if dist is None:
            ok += 1
        else:
            mismatches.append(dict(_brief(r), bar=iv, kline_low=low, kline_high=high, outside_bps=round(dist, 2)))
    if cache_path:
        keep = {f"{s}|{m}": list(lh) for (s, iv, m), lh in bars.items() if iv == "1M"
                and any(r["symbol"] == s and r["ts_ms"] // 60_000 * 60_000 == m for r in rows)}
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(keep), encoding="utf-8")
    n = len(rows)
    return dict(checked=n, matched=ok, mismatched=len(mismatches), kline_unavailable=len(unavailable),
                checked_against=dict(by_bar),
                verdict="PASS" if n and not mismatches and not unavailable else "MISMATCHES",
                rule="fill price inside [low, high] of the Pionex public kline of the fill minute (strict); "
                     "5M bar only where the 1m bar has expired (Pionex keeps ~7 days of 1m)",
                mismatches=mismatches, unavailable=unavailable)

def _brief(r):
    return {k: r.get(k) for k in ("time_utc", "ts_ms", "book", "symbol", "side", "fill_price", "note", "error")
            if r.get(k) is not None}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "build"
    rows = build_rows()
    if cmd == "build":
        write_csv(rows)
        print(f"wrote {OUT_CSV} ({len(rows)} rows, all SIMULATED)")
        return 0
    if cmd == "check":
        rep = check_rows(rows, cache_path=KLINE_CACHE)
        rep["generated_utc"] = iso(int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000))
        OUT_CHECK.write_text(json.dumps(rep, indent=1), encoding="utf-8")
        print({k: rep[k] for k in ("checked", "matched", "mismatched", "kline_unavailable", "checked_against", "verdict")})
        return 0 if rep["verdict"] == "PASS" else 1
    print("usage: python -m pionex_lab.reporting.trade_ledger [build|check]")
    return 2


if __name__ == "__main__":
    sys.exit(main())

