"""Explicitly labelled proxy-venue history: Binance public spot klines (data.binance.vision).

Pionex serves about 10,000 candles per interval (~35 days of 5-minute bars), too short for the
60-day out-of-sample gate. references/research.md: "Collect missing history; do not silently
substitute another venue." This module substitutes openly:

- It downloads Binance's published, SHA-256-checksummed monthly/daily kline archives (public
  market data; no account, no key) into a SEPARATE database (var/proxy_market.db). Pionex's
  market store is never written.
- `tracking_check` measures how closely the proxy follows Pionex's own bars over the overlap;
  research refuses the proxy when it does not track.
- Research cycles on proxy bars record the venue and the tracking evidence. The cost model still
  uses Pionex fees and observed Pionex spreads, and a qualified candidate still needs its paper
  trial on observed Pionex quotes before anything else.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import urllib.error
import urllib.request
import zipfile
from datetime import date, timedelta
from decimal import Decimal

from ..exchange.pionex_public import KLINE_INTERVALS, Kline

BASE_URL = "https://data.binance.vision/data/spot"
VENUE = "Binance public spot archive (data.binance.vision) - PROXY VENUE, not Pionex"
SYMBOLS = {"BTC_USDT": "BTCUSDT", "ETH_USDT": "ETHUSDT"}
INTERVALS = {"5M": "5m", "60M": "1h", "1D": "1d"}
# Research may use the proxy only if it tracks Pionex this closely on overlapping bars.
MIN_OVERLAP_BARS = 2000
MAX_MEDIAN_CLOSE_DIFF_BPS = 5.0
MIN_RETURN_CORRELATION = 0.95


class ProxyDataError(RuntimeError):
    pass


def http_get(url: str, timeout: float = 60.0) -> bytes | None:
    """GET a public archive file; None when it does not exist (404)."""
    req = urllib.request.Request(url, headers={"User-Agent": "pionex-lab-research"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def parse_klines(csv_bytes: bytes) -> list:
    """Binance kline CSV rows -> Kline. Spot archives switched open_time from ms to us in 2025."""
    out = []
    for row in csv.reader(io.StringIO(csv_bytes.decode("utf-8"))):
        if not row or not row[0].strip().isdigit():
            continue  # header line, if any
        t = int(row[0])
        if t > 10 ** 14:
            t //= 1000
        out.append(Kline(t, Decimal(row[1]), Decimal(row[2]), Decimal(row[3]), Decimal(row[4]), Decimal(row[5])))
    return out


def _download(url: str, get) -> list | None:
    blob = get(url)
    if blob is None:
        return None
    check = get(url + ".CHECKSUM")
    if check is None:
        raise ProxyDataError(f"no checksum published for {url}")
    expected = check.decode().split()[0].strip().lower()
    if hashlib.sha256(blob).hexdigest() != expected:
        raise ProxyDataError(f"checksum mismatch for {url}")
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        return parse_klines(z.read(z.namelist()[0]))


def _count(store, symbol, interval, start_ms, end_ms) -> int:
    return store.conn.execute("SELECT COUNT(*) FROM klines WHERE symbol=? AND interval=? AND open_time>=? "
                              "AND open_time<?", (symbol, interval, start_ms, end_ms)).fetchone()[0]


def _ms(d: date) -> int:
    return (d.toordinal() - date(1970, 1, 1).toordinal()) * 86_400_000


# Research window: this many full months before the current month. 42 months starts on or after
# 2023-04-01 until 2026-10, i.e. after the 2023-03-24 Binance spot trading halt (a real 16-bar gap
# that the data-quality gate would rightly reject; gaps are never filled with invented bars).
DEFAULT_MONTHS = 42


def window_start(today: date, months: int) -> date:
    """First day of the month `months` full months before `today`'s month."""
    y, m = divmod(today.year * 12 + today.month - 1 - months, 12)
    return date(y, m + 1, 1)


def window_start_ms(today: date, months: int = DEFAULT_MONTHS) -> int:
    return _ms(window_start(today, months))


PERP_BASE_URL = "https://data.binance.vision/data/futures/um"
PERP_VENUE = "Binance USD-M perpetual klines archive (data.binance.vision/futures/um) - PROXY VENUE, not Pionex"
PERP_SYMBOLS = {"BTC_USDT_PERP": "BTCUSDT", "ETH_USDT_PERP": "ETHUSDT"}   # stored beside spot under these keys


def fetch(store, symbol: str, interval: str, months: int, today: date, now_ms: int, get=http_get) -> dict:
    """Fill `store` with `months` full months before `today` plus this month's completed days.
    Periods already complete in the store are skipped, so the daily refresh fetches one file.
    `symbol` is a spot key (SYMBOLS) or a perpetual key (PERP_SYMBOLS, futures archive)."""
    perp = symbol in PERP_SYMBOLS
    base = PERP_BASE_URL if perp else BASE_URL
    raw_sym, raw_iv = (PERP_SYMBOLS if perp else SYMBOLS)[symbol], INTERVALS[interval]
    step = KLINE_INTERVALS[interval]
    first = date(today.year, today.month, 1)

    def daily(start, end):
        d, out = start, []
        while d < min(end, today):
            out.append((f"{base}/daily/klines/{raw_sym}/{raw_iv}/{raw_sym}-{raw_iv}-{d:%Y-%m-%d}.zip",
                        d, d + timedelta(days=1), None))
            d += timedelta(days=1)
        return out

    files = []
    for k in range(months, 0, -1):
        y, m = divmod(first.year * 12 + first.month - 1 - k, 12)
        start = date(y, m + 1, 1)
        end = date(y + (m + 1) // 12, (m + 1) % 12 + 1, 1)
        # A month's archive is published a few days after it ends; until then use its daily files.
        files.append((f"{base}/monthly/klines/{raw_sym}/{raw_iv}/{raw_sym}-{raw_iv}-{start:%Y-%m}.zip",
                      start, end, daily(start, end)))
    files += daily(first, today)
    got = skipped = missing = 0
    while files:
        url, start, end, fallback = files.pop(0)
        s_ms, e_ms = _ms(start), _ms(end)
        if _count(store, symbol, interval, s_ms, e_ms) >= (e_ms - s_ms) // step:
            skipped += 1
            continue
        klines = _download(url, get)
        if klines is None:
            if fallback:
                files[:0] = fallback
            else:
                missing += 1
            continue
        store.upsert_klines(symbol, interval, klines, None, now_ms)
        got += 1
    return {"symbol": symbol, "interval": interval, "files_downloaded": got, "files_skipped": skipped,
            "files_missing": missing, "bars": _count(store, symbol, interval, 0, 1 << 62)}


FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
FUNDING_VENUE = "Binance USD-M perpetual funding rates (public fapi/v1/fundingRate) - PROXY VENUE, not Pionex"
FUNDING_SCHEMA = """CREATE TABLE IF NOT EXISTS funding(symbol TEXT NOT NULL, t INTEGER NOT NULL, rate TEXT NOT NULL,
  PRIMARY KEY(symbol, t));"""


def http_get_json(url: str, timeout: float = 30.0):
    blob = http_get(url, timeout)
    return None if blob is None else json.loads(blob.decode("utf-8"))


def fetch_funding(conn, symbol: str, now_ms: int, days: int = 420, get_json=http_get_json,
                  start_ms: int | None = None) -> dict:
    """Settled funding rates (public, no key), paged 1000 at a time, into the separate proxy
    database's `funding` table. Covers from `start_ms` (default `days` back): if stored history
    does not reach that far back it is backfilled, otherwise only newer settlements are fetched."""
    conn.executescript(FUNDING_SCHEMA)
    want = start_ms if start_ms is not None else now_ms - days * 86_400_000
    lo, hi = conn.execute("SELECT MIN(t), MAX(t) FROM funding WHERE symbol=?", (symbol,)).fetchone()
    start = want if lo is None or lo > want + 8 * 3_600_000 else hi + 1
    got = 0
    while start < now_ms:
        page = get_json(f"{FUNDING_URL}?symbol={SYMBOLS[symbol]}&startTime={start}&limit=1000") or []
        rows = [(symbol, int(p["fundingTime"]), str(p["fundingRate"])) for p in page if int(p["fundingTime"]) <= now_ms]
        if not rows:
            break
        with conn:
            conn.executemany("INSERT OR IGNORE INTO funding(symbol, t, rate) VALUES(?,?,?)", rows)
        got += len(rows)
        start = max(r[1] for r in rows) + 1
        if len(page) < 1000:
            break
    total = conn.execute("SELECT COUNT(*) FROM funding WHERE symbol=?", (symbol,)).fetchone()[0]
    return {"symbol": symbol, "funding_rows_added": got, "funding_rows": total}


def funding_series(conn, symbol: str) -> list:
    """[(settlement_ms, rate)] oldest first; empty if none stored."""
    try:
        return [(int(t), float(r)) for t, r in conn.execute("SELECT t, rate FROM funding WHERE symbol=? ORDER BY t",
                                                             (symbol,))]
    except Exception:  # noqa: BLE001 - table absent: no funding history
        return []


METRICS_VENUE = ("Binance USD-M futures metrics archive (data.binance.vision: open interest, long/short "
                 "ratios, taker volume ratio) - PROXY VENUE, not Pionex")
METRICS_SCHEMA = """CREATE TABLE IF NOT EXISTS metrics(symbol TEXT NOT NULL, t INTEGER NOT NULL, oi_coin REAL,
  oi_usd REAL, top_ls_count REAL, top_ls_sum REAL, ls_count REAL, taker_ls REAL, PRIMARY KEY(symbol, t));"""
METRIC_FIELDS = ("oi_coin", "oi_usd", "top_ls_count", "top_ls_sum", "ls_count", "taker_ls")


def parse_metrics(csv_bytes: bytes) -> list:
    """Binance daily metrics CSV -> [(t_ms, oi_coin, oi_usd, top_ls_count, top_ls_sum, ls_count, taker_ls)]."""
    from datetime import datetime, timezone
    out = []
    for row in csv.reader(io.StringIO(csv_bytes.decode("utf-8"))):
        if not row or row[0] == "create_time":
            continue
        t = int(datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp() * 1000)
        vals = []
        for v in row[2:8]:
            try:
                vals.append(float(v))
            except ValueError:
                vals.append(None)
        out.append((t, *vals))
    return out


def fetch_metrics(conn, symbol: str, today: date, months: int, get=http_get, workers: int = 8) -> dict:
    """Daily futures-metrics archives (5-minute snapshots) for the research window, downloaded in
    parallel with checksum verification. Days already complete in the table are skipped."""
    from concurrent.futures import ThreadPoolExecutor
    conn.executescript(METRICS_SCHEMA)
    raw = SYMBOLS[symbol]
    d, days = window_start(today, months), []
    while d < today:
        s_ms = _ms(d)
        have = conn.execute("SELECT COUNT(*) FROM metrics WHERE symbol=? AND t>=? AND t<?",
                            (symbol, s_ms, s_ms + 86_400_000)).fetchone()[0]
        if have < 288:
            days.append(d)
        d += timedelta(days=1)

    def one(day):
        url = f"https://data.binance.vision/data/futures/um/daily/metrics/{raw}/{raw}-metrics-{day:%Y-%m-%d}.zip"
        blob = get(url)
        if blob is None:
            return day, None
        check = get(url + ".CHECKSUM")
        if check is None or hashlib.sha256(blob).hexdigest() != check.decode().split()[0].strip().lower():
            raise ProxyDataError(f"checksum problem for {url}")
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            return day, parse_metrics(z.read(z.namelist()[0]))
    got = missing = 0
    with ThreadPoolExecutor(workers) as ex:
        for day, rows in ex.map(one, days):
            if rows is None:
                missing += 1
                continue
            with conn:
                conn.executemany("INSERT OR REPLACE INTO metrics(symbol, t, oi_coin, oi_usd, top_ls_count, top_ls_sum, "
                                 "ls_count, taker_ls) VALUES(?,?,?,?,?,?,?,?)", [(symbol, *r) for r in rows])
            got += 1
    total = conn.execute("SELECT COUNT(*) FROM metrics WHERE symbol=?", (symbol,)).fetchone()[0]
    return {"symbol": symbol, "metric_days_downloaded": got, "metric_days_missing": missing, "metric_rows": total}


def metrics_series(conn, symbol: str, start_ms: int | None = None) -> dict:
    """{field: {t_ms: value}} of stored 5-minute metrics snapshots; empty if none."""
    try:
        rows = conn.execute(f"SELECT t, {', '.join(METRIC_FIELDS)} FROM metrics WHERE symbol=? AND t>=? ORDER BY t",
                            (symbol, start_ms or 0)).fetchall()
    except Exception:  # noqa: BLE001 - table absent
        return {}
    return {f: {int(r[0]): r[k + 1] for r in rows if r[k + 1] is not None} for k, f in enumerate(METRIC_FIELDS)}


def metrics_aligned(conn, symbol: str, times: list, fields=("oi_usd", "ls_count")) -> dict:
    """{field: [value per bar]} using the snapshot stamped at each bar's OPEN time (known before
    the bar closes; conservative). A bar with no snapshot within 10 minutes before its open gets NaN."""
    nan = float("nan")
    out = {f: [nan] * len(times) for f in fields}
    if not times:
        return out
    try:
        rows = conn.execute(f"SELECT t, {', '.join(fields)} FROM metrics WHERE symbol=? AND t>=? AND t<=? ORDER BY t",
                            (symbol, times[0] - 600_000, times[-1])).fetchall()
    except Exception:  # noqa: BLE001 - table absent: no metrics
        return out
    j = -1
    for i, t in enumerate(times):
        while j + 1 < len(rows) and rows[j + 1][0] <= t:
            j += 1
        if j >= 0 and t - rows[j][0] <= 600_000:
            for k, f in enumerate(fields):
                v = rows[j][k + 1]
                out[f][i] = nan if v is None else float(v)
    return out


def tracking_check(proxy_bars, pionex_bars) -> dict:
    """Compare proxy and Pionex bars on identical open times: median |close difference| in bps
    and the correlation of bar-to-bar close returns."""
    px = dict(zip(proxy_bars.t, proxy_bars.c))
    pairs = [(px[t], c) for t, c in zip(pionex_bars.t, pionex_bars.c) if t in px]
    n = len(pairs)
    result = {"overlap_bars": n, "median_close_diff_bps": None, "return_correlation": None, "ok": False,
              "thresholds": {"min_overlap_bars": MIN_OVERLAP_BARS, "max_median_close_diff_bps": MAX_MEDIAN_CLOSE_DIFF_BPS,
                             "min_return_correlation": MIN_RETURN_CORRELATION}}
    if n < 3:
        return result
    diffs = sorted(abs(a - b) / b * 10_000 for a, b in pairs)
    med = diffs[n // 2] if n % 2 else (diffs[n // 2 - 1] + diffs[n // 2]) / 2
    ra = [pairs[i][0] / pairs[i - 1][0] - 1 for i in range(1, n)]
    rb = [pairs[i][1] / pairs[i - 1][1] - 1 for i in range(1, n)]
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va, vb = sum((x - ma) ** 2 for x in ra), sum((y - mb) ** 2 for y in rb)
    corr = cov / math.sqrt(va * vb) if va > 0 and vb > 0 else None
    result.update(median_close_diff_bps=round(med, 3), return_correlation=round(corr, 5) if corr is not None else None)
    result["ok"] = (n >= MIN_OVERLAP_BARS and med <= MAX_MEDIAN_CLOSE_DIFF_BPS and corr is not None
                    and corr >= MIN_RETURN_CORRELATION)
    return result
