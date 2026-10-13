"""Binance USD-M futures order-book depth archive (data.binance.vision bookDepth) - PROXY, not Pionex.

Each daily file holds a snapshot about every 30 s of cumulative depth within +/-0.2, 1, 2, 3, 4, 5 %
of the price (negative = bids, positive = asks). We keep the LAST snapshot inside each 5-minute
bucket, so a row stamped with a bucket start is known at that bucket's close (no look-ahead when
used at the close of the 5m bar with the same open time). Checksums are verified.
"""
from __future__ import annotations

import hashlib
import io
import sqlite3
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone

URL = "https://data.binance.vision/data/futures/um/daily/bookDepth/{s}/{s}-bookDepth-{d}.zip"
SCHEMA = """CREATE TABLE IF NOT EXISTS depth5m(symbol TEXT NOT NULL, t INTEGER NOT NULL, pct REAL NOT NULL,
  depth REAL NOT NULL, notional REAL NOT NULL, PRIMARY KEY(symbol, t, pct));
CREATE TABLE IF NOT EXISTS depth_days(symbol TEXT NOT NULL, day TEXT NOT NULL, rows INTEGER, PRIMARY KEY(symbol, day));"""
BUCKET = 300_000


def _get(url: str) -> bytes | None:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "pionex-lab-research"}), timeout=60) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def parse(blob: bytes) -> dict:
    """{(bucket_start_ms, pct): (depth, notional)} keeping the last snapshot per bucket."""
    out, day_ms = {}, {}
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for line in z.read(z.namelist()[0]).decode().splitlines():
            if not line or line[0] not in "0123456789":
                continue
            ts, pct, dep, notl = line.split(",")
            d = ts[:10]                                                    # "YYYY-MM-DD HH:MM:SS", UTC
            base = day_ms.get(d)
            if base is None:
                base = day_ms[d] = int(datetime(int(d[:4]), int(d[5:7]), int(d[8:10]), tzinfo=timezone.utc).timestamp() * 1000)
            t = base + (int(ts[11:13]) * 3600 + int(ts[14:16]) * 60 + int(ts[17:19])) * 1000
            out[(t - t % BUCKET, float(pct))] = (float(dep), float(notl))   # later rows overwrite earlier ones
    return out


def fetch_day(symbol: str, d: date):
    url = URL.format(s=symbol, d=d.isoformat())
    blob = _get(url)
    if blob is None:
        return d, None
    check = _get(url + ".CHECKSUM")
    if check and hashlib.sha256(blob).hexdigest() != check.decode().split()[0].strip().lower():
        raise ValueError(f"checksum mismatch {url}")
    return d, parse(blob)


def fetch(db_path, symbol="BTCUSDT", start=date(2023, 1, 1), end=None, workers=16):
    from concurrent.futures import ThreadPoolExecutor
    end = end or (datetime.now(timezone.utc).date() - timedelta(days=1))
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    have = {r[0] for r in con.execute("SELECT day FROM depth_days WHERE symbol=?", (symbol,))}
    days = [start + timedelta(days=k) for k in range((end - start).days + 1)]
    todo = [d for d in days if d.isoformat() not in have]
    got = missing = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for d, rows in pool.map(lambda x: fetch_day(symbol, x), todo):
            if rows is None:
                missing += 1
                continue
            with con:
                con.executemany("INSERT OR REPLACE INTO depth5m VALUES(?,?,?,?,?)",
                                [(symbol, t, p, dp, nt) for (t, p), (dp, nt) in rows.items()])
                con.execute("INSERT OR REPLACE INTO depth_days VALUES(?,?,?)", (symbol, d.isoformat(), len(rows)))
            got += 1
    return {"symbol": symbol, "days_fetched": got, "days_missing": missing, "days_total": len(days)}
