"""Estimated liquidation heatmap from free public Binance USD-M futures data.

Like the commercial heatmaps, this is a MODEL, not observed liquidations or real positions:
whenever open interest rises during a period, the new notional is assumed to be split evenly
between longs and shorts opened at that period's close, spread over leverage tiers. Each tier
places a liquidation level at entry x (1 -/+ 1/leverage +/- maintenance margin). A level is removed
once price trades through it, and all levels shrink proportionally when open interest falls.
The result is a time x price grid of estimated USD liquidations still waiting at each price.

Data: GET /futures/data/openInterestHist and /fapi/v1/klines on fapi.binance.com (public, no key;
open-interest history covers the most recent 30 days). Every range fits in one request per
endpoint by choosing the period.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

FAPI = "https://fapi.binance.com"
UA = "pionex-lab-wavelab"
# range -> (period, number of periods); every range is a single request (Binance caps at 500)
RANGES = {"12h": ("5m", 144), "24h": ("5m", 288), "3d": ("15m", 288), "1w": ("30m", 336),
          "2w": ("1h", 336), "1M": ("2h", 360)}
PERIOD_MS = {"5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000}
# leverage tier weights per model (our own assumptions, documented in the UI)
MODELS = {1: {10: 0.25, 25: 0.25, 50: 0.25, 100: 0.25},     # equal weight
          2: {10: 0.40, 25: 0.30, 50: 0.20, 100: 0.10},     # mostly lower leverage
          3: {25: 0.20, 50: 0.40, 100: 0.40}}               # mostly high leverage
MMR = 0.005          # approximate maintenance margin rate
BINS = 120


class HeatmapError(RuntimeError):
    pass


def binance_symbol(symbol: str) -> str:
    base, _, quote = symbol.partition("_")
    if quote != "USDT" or not base.isalnum():
        raise HeatmapError("only USDT pairs have a Binance USD-M perpetual")
    return base + "USDT"


def http_json(url: str, timeout: float = 15.0):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise HeatmapError(f"Binance HTTP {exc.code} for {url.split('?')[0].rsplit('/', 1)[-1]}") from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise HeatmapError(f"Binance request failed: {exc}") from None


def fetch(symbol: str, rng: str, get=http_json) -> dict:
    """Open interest (USD) and OHLC per period for the range, oldest first, aligned by time."""
    period, n = RANGES[rng]
    sym = binance_symbol(symbol)
    oi = get(f"{FAPI}/futures/data/openInterestHist?symbol={sym}&period={period}&limit={n}")
    kl = get(f"{FAPI}/fapi/v1/klines?symbol={sym}&interval={period}&limit={n + 1}")
    bars = {int(k[0]): (float(k[2]), float(k[3]), float(k[4])) for k in kl}   # open time -> (high, low, close)
    step = PERIOD_MS[period]
    rows = []
    for o in sorted(oi, key=lambda r: int(r["timestamp"])):
        ts = int(o["timestamp"])
        bar = bars.get(ts - step) or bars.get(ts)     # OI is stamped at the period end
        if bar:
            rows.append((ts, float(o["sumOpenInterestValue"]), *bar))
    if len(rows) < 3:
        raise HeatmapError("not enough Binance open-interest history for this symbol")
    return {"symbol": sym, "period": period, "step": step, "rows": rows}


def model(rows: list, step: int, tiers: dict, bins: int = BINS) -> dict:
    """rows: [(t_ms, oi_usd, high, low, close)] oldest first. Returns columns of binned USD."""
    levels = []          # [price, side ('L'/'S'), usd]
    snaps = []
    prev = None
    for t, oi, hi, lo, close in rows:
        levels = [lv for lv in levels if not (lv[1] == "L" and lo <= lv[0] or lv[1] == "S" and hi >= lv[0])]
        if prev is not None:
            d = oi - prev
            if d > 0:
                for lev, w in tiers.items():
                    levels.append([close * (1 - 1 / lev + MMR), "L", d * 0.5 * w])
                    levels.append([close * (1 + 1 / lev - MMR), "S", d * 0.5 * w])
            elif d < 0 and prev > 0:
                keep = max(0.0, 1 + d / prev)
                for lv in levels:
                    lv[2] *= keep
        prev = oi
        snaps.append((t, [tuple(lv) for lv in levels]))
    prices = [lv[0] for _, s in snaps for lv in s] + [r[3] for r in rows] + [r[2] for r in rows]
    lo_p, hi_p = min(prices), max(prices)
    width = (hi_p - lo_p) / bins or 1.0
    cols, max_long, max_short, max_both = [], 0, 0, 0
    for t, s in snaps:
        cells = {}
        for price, side, usd in s:
            b = min(bins - 1, int((price - lo_p) / width))
            c = cells.setdefault(b, [0.0, 0.0])
            c[0 if side == "L" else 1] += usd
        out = [[b, round(v[0]), round(v[1])] for b, v in sorted(cells.items()) if v[0] >= 1 or v[1] >= 1]
        for _, lng, sht in out:
            max_long, max_short, max_both = max(max_long, lng), max(max_short, sht), max(max_both, lng + sht)
        cols.append({"t0": t - step, "t1": t, "cells": out})
    return {"bins": {"lo": lo_p, "hi": hi_p, "n": bins, "width": width}, "columns": cols,
            "max_long": max_long, "max_short": max_short, "max_both": max_both}


def heatmap(symbol: str, rng: str = "24h", model_id: int = 1, lev: str = "all", get=http_json) -> dict:
    if rng not in RANGES:
        raise ValueError(f"range must be one of {list(RANGES)}")
    if model_id not in MODELS:
        raise ValueError("model must be 1, 2 or 3")
    tiers = MODELS[model_id]
    if lev != "all":
        if not lev.isdigit() or int(lev) not in tiers:
            raise ValueError(f"leverage filter for model {model_id} must be all or one of {sorted(tiers)}")
        tiers = {int(lev): tiers[int(lev)]}
    data = fetch(symbol, rng, get)
    out = model(data["rows"], data["step"], tiers)
    out.update(symbol=symbol, source=f"Binance USD-M {data['symbol']} open interest ({data['period']} periods)",
               range=rng, model=model_id, leverage=lev, tiers=tiers, generated_at=int(time.time() * 1000),
               note="Estimated from open-interest changes and assumed leverage; not observed liquidations.")
    return out
