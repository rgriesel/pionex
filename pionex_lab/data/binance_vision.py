"""Binance public data archive (data.binance.vision) -> a SEPARATE sqlite file (research only, PROXY data).

Spot monthly 1d kline zips, including pairs that were later delisted, plus daily zips for the running month.
Used by swing/pit.py (CLO-2 / C2). Never writes to proxy_market.db. Zips are untrusted input: they are parsed
in memory (zipfile + csv), never extracted to disk. Timestamps: archives switched to microseconds in 2025;
values above 1e14 are divided by 1000.
"""
from __future__ import annotations

import csv
import io
import re
import sqlite3
import time
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

LIST_URL = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
FILE_URL = "https://data.binance.vision/"
SCHEMA = """
CREATE TABLE IF NOT EXISTS bars(symbol TEXT NOT NULL, t INTEGER NOT NULL, o REAL NOT NULL, h REAL NOT NULL,
  l REAL NOT NULL, c REAL NOT NULL, vol REAL NOT NULL, qvol REAL NOT NULL, PRIMARY KEY(symbol, t));
CREATE TABLE IF NOT EXISTS fetched(key TEXT PRIMARY KEY, rows INTEGER NOT NULL, at INTEGER NOT NULL);
"""


def _get(url: str, tries: int = 4) -> bytes:
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "pionex-lab-research"}), timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            if k == tries - 1:
                raise
        except Exception:
            if k == tries - 1:
                raise
        time.sleep(1.5 * (k + 1))
    raise RuntimeError("unreachable")


def list_prefix(prefix: str, delimiter: str | None = "/") -> tuple[list[str], list[str]]:
    """S3 listing (paginated). Returns (common prefixes, keys)."""
    prefixes, keys, marker = [], [], ""
    while True:
        q = {"prefix": prefix}
        if delimiter:
            q["delimiter"] = delimiter
        if marker:
            q["marker"] = marker
        xml = _get(LIST_URL + "?" + urllib.parse.urlencode(q)).decode()
        prefixes += re.findall(r"<CommonPrefixes><Prefix>([^<]+)</Prefix>", xml)
        ks = re.findall(r"<Contents><Key>([^<]+)</Key>", xml)
        keys += ks
        if "<IsTruncated>true</IsTruncated>" not in xml:
            return prefixes, keys
        marker = re.findall(r"<NextMarker>([^<]+)</NextMarker>", xml)
        marker = marker[0] if marker else (ks[-1] if ks else prefixes[-1])


def usdt_symbols() -> list[str]:
    pre, _ = list_prefix("data/spot/monthly/klines/")
    return sorted(p.rstrip("/").split("/")[-1] for p in pre if p.rstrip("/").endswith("USDT"))


def parse_zip(blob: bytes) -> list[tuple]:
    """Rows (t_ms, o, h, l, c, vol, qvol) from a kline zip; header rows and non-positive prices are skipped."""
    out = []
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for name in z.namelist():
            if not name.endswith(".csv"):
                continue
            for row in csv.reader(io.TextIOWrapper(z.open(name), "utf-8")):
                try:
                    t = int(row[0])
                    o, h, l, c, v, qv = (float(x) for x in (row[1], row[2], row[3], row[4], row[5], row[7]))
                except (ValueError, IndexError):
                    continue
                if t > 10 ** 14:
                    t //= 1000
                if min(o, h, l, c) <= 0:
                    continue
                out.append((t, o, h, l, c, v, qv))
    return out


def connect(path: Path | str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.executescript("PRAGMA journal_mode=WAL;" + SCHEMA)
    return conn


def _fetch_key(key: str):
    try:
        return key, parse_zip(_get(FILE_URL + key))
    except urllib.error.HTTPError as e:
        return key, None if e.code == 404 else e


def sync(db_path, symbols=None, workers: int = 16, log=print) -> dict:
    """Download every monthly 1d zip not yet in the database, then the daily zips of the running month.
    Idempotent: `fetched` records finished keys."""
    conn = connect(db_path)
    done = {r[0] for r in conn.execute("SELECT key FROM fetched")}
    symbols = symbols or usdt_symbols()

    def keys_for(sym):
        _, ks = list_prefix(f"data/spot/monthly/klines/{sym}/1d/")
        return [k for k in ks if k.endswith(".zip")]
    with ThreadPoolExecutor(workers) as ex:
        monthly = [k for ks in ex.map(keys_for, symbols) for k in ks]
        last_month = {}
        for k in monthly:
            sym = k.split("/")[-3]
            last_month[sym] = max(last_month.get(sym, ""), k[-11:-4])
        newest = max(last_month.values())
        # symbols still printing in the newest completed month also get daily files for the running month
        running = [s for s, m in last_month.items() if m == newest]

        def daily_keys(sym):
            _, ks = list_prefix(f"data/spot/daily/klines/{sym}/1d/")
            return [k for k in ks if k.endswith(".zip")]
        daily = [k for ks in ex.map(daily_keys, running) for k in ks]
        daily = [k for k in daily if k[-14:-4] > newest + "-31"]            # days after the newest monthly file
        todo = [k for k in monthly + daily if k not in done]
        log(f"{len(symbols)} USDT symbols, {len(monthly)} monthly + {len(daily)} daily files, {len(todo)} to fetch")
        n = bad = 0
        for key, rows in ex.map(_fetch_key, todo):
            if isinstance(rows, Exception):
                bad += 1
                log(f"  failed {key}: {rows}")
                continue
            sym = key.split("/")[-3]
            conn.executemany("INSERT OR REPLACE INTO bars VALUES(?,?,?,?,?,?,?,?)", [(sym,) + r for r in (rows or [])])
            conn.execute("INSERT OR REPLACE INTO fetched VALUES(?,?,?)", (key, len(rows or []), int(time.time() * 1000)))
            n += 1
            if n % 2000 == 0:
                conn.commit()
                log(f"  {n}/{len(todo)}")
    conn.commit()
    return {"symbols": len(symbols), "fetched": n, "failed": bad, "monthly": len(monthly), "daily": len(daily)}
