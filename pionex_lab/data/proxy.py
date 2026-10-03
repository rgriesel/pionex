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
INTERVALS = {"5M": "5m", "60M": "1h"}
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


def fetch(store, symbol: str, interval: str, months: int, today: date, now_ms: int, get=http_get) -> dict:
    """Fill `store` with `months` full months before `today` plus this month's completed days.
    Periods already complete in the store are skipped, so the daily refresh fetches one file."""
    raw_sym, raw_iv = SYMBOLS[symbol], INTERVALS[interval]
    step = KLINE_INTERVALS[interval]
    first = date(today.year, today.month, 1)

    def daily(start, end):
        d, out = start, []
        while d < min(end, today):
            out.append((f"{BASE_URL}/daily/klines/{raw_sym}/{raw_iv}/{raw_sym}-{raw_iv}-{d:%Y-%m-%d}.zip",
                        d, d + timedelta(days=1), None))
            d += timedelta(days=1)
        return out

    files = []
    for k in range(months, 0, -1):
        y, m = divmod(first.year * 12 + first.month - 1 - k, 12)
        start = date(y, m + 1, 1)
        end = date(y + (m + 1) // 12, (m + 1) % 12 + 1, 1)
        # A month's archive is published a few days after it ends; until then use its daily files.
        files.append((f"{BASE_URL}/monthly/klines/{raw_sym}/{raw_iv}/{raw_sym}-{raw_iv}-{start:%Y-%m}.zip",
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
