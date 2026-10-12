"""Local Wave Lab web server (standard library).

* Binds to loopback only and rejects requests whose Host header is not this loopback address,
  so other web pages cannot reach it through DNS rebinding.
* Serves public market data and its analysis. No credentials, no account access, no order
  endpoints, no writes: watchlists, drawings and alerts live in the browser's local storage.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import math
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ..exchange.pionex_public import KLINE_INTERVALS
from ..util import PROJECT_ROOT
from .elliott import DEGREES, analyze, scan_summary, wave_oscillator
from .feeds import MAX_BARS, validate
from .heatmap import RANGES, HeatmapError, heatmap as liq_heatmap

log = logging.getLogger("pionex_lab.waves")
PAGE = PROJECT_ROOT / "wavelab" / "index.html"
CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; "
       "connect-src 'self'; media-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
MAX_SCAN = 60


def _clean(x):
    """JSON-safe floats (NaN/inf -> None)."""
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    return x


class WaveApi:
    def __init__(self, feed, heat_source=None):
        self.feed = feed
        self.heat_source = heat_source          # injectable for tests; default: Binance public API
        self._heat, self._heat_lock = {}, threading.Lock()

    def meta(self):
        return {"feed": self.feed.name, "feed_label": self.feed.label,
                "fallback_reason": getattr(self.feed, "fallback_reason", None),
                "intervals": list(KLINE_INTERVALS), "degrees": list(DEGREES),
                "disclaimer": "Wave counts are pattern hypotheses, not forecasts or evidence of profitability."}

    def symbols(self):
        return {"feed": self.feed.name, "symbols": self.feed.symbols()}

    def candles(self, symbol, interval, limit=500):
        bars = self.feed.candles(symbol, interval, max(20, min(MAX_BARS, int(limit))))
        return {"feed": self.feed.name, "symbol": symbol, "interval": interval, **bars}

    def analysis(self, symbol, interval, degree="intermediate", limit=500, pct=None, bars=False):
        if degree not in DEGREES:
            raise ValueError("invalid degree")
        if pct is not None and not 0.001 <= pct <= 0.5:
            raise ValueError("pct must be within 0.001-0.5")
        b = self.feed.candles(symbol, interval, max(20, min(MAX_BARS, int(limit))))
        a = analyze(b["t"], b["o"], b["h"], b["l"], b["c"], degree=degree, pct=pct)
        a["ewo"] = wave_oscillator(b["h"], b["l"])
        out = {"feed": self.feed.name, "symbol": symbol, "interval": interval, **a}
        if bars:
            out["bars"] = b
        return out

    def quotes(self, symbols):
        def one(sym):
            try:
                b = self.feed.candles(sym, "60M", 25)
                if not b["c"]:
                    return sym, None
                last, ref = b["c"][-1], b["c"][0]
                return sym, {"last": last, "change_pct": (last / ref - 1) * 100 if ref else None,
                             "high": max(b["h"]), "low": min(b["l"]), "spark": b["c"]}
            except Exception as exc:  # one bad symbol must not break the watchlist
                return sym, {"error": str(exc)[:120]}
        with ThreadPoolExecutor(4) as ex:
            return {"feed": self.feed.name, "quotes": dict(ex.map(one, symbols))}

    def heatmap(self, symbol, rng, model, lev):
        """Estimated liquidation heatmap (waves/heatmap.py), cached for 60 s per parameter set."""
        key = (symbol, rng, model, lev)
        now = time.time()
        with self._heat_lock:
            hit = self._heat.get(key)
            if hit and now - hit[0] < 60:
                return hit[1]
        try:
            kw = {"get": self.heat_source} if self.heat_source else {}
            out = {"available": True, **liq_heatmap(symbol, rng, model, lev, **kw)}
        except HeatmapError as exc:
            out = {"available": False, "symbol": symbol, "note": str(exc)}
        with self._heat_lock:
            self._heat[key] = (now, out)
            if len(self._heat) > 64:
                self._heat.pop(next(iter(self._heat)))
        return out

    def scan(self, symbols, intervals, degree):
        jobs = [(s, iv) for s in symbols for iv in intervals][:MAX_SCAN]

        def one(job):
            sym, iv = job
            try:
                b = self.feed.candles(sym, iv, 500)
                a = analyze(b["t"], b["o"], b["h"], b["l"], b["c"], degree=degree, history=False)
                return scan_summary(sym, iv, a, b["c"][-1] if b["c"] else None)
            except Exception as exc:
                return {"symbol": sym, "interval": iv, "error": str(exc)[:120]}
        with ThreadPoolExecutor(4) as ex:
            rows = list(ex.map(one, jobs))
        return {"feed": self.feed.name, "degree": degree, "rows": rows}


def _csv(q, name, maxn=40):
    raw = q.get(name, [""])[0]
    items = [x.strip().upper() for x in raw.split(",") if x.strip()]
    if not items or len(items) > maxn:
        raise ValueError(f"{name}: 1-{maxn} items")
    return items


def make_handler(api: WaveApi, allowed_hosts: set):
    class Handler(BaseHTTPRequestHandler):
        server_version = "wavelab"
        sys_version = ""

        def log_message(self, fmt, *args):
            log.info("%s %s", self.command, self.path.split("?")[0])

        def _send(self, status, body: bytes, ctype="application/json"):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", CSP)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status, obj):
            self._send(status, json.dumps(_clean(obj), separators=(",", ":")).encode())

        def do_GET(self):
            if self.headers.get("Host", "") not in allowed_hosts:
                return self._json(403, {"error": "host not allowed"})
            url = urllib.parse.urlsplit(self.path)
            q = urllib.parse.parse_qs(url.query)
            arg = lambda k, d=None: q.get(k, [d])[0]  # noqa: E731
            try:
                if url.path in ("/", "/index.html"):
                    return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
                if url.path == "/api/meta":
                    return self._json(200, api.meta())
                if url.path == "/api/symbols":
                    return self._json(200, api.symbols())
                if url.path in ("/api/candles", "/api/analysis"):
                    sym, iv = (arg("symbol") or "").upper(), arg("interval", "60M")
                    validate(sym, iv)
                    limit = int(arg("limit", "500"))
                    if url.path == "/api/candles":
                        return self._json(200, api.candles(sym, iv, limit))
                    pct = arg("pct")
                    return self._json(200, api.analysis(sym, iv, arg("degree", "intermediate"), limit,
                                                        float(pct) if pct else None, arg("bars") == "1"))
                if url.path == "/api/heatmap":
                    sym = (arg("symbol") or "").upper()
                    validate(sym, "60M")
                    rng, lev = arg("range", "24h"), arg("lev", "all")
                    if rng not in RANGES:
                        raise ValueError(f"range must be one of {list(RANGES)}")
                    return self._json(200, api.heatmap(sym, rng, int(arg("model", "1")), lev))
                if url.path == "/api/quotes":
                    syms = _csv(q, "symbols")
                    for s in syms:
                        validate(s, "60M")
                    return self._json(200, api.quotes(syms))
                if url.path == "/api/scan":
                    syms, ivs = _csv(q, "symbols"), [x for x in (arg("intervals") or "").split(",") if x]
                    if not ivs or len(ivs) > 6:
                        raise ValueError("intervals: 1-6 items")
                    for s in syms:
                        for iv in ivs:
                            validate(s, iv)
                    deg = arg("degree", "intermediate")
                    if deg not in DEGREES:
                        raise ValueError("invalid degree")
                    return self._json(200, api.scan(syms, ivs, deg))
                return self._json(404, {"error": "not found"})
            except ValueError as exc:
                return self._json(400, {"error": str(exc)[:200]})
            except Exception as exc:
                log.warning("request failed: %s", exc)
                return self._json(502, {"error": f"data source error: {str(exc)[:200]}"})

        def do_POST(self):
            self._json(405, {"error": "read-only"})

        do_PUT = do_DELETE = do_PATCH = do_POST

    return Handler


def serve(feed, host="127.0.0.1", port=8770, ready=None):
    if ipaddress.ip_address(host) not in ipaddress.ip_network("127.0.0.0/8"):
        raise SystemExit("Wave Lab binds to an IPv4 loopback address only")
    httpd = ThreadingHTTPServer((host, port), None)
    real = httpd.server_address[1]
    allowed = {f"{host}:{real}", f"localhost:{real}"}
    httpd.RequestHandlerClass = make_handler(WaveApi(feed), allowed)
    if ready:
        ready(httpd)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
