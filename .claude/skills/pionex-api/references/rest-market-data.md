# Pionex public REST market data (verified 2026-10-14)

Base URL: `https://api.pionex.com`. All endpoints below are public: GET, no key, no signature, no `timestamp` parameter.
Official page for each endpoint: see `official-docs.md`. "Doc" = what the official docs say; "Observed" = what a live call returned on 2026-10-14.

## Envelope

Every response is JSON:

```json
{"result": true, "data": {...}, "timestamp": 1792010714134}
```

- `timestamp` is the server time in ms (use it as the clock reference; there is no separate time endpoint in the docs).
- Failure: `{"result": false, "code": "MARKET_PARAMETER_ERROR", "message": "limit error", "timestamp": ...}`. Observed on HTTP 200, so check `result`, not the HTTP status. Our client turns this into `ExchangeError` with `.code`.
- Seen codes: `MARKET_INVALID_SYMBOL` ("symbol error"), `MARKET_PARAMETER_ERROR` ("limit error", "interval param error", "symbol error"), `MARKET_INVALID_TIME` ("endTime param error": kline history limit, see below).
- Numbers are strings (`"81752.00"`), except `timestamp`/`time`/`count` which are JSON numbers. Parse with `Decimal`, never `float`, for prices and sizes.

## Symbol naming

- Spot: `BASE_QUOTE`, upper case, e.g. `BTC_USDT`, `ETH_USDT`, `USDC_USDT`, `AAVE_ETH`. Quotes seen: USDT, USDC, BTC, ETH. 413 spot symbols listed, 342 enabled, 391 with USDT quote (2026-10-14).
- Perpetual futures: `BTC_USDT_PERP` (two underscores). The lab's Wave Lab symbol regex `^[A-Z0-9]{1,20}_[A-Z0-9]{1,10}$` rejects these.
- `baseCurrency` can differ from the symbol prefix (`0G_USDT_PERP` has base `ZEROG`). Always read `symbol`, do not rebuild it.
- Tokenized stocks exist as spot (`AAPLX_USDT`). The lab universe excludes derivatives, leveraged tokens and thin markets (see `pionex-trading-lab/references/research.md`).

## Endpoints

| Endpoint | Weight (doc) | Params | Notes |
|---|---|---|---|
| `GET /api/v1/common/symbols` | 5 | `symbols` (csv, plural) or `type=SPOT\|PERP` | Trading rules. Default SPOT. |
| `GET /api/v1/market/bookTickers` | 1 | `symbol` or `type=SPOT\|PERP` | Best bid/ask. With no params returns PERP (observed 607 rows). |
| `GET /api/v1/market/tickers` | 1 | `symbol` or `type` | 24h stats. With no params returns SPOT (observed 330 rows). |
| `GET /api/v1/market/depth` | 1 | `symbol` (req), `limit` | Default 20. |
| `GET /api/v1/market/trades` | 1 | `symbol` (req), `limit` | Default 100. Newest first. |
| `GET /api/v1/market/klines` | 1 | `symbol`, `interval` (req), `endTime`, `limit` | Default limit 100, max 500. |

### symbols

`GET /api/v1/common/symbols?symbols=BTC_USDT` (use the plural `symbols`; the doc example's singular `symbol=` is silently ignored and returns every spot symbol).

Observed SPOT row, exact fields:

```json
{"symbol":"BTC_USDT","type":"SPOT","baseCurrency":"BTC","quoteCurrency":"USDT","basePrecision":6,"quotePrecision":2,
 "amountPrecision":8,"minAmount":"10","minTradeSize":"0.000001","maxTradeSize":"1000","minTradeDumping":"0.000001",
 "maxTradeDumping":"100","enable":true,"buyCeiling":"1.1","sellFloor":"0.9"}
```

Field meaning (see `fees-sizes-limits.md` for use): `basePrecision` = decimals of the BASE quantity (size step), `quotePrecision` = decimals of the price (tick), `amountPrecision` = decimals of the quote `amount` of a market buy, `minAmount` = minimum quote notional, `minTradeSize`/`maxTradeSize` = LIMIT size range (base), `minTradeDumping`/`maxTradeDumping` = MARKET SELL size range (base), `enable` = tradable (boolean), `buyCeiling`/`sellFloor` = price band ratios.

An unknown symbol in `symbols=` returns `MARKET_PARAMETER_ERROR` ("symbol error").

PERP rows (`type=PERP`, 609 seen) have a different shape: `name`, `minNotional`, `baseStep`, `quoteStep`, `minSizeLimit`, `maxSizeLimit`, `maxImpactLimit`, `minSizeMarket`, `maxSizeMarket`, `maxImpactMarket`, `maxOrderNum`, `status` ("TRADING"), `liquidationFeeRate`. `parse_symbols` in our client is SPOT-shaped: it requires boolean `enable` and does not parse PERP rows.

### bookTickers

```json
{"tickers":[{"symbol":"BTC_USDT","bidPrice":"81752.00","bidSize":"11.069400","askPrice":"81752.01","askSize":"16.599004","timestamp":1792010715643}]}
```

Observed spread on BTC_USDT: 1 tick (0.001 bp). `type=SPOT` returns 330 rows (only currently trading pairs, fewer than the 413 listed by `symbols`).

### tickers (24h)

```json
{"tickers":[{"symbol":"BTC_USDT","time":1792010731598,"open":"83370.22","close":"81721.04","high":"84146.72","low":"81517.59","volume":"32522.667256","amount":"2692299368.94379044","count":448009}]}
```

`volume` is base units, `amount` is quote value (USDT), `count` is the trade count (a JSON number although the doc says string). `open` did not equal the UTC 1D bar open (83370.22 vs 83169.01 at the same moment), consistent with a rolling 24h window; use klines for UTC-day values. Doc warns about calling with no symbol ("Careful").

### depth

`GET /api/v1/market/depth?symbol=BTC_USDT&limit=5`

```json
{"bids":[["81730.15","7.158131"],["81730.14","0.001469"]],"asks":[["81730.16","12.387163"],["81730.17","0.003874"]],"updateTime":1792010725479}
```

- Entries are `[price, size]` strings. Bids descending, asks ascending. `updateTime` ms.
- Doc: limit 1 to 1000, default 20 (change log 2022-11-24 raised the cap to 1000). Observed: 100 -> 100 levels per side, 101 -> 101, 1000 -> 999 per side, default -> 20.
- Our `PionexPublic.depth()` refuses `limit > 100`; for more use `client.get(...)` + `parse_depth(env.data)` (see `python-client.md`). The official CLI and the WebSocket DEPTH topic are capped at 100.

### trades

`GET /api/v1/market/trades?symbol=BTC_USDT&limit=3`, newest first:

```json
{"trades":[{"symbol":"BTC_USDT","tradeId":"320000000879812895","price":"81730.01","size":"0.038710","side":"BUY","timestamp":1792010727580}]}
```

- `side` is the taker's direction. `timestamp` is ms (a number, doc says string).
- Doc: limit 10 to 500, default 100. Observed: 5, 9, 10, 100, 101, 500 all worked; 501 -> `MARKET_PARAMETER_ERROR`. This is a recent-trades window only, not history (no `startTime`/`fromId`).
- Our `PionexPublic.trades()` refuses `limit > 100`.

### klines

`GET /api/v1/market/klines?symbol=BTC_USDT&interval=1D&limit=2`

```json
{"klines":[{"time":1791936000000,"open":"83169.01","close":"81752.01","high":"84146.72","low":"81517.59","volume":"30021.059133"},
           {"time":1791849600000,"open":"81850.01","close":"83169.01","high":"84168.00","low":"81034.32","volume":"30806.795376"}]}
```

- Raw order is NEWEST FIRST. `PionexPublic.klines()` returns them sorted ascending by `open_time`.
- `time` is the bar OPEN time in ms. Bars are UTC-aligned (1D opens at 00:00 UTC; verified).
- `volume` is base-asset volume. There is no quote volume or trade count in a kline.
- The newest bar is the bar in progress (partial OHLCV) whenever `time + interval > server time`. Verified: the 1D bar at 2026-10-14 00:00 UTC changed `close` between two calls. Drop it before computing signals; `MarketStore.upsert_klines` flags it `complete=0` and `MarketView.bars()` returns complete bars only by default.
- Intervals (exact strings): `1M, 5M, 15M, 30M, 60M, 4H, 8H, 12H, 1D`. `1W`, `3D` and any other value return `MARKET_PARAMETER_ERROR` ("interval param error"). Note `1M` means ONE MINUTE, not one month; hourly is `60M`.
- `limit`: 1 to 500, default 100. 501 and 1000 are rejected with `MARKET_PARAMETER_ERROR` ("limit error").
- `endTime` (ms) is INCLUSIVE: a bar whose open time equals `endTime` is returned. To page backwards, set `endTime = oldest_open_time - 1`.
- History reach: at most ~10,000 bars before "now". `endTime` older than that returns `MARKET_INVALID_TIME`. Observed: 60M, 9,900 bars back OK, 10,100 bars back rejected; 1M, 8,640 bars back OK, 11,520 rejected. So ~416 days of 60M, ~34.7 days of 5M, ~6.9 days of 1M. The 10,000-bar limit does not bind on 1D: BTC_USDT and ETH_USDT 1D start 2017-10-26 (verified by paging back); SOL_USDT is empty before its later listing.
- For long 5M/60M history the lab uses a labelled Binance proxy (`python-client.md`), never mixed with Pionex data.

## Time and clock skew

Use the envelope `timestamp` as server time. `Envelope.skew_ms` = server minus local midpoint of the request (positive: server ahead). First request after process start is slow (TLS, about 1 s); do not read that as skew.
