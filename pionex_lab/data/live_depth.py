"""Live order-book depth recorder (Binance spot, public REST, no key) for forward tests.

Every `every` seconds, reads GET /api/v3/depth?limit=5000 for each symbol (about +/-1% of the book
for BTC) and stores cumulative bid/ask depth within +/-0.2, 0.5 and 1 % of the mid price. Spot,
not futures: the historical signal was found on the futures bookDepth archive, so this is a
genuinely forward and slightly different check. Watch-only; request weight 250 per call
(limit 6000/min). Usage: py -m pionex_lab.data.live_depth  (Ctrl+C to stop).
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

URL = "https://api.binance.com/api/v3/depth?symbol={s}&limit=5000"
LEVELS = (0.2, 0.5, 1.0)
SCHEMA = """CREATE TABLE IF NOT EXISTS live_depth(symbol TEXT NOT NULL, t INTEGER NOT NULL, mid REAL NOT NULL,
  pct REAL NOT NULL, bids REAL NOT NULL, asks REAL NOT NULL, reach REAL NOT NULL, PRIMARY KEY(symbol, t, pct));"""


def snapshot(symbol: str):
    req = urllib.request.Request(URL.format(s=symbol), headers={"User-Agent": "pionex-lab-research"})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read())
    bids = [(float(p), float(q)) for p, q in d["bids"]]
    asks = [(float(p), float(q)) for p, q in d["asks"]]
    mid = (bids[0][0] + asks[0][0]) / 2
    reach = min(1 - bids[-1][0] / mid, asks[-1][0] / mid - 1) * 100       # % of book covered on both sides
    out = []
    for pct in LEVELS:
        b = sum(q for p, q in bids if p >= mid * (1 - pct / 100))
        a = sum(q for p, q in asks if p <= mid * (1 + pct / 100))
        out.append((pct, b, a))
    return mid, reach, out


def run(db_path, symbols=("BTCUSDT", "ETHUSDT"), every=60):
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    while True:
        t0 = time.time()
        stamp = int(t0 // every * every * 1000)
        for s in symbols:
            try:
                mid, reach, rows = snapshot(s)
                with con:
                    con.executemany("INSERT OR REPLACE INTO live_depth VALUES(?,?,?,?,?,?,?)",
                                    [(s, stamp, mid, p, b, a, reach) for p, b, a in rows])
            except Exception as e:  # noqa: BLE001 - a missed minute is fine; keep recording
                print(f"{time.strftime('%H:%M:%S')} {s}: {e}", flush=True)
        time.sleep(max(1.0, every - (time.time() - t0)))


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2] / "var" / "orderbook"
    root.mkdir(parents=True, exist_ok=True)
    run(root / "live.db", every=int(sys.argv[1]) if len(sys.argv) > 1 else 60)
