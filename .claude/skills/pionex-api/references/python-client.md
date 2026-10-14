# Our Python data layer (Windows: run with `py`, from the repo root)

Standard library only. Everything here is read-only: no signing, no credentials, no order endpoint.

## `pionex_lab/exchange/pionex_public.py`

```python
from pionex_lab.exchange.pionex_public import PionexPublic, KLINE_INTERVALS, ExchangeError, SchemaError
from pionex_lab.exchange.ratelimit import RateLimited
client = PionexPublic()          # base https://api.pionex.com, 5 weight/s shared limiter, 10 s timeout
```

Every wrapper returns `(parsed, envelope)`. `Envelope` has `.data` (raw), `.server_ts`, `.sent_ms`, `.recv_ms`, `.endpoint`, `.latency_ms`, `.skew_ms`.

| Call | Returns | Client-side limit |
|---|---|---|
| `client.symbols(["BTC_USDT","ETH_USDT"])` or `client.symbols(None, "SPOT")` | `list[SymbolRules]` | `type_` is sent as `type`; SPOT rows only |
| `client.book_ticker("BTC_USDT")` | `BookTicker` (`bid, bid_size, ask, ask_size, exchange_ts, mid, spread_bps`) | one symbol; rejects crossed/locked book |
| `client.depth("BTC_USDT", 20)` | `Depth` (`bids`, `asks` as tuples of `(Decimal price, Decimal size)`, `update_ts`) | `limit` 1 to 100 (exchange allows ~1000) |
| `client.klines("BTC_USDT", "1D", end_time=None, limit=500)` | `list[Kline]` ascending (`open_time, open, high, low, close, volume`, all `Decimal` except time) | `limit` 1 to 500, interval in `KLINE_INTERVALS` |
| `client.trades("BTC_USDT", 100)` | `list[Trade]` (`trade_id, price, size, side, ts`) | `limit` 1 to 100 (exchange allows 500) |
| `client.get(path, params, weight=1.0, priority="normal")` | `Envelope` | any public path; you parse `env.data` yourself |

Not wrapped: 24h `tickers`, PERP symbols, REST depth above 100, trades above 100. Use `client.get` for those:

```python
env = client.get("/api/v1/market/tickers", {"symbol": "BTC_USDT"}, weight=1)
row = env.data["tickers"][0]                      # strings; row["count"] is an int

from pionex_lab.exchange.pionex_public import parse_depth
env = client.get("/api/v1/market/depth", {"symbol": "BTC_USDT", "limit": 500})
book = parse_depth(env.data)                      # validates ordering, returns Depth
```

Parsers are strict and raise `SchemaError` (an `ExchangeError`) on anything unexpected, including crossed books and inconsistent OHLC. `client.get` raises `RateLimited` (with `retry_after_s`) on HTTP 418/429 and bans all traffic from that client until the pause ends. Exchange-level failures raise `ExchangeError` with `.code` (for example `MARKET_INVALID_TIME`).

Known gap: the wrappers call `get(..., weight=1.0)` for every endpoint, but the docs give `/api/v1/common/symbols` weight 5. Harmless at one call per hour (the collector), but pass `weight=5` if you call it in a loop through `client.get`.

`SymbolRules` fields: `symbol, type, base, quote, enabled, base_precision, quote_precision, min_amount, min_trade_size, max_trade_size, min_dump_size, max_dump_size, raw`, plus `quantity_step`, `price_step` (from `step_from_precision`) and `complete()` -> `(ok, missing_fields)`.

Minimal end-to-end example (public data only):

```python
import sys; sys.path.insert(0, ".")        # when running a script from the repo root
from pionex_lab.exchange.pionex_public import PionexPublic
c = PionexPublic()
rules, _ = c.symbols(["BTC_USDT"]);   r = rules[0]
bt, env  = c.book_ticker("BTC_USDT")
bars, _  = c.klines("BTC_USDT", "1D", limit=30)
done     = [b for b in bars if b.open_time + 86_400_000 <= env.server_ts]   # drop the in-progress bar
print(r.min_amount, r.price_step, bt.bid, bt.ask, float(bt.spread_bps), done[-1].open_time)
```

Page backwards through klines (the collector's `backfill` does this with a stop on `MARKET_INVALID_TIME`):

```python
end = None; out = []
while True:
    kl, _ = c.klines("BTC_USDT", "1D", end_time=end, limit=500)
    if not kl: break
    out = kl + out
    end = kl[0].open_time - 1            # endTime is inclusive
    if len(kl) < 500: break
```

## Rate limiter (`pionex_lab/exchange/ratelimit.py`)

`WeightedLimiter(rate_per_s=5.0)`: token bucket, 1 token/weight unit, 1.0 reserved for `priority="exit"`. `acquire()` sleeps up to 30 s then raises `RateLimited`. `ban(retry_after_s)` records a server ban (default bounded jittered backoff). The mandate sets the local budget at 5 weight/s (`rest_weight_per_second_local_budget`) against the exchange's 10/s per IP. Do not raise it, and do not run a second ad-hoc client in a tight loop while the collector runs (they share the IP budget but not the limiter).

## Collector and stores

- `pionex_lab/data/collector.py` `Collector`: the only process that polls Pionex in paper mode. It refreshes symbols (hourly), book tickers (1 s), depth (3 s, 20 levels), klines (20 s) for `config/runtime.json` `research_universe` (BTC_USDT, ETH_USDT) on `bar_intervals` (5M, 60M), plus `USDC_USDT` depeg monitoring. Run via `py -m pionex_lab collect` (or `run` for collector + paper engine + dashboard).
- `pionex_lab/data/store.py`: SQLite in `var/market.db` (git-ignored). Prices are stored as exact decimal strings.
- `MarketView(path, readonly=True)` (read access, use this) methods: `latest_book(symbol, at_or_before=None)`, `first_book_after(symbol, after_ms)`, `depth_near(symbol, after_ms, at_or_before)`, `bars(symbol, interval, limit=None, end_ms=None, start_ms=None, complete_only=True)` -> `Bars` (parallel float lists `t,o,h,l,c,v`, plus `.slice()`), `symbol_rules(symbol)` -> `(SymbolRules, fetched_at)`, `status(key)`, `median_spread_bps(symbol, since_ms)`, `fetch_errors(since_ms)`. `resample(bars, "4H")` builds coarser bars. Only the collector uses `MarketStore` (write).

```python
from pionex_lab.data.store import MarketView
from pionex_lab.paths import Paths
mv = MarketView(Paths.default().market)               # var/market.db, read-only
b = mv.bars("BTC_USDT", "60M", limit=500)             # completed bars only
tick = mv.latest_book("BTC_USDT")                     # dict of Decimals, with fetched_at
rules, fetched_at = mv.symbol_rules("BTC_USDT")
```

Snapshot on 2026-10-14 (re-query, it grows): `var/market.db` holds BTC_USDT and ETH_USDT 5M (since 2026-08-26) and 60M (since 2025-08-09), about 97,800 book ticks and 55,600 depth snapshots.

## Proxy venue (NOT Pionex)

`pionex_lab/data/proxy.py` downloads Binance public archives (`data.binance.vision`, checksum verified, no key) into a SEPARATE `var/proxy_market.db` (`Paths.default().proxy_market`) because Pionex only serves ~10,000 bars per interval. Snapshot 2026-10-14: 1D for BTC, ETH, SOL, XRP, DOGE, LINK, ADA, BNB, AVAX, LTC (back to 2017 to 2020), 5M and 60M for BTC/ETH since 2022-10-01, PERP 60M since 2023-04-01, funding rates and futures metrics tables. Rules: label every result that uses it as proxy-venue, never write it into `market.db`, and use `tracking_check` before trusting it (median close difference at most 5 bps, return correlation at least 0.95, at least 2,000 overlapping bars). Refresh with `py -m pionex_lab fetch-proxy`.

Pionex itself has deep daily history (BTC_USDT and ETH_USDT 1D from 2017-10-26), so for DAILY research you can pull Pionex directly with the paging loop above; 5M/60M beyond ~35/416 days need the proxy.

## Other consumers of `PionexPublic`

`pionex_lab/waves/feeds.py` (`PionexFeed`, `StoreFeed`, `DemoFeed`; DemoFeed is synthetic, never data), `swing/guidance.py`, `swing/swing_book.py`, `waves/alerts.py`, `cli.py capability` (probes public endpoints and writes fixtures under `var/capability/`).

## Commands

- `py -m pionex_lab status` shows state, feeds and latches. `py -m pionex_lab capability` probes the public endpoints.
- Tests before any commit: `py -m unittest discover -s tests` and `py -m unittest discover -s .claude/skills/pionex-trading-lab/scripts -p "test_*.py"`.
- Do not open `var/account.json`, `var/account.db`, any `.env*`, or `~/.pionex/config.toml`. They are private account or secret data.
