---
name: pionex-api
description: Use when you need Pionex exchange knowledge or public market data in this repo - fetching symbols, tickers, book ticker, depth, trades or klines (OHLCV, 1D/60M/5M), symbol rules (minimum order size, precision, tick), fees, rate limits, WebSocket streams, trading-bot products (grid, DCA, rebalancing), the official Pionex API docs or AI Kit CLI, or how paper order dry-run previews work. Read-only and paper only - covers our Python client (PionexPublic, MarketView) and the verified REST facts. Never for placing orders, keys, or private endpoints.
---

# Pionex API knowledge (public market data, paper only)

Verified live on 2026-10-14. Detailed material is in `references/`; load only the file you need.

## Hard limits (read first, no exceptions)

- Paper only. `config/mandate.v1.json` has `live_enabled=false`. Never edit the mandate or its lock, never raise limits, never add or call an order path. Never run `review-latch` (agent-prohibited).
- Public, unsigned, read-only requests only. No private or signed endpoint: nothing under `/api/v1/trade/`, `/account/`, `/wallet/`, `/bot/`, no private WebSocket (`wss://ws.pionex.com/ws`), no earn endpoints.
- Never open or print `.env*`, `var/account.json`, `var/account.db`, `~/.pionex/config.toml`, API keys or tokens. Never ask for or paste secrets. Paper trading needs none.
- Never run `pionex-ai-kit onboard|setup`, never register or install `@pionex/pionex-trade-mcp`, never run CLI `orders new|cancel`, `bot ...`, or `earn ...` writes. Order previews go through `pionex_lab/execution/dryrun.py` only.
- Paper results, backtests and synthetic or demo feed data are never evidence of profitability. Label proxy-venue (Binance) data as proxy.
- Do not exceed the lab request budget (5 weight/s, shared limiter); a 429 bans the IP for 60 s.

## Where to get data (decision table)

| Need | Use |
|---|---|
| Latest quote, spread | `PionexPublic().book_ticker("BTC_USDT")` (live) (`MarketView(...).latest_book(sym)` is stored data that stopped when the collector was retired on 2026-10-14) |
| Daily candles, any pair | `PionexPublic().klines(sym, "1D", end_time, 500)` and page backwards (Pionex 1D BTC/ETH starts 2017-10-26) |
| 5M / 60M candles BTC/ETH | recent: `PionexPublic().klines(sym, "60M", end_time, 500)` paged back (about 10,000 bars). `MarketView(Paths.default().market)` holds collected bars (5M 2026-08-26, 60M 2025-08-09) but the collector was retired on 2026-10-14, so it stops there |
| Longer 5M/60M history | `var/proxy_market.db` = Binance proxy, labelled and tracking-checked, never mixed into `market.db` |
| Symbol rules / min size / tick | `PionexPublic().symbols([...])` -> `SymbolRules`, or `MarketView.symbol_rules(sym)` |
| Order book depth | `client.depth(sym, 20)` (max 100); for 100+ use `client.get(...)` + `parse_depth` |
| Recent trades | `client.trades(sym, 100)` (max 100; REST allows 500), recent window only |
| 24h stats | `client.get("/api/v1/market/tickers", {"symbol": sym})` (not wrapped) |
| Streaming | public WebSocket, see `references/websocket.md` (the lab itself polls REST) |
| Order request shape | `dryrun.build_order_request(...)` / `dryrun.preview(...)`, see `references/order-previews.md` |

## Python usage (run from the repo root with `py`)

```python
import sys; sys.path.insert(0, ".")
from pionex_lab.exchange.pionex_public import PionexPublic
c = PionexPublic()                                  # https://api.pionex.com, 5 weight/s limiter
rules, _ = c.symbols(["BTC_USDT"]); r = rules[0]    # r.min_amount, r.price_step, r.quantity_step, r.enabled
bt, env  = c.book_ticker("BTC_USDT")                # bt.bid, bt.ask, bt.spread_bps; env.server_ts
bars, _  = c.klines("BTC_USDT", "1D", limit=30)     # ascending list[Kline]; Decimal OHLCV
closed   = [b for b in bars if b.open_time + 86_400_000 <= env.server_ts]   # drop in-progress bar
```

Every wrapper returns `(parsed, Envelope)`. Prices and sizes are `Decimal`. Exchange errors raise `ExchangeError` (`.code`), schema surprises `SchemaError`, HTTP 418/429 `RateLimited`. Full API, stores and the proxy venue: `references/python-client.md`.

## Public REST cheat sheet

Base `https://api.pionex.com`, GET, no auth, no timestamp. Responses are `{"result": true, "data": ..., "timestamp": <server ms>}`; failures are HTTP 200 with `{"result": false, "code": ..., "message": ...}`.

| URL | Key params | Limits |
|---|---|---|
| `/api/v1/common/symbols` | `symbols=A,B` (plural!) or `type=SPOT\|PERP` | weight 5; 413 spot symbols, 342 enabled |
| `/api/v1/market/bookTickers` | `symbol` or `type=SPOT\|PERP` | no params = PERP |
| `/api/v1/market/tickers` | `symbol` or `type` | no params = SPOT (24h rolling) |
| `/api/v1/market/depth` | `symbol`, `limit` | 1 to 1000, default 20 |
| `/api/v1/market/trades` | `symbol`, `limit` | up to 500, default 100, newest first |
| `/api/v1/market/klines` | `symbol`, `interval`, `endTime` ms (inclusive), `limit` | limit 1 to 500 (default 100); ~10,000 bars of history |

Symbols are `BASE_QUOTE` upper case (`BTC_USDT`, `ETH_USDT`); perpetuals `BTC_USDT_PERP`. Kline intervals, exact strings: `1M 5M 15M 30M 60M 4H 8H 12H 1D` (`1M` is one MINUTE; hourly is `60M`; no `1W`). Raw klines are newest first; `time` is the bar open (UTC aligned); the newest bar is still forming. Page back with `endTime = oldest_open_time - 1`. Beyond ~10,000 bars: `MARKET_INVALID_TIME` (about 34.7 days of 5M, 416 days of 60M; 1D unaffected). Details and exact response fields: `references/rest-market-data.md`.

## Fees, minimum sizes, precision (summary)

- Fees [official fee page, read in a browser 2026-10-14]: spot maker 0.050% / taker 0.050% (0.10% round trip), futures maker 0.020% / taker 0.050%, leveraged tokens 0.100%; bots add no fee beyond trading fees [secondary]; VIP tiers can lower them (current table unread). The lab assumes 5 bps per side (`assumed_spot_fee_per_side_for_research_only`), `verified_fee_source` is still null. Always add spread and impact, and stress costs 2x.
- Symbol rules come from `/common/symbols`, never hard-code: `basePrecision` = quantity decimals, `quotePrecision` = price decimals, `minAmount` = minimum quote notional (10 USDT on 300 of 324 enabled USDT pairs; 5 or 1 on a few), `minTradeSize`/`maxTradeSize` for LIMIT, `minTradeDumping`/`maxTradeDumping` for MARKET sell, `enable` must be true. BTC_USDT: size step 0.000001, tick 0.01, minimum 10 USDT notional, `buyCeiling` 1.1 / `sellFloor` 0.9.
- Rate limit: 10 weight/s per IP (public) and per account (private); over it, HTTP 429 and a 60 s ban, +10 s per request while ignoring it. Lab budget 5/s with 1 reserved for exits.

More: `references/fees-sizes-limits.md`.

## Order previews (dry-run only)

An order in this repo is a validated request body plus a simulated fill. `dryrun.build_order_request(rules, side, type_, client_order_id, size=, price=, amount=)` renders the exact body of `POST /api/v1/trade/order` (`"sent": False`) and enforces precision, minimum size, notional and field-combination rules (LIMIT = size+price, MARKET BUY = amount, MARKET SELL = size). `dryrun.preview(rules, cli, **order)` also cross-checks against the pinned official CLI's `--dry-run` output (run with `--read-only`, empty HOME, no `PIONEX*` env) and rejects on mismatch. Fills are simulated by `execution/paper.py` against quotes observed at least 250 ms after submission, depth-limited, fee on both sides. See `references/order-previews.md`.

## Bots (research context only)

Pionex bots: spot grid (arithmetic/geometric), infinity grid, futures grid, DCA (martingale), rebalancing, smart copy, signal, arbitrage, and more. Bot API exists only for spot grid, futures grid, smart copy, signal (all private/signed); no DCA or rebalancing API found. Minimum investments are set per product (`checkParams` / order panel). The lab has no bot path; model grids on candles only, labelled as models. See `references/bots-and-products.md`.

## Official docs and toolkit

- API docs (index with raw Markdown pages): https://pionex-doc.gitbook.io/apidocs/llms.txt ; newer site https://www.pionex.com/docs/api-docs ; OpenAPI specs https://github.com/pionex-official/pionex-open-api
- Official AI Kit (CLI + MCP + skills): https://github.com/pionex-official/pionex-ai-kit ; pinned CLI 0.2.55 at `tools/pionex-cli/` (public `market` commands and `--dry-run` previews only)
- Fees page https://www.pionex.com/en/fees and the support center return HTTP 403 to automated fetch; open them in a browser tool.
- Full link list and doc errors found by testing: `references/official-docs.md`; AI Kit and CLI usage: `references/ai-kit-cli.md`.

## Gotchas that cost time

1. `symbols=` is plural; the doc's singular `symbol=` is ignored and returns every symbol.
2. The newest kline is in progress. Do not feed it to a signal; drop it or use `complete_only=True` bars.
3. `PionexPublic.depth()` and `.trades()` refuse limit > 100, stricter than the exchange.
4. `parse_symbols` is SPOT-shaped; do not feed it PERP symbol rows.
5. `bookTickers` with no params returns PERP, `tickers` with no params returns SPOT. The tickers endpoints list only 330 currently trading pairs, `symbols` lists 413 including disabled ones.
6. All values are strings. Use `Decimal`; compare against steps with exact arithmetic.
7. Pionex 5M history is capped (~35 days); do not silently substitute Binance data. Use the labelled proxy store.
8. The client weights every call 1.0, but `/common/symbols` is weight 5 per the docs.
9. Run the unit tests before any commit: `py -m unittest discover -s tests` and `py -m unittest discover -s .claude/skills/pionex-trading-lab/scripts -p "test_*.py"`.

## References

| File | Contents |
|---|---|
| `references/rest-market-data.md` | Each public endpoint: params, exact response fields, limits (doc vs observed), kline semantics, errors |
| `references/python-client.md` | `PionexPublic`, parsers, limiter, collector, `MarketView`, proxy venue, local data inventory, code examples |
| `references/fees-sizes-limits.md` | Fees with confidence tags, min sizes, precision semantics, rate limits |
| `references/websocket.md` | Public streams, protocol, heartbeat, observed behaviour, Node example |
| `references/bots-and-products.md` | Bot products, Bot API facts, minimum investments, how they relate to the lab |
| `references/order-previews.md` | Order shape, dry-run validator and error codes, paper fills, forbidden actions |
| `references/ai-kit-cli.md` | Official AI Kit, CLI syntax, safe invocation, tool inventory |
| `references/official-docs.md` | All official links, fetch status, documentation errors |
| `references/verification-2026-10-14.md` | What was checked live, remaining gaps, re-check snippet |

Related skill: `pionex-trading-lab` (mandate, risk, research protocol). Human-readable summary: `docs/PIONEX.md`.
