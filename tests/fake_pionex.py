"""Local fake of the public Pionex REST endpoints, for tests ONLY.

Serves deterministic SYNTHETIC prices in the documented response shapes, using a
shared clock so tests can drive time. Nothing here is market data. Reports built
from it are labeled "TEST FEED ... not Pionex market data" by the exporter.
"""
from __future__ import annotations

import json
import math
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

INTERVALS = {"1M": 60_000, "5M": 300_000, "15M": 900_000, "30M": 1_800_000, "60M": 3_600_000}
BASE = {"BTC_USDT": 60000.0, "ETH_USDT": 3000.0, "USDC_USDT": 1.0}
RULES = {
    "BTC_USDT": {"basePrecision": 6, "quotePrecision": 2, "amountPrecision": 2, "minAmount": "10",
                 "minTradeSize": "0.000001", "maxTradeSize": "1000", "minTradeDumping": "0.000001",
                 "maxTradeDumping": "1000"},
    "ETH_USDT": {"basePrecision": 4, "quotePrecision": 2, "amountPrecision": 2, "minAmount": "10",
                 "minTradeSize": "0.0001", "maxTradeSize": "10000", "minTradeDumping": "0.0001",
                 "maxTradeDumping": "10000"},
    "USDC_USDT": {"basePrecision": 2, "quotePrecision": 4, "amountPrecision": 2, "minAmount": "10",
                  "minTradeSize": "1", "maxTradeSize": "1000000", "minTradeDumping": "1",
                  "maxTradeDumping": "1000000"},
}


def default_path(symbol: str, t_ms: int) -> float:
    if symbol == "USDC_USDT":
        return 1.0
    b = BASE[symbol]
    phase = 0.0 if symbol == "BTC_USDT" else 1.3
    x = t_ms / 1000.0
    return b * (1 + 0.02 * math.sin(2 * math.pi * x / 21600 + phase) + 0.004 * math.sin(2 * math.pi * x / 2220)
                + 0.0015 * math.sin(2 * math.pi * x / 380 + phase))


class FakePionex:
    def __init__(self, now_ms, price_fn=default_path, spread_bps=1.0):
        self.now_ms = now_ms
        self.price = price_fn
        self.spread_bps = spread_bps
        self.mode = "ok"            # "ok" | "429" | "malformed" | "down"
        self.history_limit_bars = None  # mimic Pionex rejecting old endTime (MARKET_INVALID_TIME)
        self.requests = []
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()

    # ------------------------------------------------------------ data
    def bar(self, symbol, interval, open_time, now):
        step = INTERVALS[interval]
        end = min(open_time + step, now)
        pts = [self.price(symbol, open_time + k * (end - open_time) // 12) for k in range(13)]
        vol = 5 + 3 * math.sin(open_time / 7_777_777) + (open_time // step) % 7
        return {"time": open_time, "open": f"{pts[0]:.2f}", "close": f"{pts[-1]:.2f}",
                "high": f"{max(pts):.2f}", "low": f"{min(pts):.2f}", "volume": f"{vol:.4f}"}

    def book(self, symbol, now):
        mid = self.price(symbol, now)
        half = mid * self.spread_bps / 2e4
        prec = RULES[symbol]["quotePrecision"]
        bid, ask = round(mid - half, prec), round(mid + half, prec)
        if ask <= bid:
            ask = round(bid + 10 ** -prec, prec)
        return bid, ask, prec

    def _handler(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, obj, headers=None):
                body = json.dumps(obj).encode() if not isinstance(obj, bytes) else obj
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802
                u = urllib.parse.urlparse(self.path)
                q = dict(urllib.parse.parse_qsl(u.query))
                fake.requests.append((u.path, q))
                now = fake.now_ms()
                if fake.mode == "429":
                    return self._send(429, {"result": False, "code": "TOO_MANY"}, {"Retry-After": "7"})
                if fake.mode == "down":
                    return self._send(503, {"result": False})
                if fake.mode == "malformed":
                    return self._send(200, b'{"result": true, "data": {"tickers": [{"symbol": 1}]}}')
                env = lambda data: {"result": True, "data": data, "timestamp": now}  # noqa: E731
                if u.path == "/api/v1/common/symbols":
                    syms = q.get("symbols", ",".join(RULES)).split(",")
                    return self._send(200, env({"symbols": [
                        {"symbol": s, "type": "SPOT", "baseCurrency": s.split("_")[0], "quoteCurrency": "USDT",
                         "enable": True, **RULES[s]} for s in syms if s in RULES]}))
                sym = q.get("symbol")
                if sym not in RULES:
                    return self._send(200, {"result": False, "code": "INVALID_SYMBOL", "message": "bad symbol"})
                if u.path == "/api/v1/market/bookTickers":
                    bid, ask, prec = fake.book(sym, now)
                    return self._send(200, env({"tickers": [{"symbol": sym, "bidPrice": f"{bid:.{prec}f}",
                                                             "bidSize": "0.5", "askPrice": f"{ask:.{prec}f}",
                                                             "askSize": "0.5", "timestamp": now}]}))
                if u.path == "/api/v1/market/depth":
                    bid, ask, prec = fake.book(sym, now)
                    n = int(q.get("limit", 5))
                    tick = 10 ** -prec * max(1, int(fake.price(sym, now) * 1e-5 / 10 ** -prec))
                    bids = [[f"{bid - k * tick:.{prec}f}", "0.4"] for k in range(n)]
                    asks = [[f"{ask + k * tick:.{prec}f}", "0.4"] for k in range(n)]
                    return self._send(200, env({"bids": bids, "asks": asks, "updateTime": now}))
                if u.path == "/api/v1/market/klines":
                    step = INTERVALS[q["interval"]]
                    lim = fake.history_limit_bars
                    if lim and "endTime" in q and int(q["endTime"]) < now - lim * step:
                        return self._send(200, {"result": False, "code": "MARKET_INVALID_TIME",
                                                "message": "endTime param error"})
                    end = min(int(q.get("endTime", now)), now)
                    limit = int(q.get("limit", 100))
                    last_open = (end // step) * step
                    opens = [last_open - k * step for k in range(limit)][::-1]
                    return self._send(200, env({"klines": [fake.bar(sym, q["interval"], t, now)
                                                           for t in opens if t >= 0]}))
                if u.path == "/api/v1/market/trades":
                    bid, ask, prec = fake.book(sym, now)
                    return self._send(200, env({"trades": [{"symbol": sym, "tradeId": str(now), "price": f"{ask}",
                                                            "size": "0.01", "side": "BUY", "timestamp": now}]}))
                return self._send(404, {"result": False, "code": "NOT_FOUND"})

        return H
