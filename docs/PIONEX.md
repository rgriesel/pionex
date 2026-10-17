# Pionex reference (for people)

Checked and tested live on 2026-10-14. Agents use the same facts through the skill `.claude/skills/pionex-api/SKILL.md` (long versions in its `references/`). This lab is paper only: it reads public market data and renders order previews; it never sends orders and never touches keys.

## Official sources

- API docs (REST + WebSocket): https://pionex-doc.gitbook.io/apidocs (page index: `/llms.txt`; append `.md` to any page for raw Markdown)
- Newer docs site (Trade, Wallet, Bot, Earn APIs): https://www.pionex.com/docs/api-docs
- Bot API (spot grid, futures grid, smart copy, signal): https://www.pionex.com/docs/api-docs/bot-api/bot-api
- OpenAPI 3 specs: https://github.com/pionex-official/pionex-open-api
- Change log (latest entry at this check: 2024-01-04, klines added): https://pionex-doc.gitbook.io/apidocs/readme/change-log.md
- Official AI Kit (CLI, MCP server, skills): https://github.com/pionex-official/pionex-ai-kit , skills https://github.com/pionex-official/pionex-skills
- Fees: https://www.pionex.com/en/fees (needs a browser; blocks automated fetching)
- Support / help center: https://support.pionex.com ; API Telegram group: https://t.me/pionexapi

## Public market data (no key)

Base `https://api.pionex.com`, GET only. Response: `{"result": true, "data": ..., "timestamp": <server ms>}`; errors come as HTTP 200 with `result: false` and a `code`.

| Endpoint | What | Limits (tested) |
|---|---|---|
| `/api/v1/common/symbols?symbols=BTC_USDT` or `?type=SPOT` | trading rules per pair | weight 5; parameter is `symbols` (plural); 413 spot pairs, 342 enabled |
| `/api/v1/market/bookTickers?symbol=BTC_USDT` | best bid/ask and sizes | no params = PERP |
| `/api/v1/market/tickers?symbol=BTC_USDT` | 24h rolling stats | no params = SPOT |
| `/api/v1/market/depth?symbol=BTC_USDT&limit=20` | order book | 1 to 1000, default 20 |
| `/api/v1/market/trades?symbol=BTC_USDT&limit=100` | recent trades (taker side) | up to 500, no history |
| `/api/v1/market/klines?symbol=BTC_USDT&interval=1D&limit=500&endTime=<ms>` | OHLCV candles | limit 1 to 500; ~10,000 bars of history |

- Symbols: `BASE_QUOTE` (`BTC_USDT`, `ETH_USDT`); perpetuals `BTC_USDT_PERP`.
- Kline intervals: `1M` (one minute), `5M`, `15M`, `30M`, `60M`, `4H`, `8H`, `12H`, `1D`. No weekly. Returned newest first, `time` = bar open (UTC); the newest bar is still forming. `endTime` is inclusive. 5M history is about 35 days, 60M about 416 days; 1D goes back to 2017-10-26 for BTC and ETH.
- WebSocket (public): `wss://ws.pionex.com/wsPub`, topics `TRADE` and `DEPTH` (1 to 100 levels), server PING every ~15 s needs a PONG, 10 connections per IP. Frames are binary UTF-8 JSON. The lab does not use it; it polls REST.

## Fees, sizes, limits

- Fees (official fee page, read in a browser on 2026-10-14): spot maker 0.050% / taker 0.050%, futures maker 0.020% / taker 0.050%, leveraged tokens 0.100%; no extra bot fee (blog); VIP tiers lower it (table not read). The lab assumes 5 bps per side for research and stresses costs 2x.
- Minimums (live, from `symbols`): BTC_USDT size step 0.000001, tick 0.01, minimum 10 USDT notional, size range 0.000001 to 1000 (limit) and to 100 (market sell). 300 of 324 enabled USDT pairs have a 10 USDT minimum. Precision and minimums differ per pair, so read them at runtime.
- Rate limit: 10 weight per second per IP (public) and per account (private). Over it: HTTP 429 and a 60 s ban. The lab keeps itself to 5 per second.

## Trading bots

Grid (spot, futures, infinity), DCA (martingale), rebalancing, smart copy, signal and arbitrage bots exist in the app. The API covers spot grid, futures grid, smart copy and signal (all signed, private); no DCA or rebalancing API was found. Minimum investment depends on the product and settings and is shown by the order panel or the `checkParams` call. The lab has no bot path; grids can only be studied as candle-based models.

## How our code reaches Pionex

| Need | Code |
|---|---|
| Public REST client, strict parsers, rate limiter | `pionex_lab/exchange/pionex_public.py`, `ratelimit.py` |
| Collector (BTC/ETH book 1 s, depth 3 s, klines) into `var/market.db` | `pionex_lab/data/collector.py`, `store.py` (`MarketView` for reads) |
| Long history (labelled Binance proxy, not Pionex) | `pionex_lab/data/proxy.py` -> `var/proxy_market.db` |
| Order request previews (dry-run only) | `pionex_lab/execution/dryrun.py`, cross-checked with the pinned CLI in `tools/pionex-cli` |
| Simulated fills | `pionex_lab/execution/paper.py` (quotes observed after submission, fees on both sides) |

Example: `py -c "import sys; sys.path.insert(0,'.'); from pionex_lab.exchange.pionex_public import PionexPublic as P; print(P().book_ticker('BTC_USDT')[0])"`

## Rules that always apply

Paper only (`live_enabled=false`; never edit the mandate or its lock). No orders, no private or signed endpoints, no keys or `.env` access, no AI Kit `onboard`/`setup`, no MCP trade server. Backtests, paper results and synthetic or proxy data are never proof of profitability.

## Known documentation errors (trust live behaviour)

`symbols` takes `symbols`, not `symbol`; `bookTickers` path is plural; `basePrecision` is quantity precision; depth and trades accept more levels than the CLI and the client allow (client caps both at 100); some field types in the docs are wrong (strings vs numbers). List: `.claude/skills/pionex-api/references/official-docs.md`.

## Open gaps

VIP fee table not read; bot minimums only from old or marketing pages; the client charges `symbols` as weight 1 though the docs say 5; WebSocket per-connection topic cap not documented; 4H/8H/12H bar alignment not checked. See `.claude/skills/pionex-api/references/verification-2026-10-14.md`.

## Demo trading (checked 2026-10-17)
Pionex demo is manual futures only: demo PUSD claimed in Futures -> Demo (app) or Futures Trading (web),
KYC Level 1 required, PUSD cannot be used with any bot (spot or futures grid) and there is no demo API
(support.pionex.com/hc/en-us/articles/45361340740761-Futures-Demo-Trading). Spot grid bots have no demo,
so the firm forward-tests them as live shadow grids on real-time Pionex prices.
