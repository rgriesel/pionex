# What was verified on 2026-10-14, and what was not

All calls were public, read-only GETs (and one public WebSocket subscription) from Windows via `PionexPublic`, the pinned CLI with an empty HOME, and Node. No key, signature, private endpoint or order was used. Roughly 100 requests in total, no 429.

## Verified live

| Check | Result |
|---|---|
| `symbols?symbols=BTC_USDT` | 1 SPOT row with the exact fields listed in `rest-market-data.md`; every limit field present, `SymbolRules.complete()` true |
| `symbols?type=SPOT` | 413 rows, 342 enabled, quotes BTC/ETH/USDC/USDT, 391 USDT-quoted |
| `symbols?type=PERP` | 609 rows, different field set (`status`, `baseStep`, `quoteStep`, `minSizeLimit`, ...) |
| `symbols?symbol=BTC_USDT` (singular, as in the doc example) | parameter ignored, all 413 spot symbols returned |
| `bookTickers?symbol=BTC_USDT` | `{"tickers":[{symbol,bidPrice,bidSize,askPrice,askSize,timestamp}]}`, all prices strings; spread 1 tick |
| `bookTickers?type=SPOT` / no params | 330 rows / 607 rows (PERP default) |
| `tickers?symbol=BTC_USDT` | fields `symbol,time,open,close,high,low,volume,amount,count` (`count` is a number) |
| `tickers` no params / `type=SPOT` | 330 rows both (SPOT default) |
| `klines` 1D BTC_USDT | fields `time,open,close,high,low,volume`; newest first; time = 00:00 UTC; newest bar in progress (close changed between calls) |
| `klines` limit | 500 OK; 501 and 1000 -> `MARKET_PARAMETER_ERROR` "limit error" |
| `klines` intervals | `1M 5M 15M 30M 60M 4H 8H 12H 1D` accepted with the right step; `1W`, `3D` -> "interval param error" |
| `klines` endTime | inclusive (bar with open time == endTime returned; `endTime = T-1` returns older bars) |
| `klines` history | 60M: 9,900 bars back OK, 10,100 -> `MARKET_INVALID_TIME`; 1M: 8,640 OK, 11,520 rejected; 1D BTC/ETH from 2017-10-26, paged 1,500 bars without a problem |
| `depth` | default 20 per side; limit 100 -> 100; 101 -> 101; 1000 -> 999; entries `[price,size]` strings; `updateTime` present |
| `trades` | default 100; limits 5, 9, 10, 100, 101, 500 OK; 501 rejected; fields `symbol,tradeId,price,size,side,timestamp`; newest first |
| Errors | unknown symbol -> `MARKET_INVALID_SYMBOL`; unknown symbol in `symbols=` -> `MARKET_PARAMETER_ERROR` "symbol error"; delivered as HTTP 200 with `result:false` |
| WebSocket `wss://ws.pionex.com/wsPub` | SUBSCRIBED acks for TRADE and DEPTH(limit 5); binary frames with UTF-8 JSON; DEPTH full snapshots ~every 0.6 s; TRADE batches; PING at ~16 s answered with PONG; clean close |
| Pinned CLI v0.2.55 | `market klines|book_tickers|symbols|depth|trades|tickers` work with empty HOME and `--read-only`; `capabilities` works offline; `orders new ... --dry-run` prints `{tool, args}` and sends nothing |
| Our dry-run | `build_order_request` and `preview` (CLI cross-check) produced identical `args` for a BTC_USDT LIMIT BUY; four rejection codes reproduced |
| Documented code examples | The snippets in `python-client.md` were executed against live data and work |

## Not verified (gaps)

- Fees: the official fee page and the support center returned HTTP 403 to the fetch tool. 0.05% spot and 0.02%/0.05% futures come from Pionex blog posts and search summaries; the current VIP table (effective 2025-11-01) was not read. Fee asset convention on real fills is unverified (needs a private fills record).
- Bot minimum investments (DCA, rebalancing, grids) are from old or marketing pages; `checkParams` (private) is the real source.
- Endpoint weights other than `symbols` = 5 are inferred from the docs ("1"); no rate-limit headers exist to confirm. The ban duration (60 s) was not tested, deliberately.
- 4H/8H/12H bar alignment (UTC anchor) was not checked; only the step sizes and 1D alignment.
- WebSocket: the per-connection topic limit, behaviour after a missed PONG, and whether DEPTH pushes continue without changes were not tested. Private streams were not touched.
- Private API behaviour (permissions, order rejects, fills, balances, bots) was not and must not be tested here.

## Re-check snippet (public only)

```python
import sys; sys.path.insert(0, ".")
from pionex_lab.exchange.pionex_public import PionexPublic, ExchangeError
c = PionexPublic()
def code(path, **p):
    try: c.get(path, p); return "ok"
    except ExchangeError as e: return e.code
print("klines 500/501:", code("/api/v1/market/klines", symbol="BTC_USDT", interval="1D", limit=500),
      code("/api/v1/market/klines", symbol="BTC_USDT", interval="1D", limit=501))
print("1W:", code("/api/v1/market/klines", symbol="BTC_USDT", interval="1W"))
print("depth 1000:", len(c.get("/api/v1/market/depth", {"symbol": "BTC_USDT", "limit": 1000}).data["bids"]))
print("trades 500/501:", code("/api/v1/market/trades", symbol="BTC_USDT", limit=500),
      code("/api/v1/market/trades", symbol="BTC_USDT", limit=501))
print("spot symbols:", len(c.symbols(None, "SPOT")[0]))
```
