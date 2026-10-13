"""Free alternative data for factor research (no keys), stored in var/alpha/alt.db. PROXY sources only.

  fng        alternative.me Crypto Fear & Greed index, daily since 2018
  cb_1h      Coinbase Exchange BTC-USD hourly closes (US spot demand; vs Binance = "Coinbase premium")
  dvol_1h    Deribit BTC DVOL implied-volatility index, hourly
  stables    DefiLlama total USD-stablecoin supply, daily
  fred:*     FRED daily series: DTWEXBGS (broad dollar), DGS10 (10y yield), VIXCLS (VIX), NASDAQCOM
Every row is (series, t_ms, value). Daily series are stamped at 00:00 UTC of their date; research
code must only use a daily value from the NEXT day on (US closes arrive after the crypto day starts).
"""
from __future__ import annotations

import csv
import io
import json
import sqlite3
import time
import urllib.request
from datetime import datetime, timedelta, timezone

UA = {"User-Agent": "pionex-lab-research"}
SCHEMA = "CREATE TABLE IF NOT EXISTS alt(series TEXT NOT NULL, t INTEGER NOT NULL, v REAL NOT NULL, PRIMARY KEY(series, t));"
H, D = 3_600_000, 86_400_000


def _get(url, tries=4):
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except Exception:  # noqa: BLE001 - public endpoints throttle; back off and retry
            if k == tries - 1:
                raise
            time.sleep(2 * (k + 1))


def _ms(dt):
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def fng():
    j = json.loads(_get("https://api.alternative.me/fng/?limit=0&format=json"))
    return [("fng", int(x["timestamp"]) * 1000, float(x["value"])) for x in j["data"]]


def coinbase_1h(start):
    rows, t = [], start
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    while t < end:
        t2 = min(t + timedelta(hours=300), end)
        url = ("https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=3600"
               f"&start={t.strftime('%Y-%m-%dT%H:%M:%SZ')}&end={t2.strftime('%Y-%m-%dT%H:%M:%SZ')}")
        for c in json.loads(_get(url)):
            rows.append(("cb_1h", int(c[0]) * 1000, float(c[4])))
        t = t2
        time.sleep(0.25)
    return rows


def dvol_1h(start):
    rows, s = [], _ms(start)
    now = int(time.time() * 1000)
    while s < now:
        e = min(s + 1000 * H, now)
        url = (f"https://www.deribit.com/api/v2/public/get_volatility_index_data?currency=BTC&start_timestamp={s}"
               f"&end_timestamp={e}&resolution=3600")
        data = json.loads(_get(url))["result"]["data"]
        rows += [("dvol_1h", int(x[0]), float(x[4])) for x in data]
        s = e
        time.sleep(0.2)
    return rows


def stables():
    j = json.loads(_get("https://stablecoins.llama.fi/stablecoincharts/all"))
    return [("stables", int(x["date"]) * 1000, float(x["totalCirculatingUSD"].get("peggedUSD", 0))) for x in j
            if x.get("totalCirculatingUSD")]


def fred(series_id):
    txt = _get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}").decode()
    rows = []
    for r in csv.DictReader(io.StringIO(txt)):
        k = [x for x in r if x.lower() not in ("date", "observation_date")]
        try:
            v = float(r[k[0]])
        except (ValueError, IndexError):
            continue
        d = r.get("observation_date") or r.get("DATE") or r.get("date")
        rows.append((f"fred:{series_id}", _ms(datetime.strptime(d, "%Y-%m-%d")), v))
    return rows


def fetch_all(db_path, start=datetime(2023, 1, 1)):
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    report = {}
    jobs = [("fng", fng), ("stables", stables), ("cb_1h", lambda: coinbase_1h(start)), ("dvol_1h", lambda: dvol_1h(start))]
    jobs += [(f"fred:{s}", (lambda s=s: fred(s))) for s in ("DTWEXBGS", "DGS10", "VIXCLS", "NASDAQCOM")]
    for name, fn in jobs:
        try:
            rows = fn()
            with con:
                con.executemany("INSERT OR REPLACE INTO alt VALUES(?,?,?)", rows)
            report[name] = len(rows)
        except Exception as e:  # noqa: BLE001 - one failing source must not stop the others
            report[name] = f"error: {e}"
    return report


def series(db_path, name):
    con = sqlite3.connect(db_path)
    return [(t, v) for t, v in con.execute("SELECT t, v FROM alt WHERE series=? ORDER BY t", (name,))]
