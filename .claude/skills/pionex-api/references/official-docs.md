# Official Pionex documentation: where to look

Checked 2026-10-14. There are two official doc sites with the same content; the GitBook one is the easiest to fetch because every page also exists as raw Markdown by appending `.md`.

## API docs

| What | URL |
|---|---|
| GitBook index (machine-readable page list) | https://pionex-doc.gitbook.io/apidocs/llms.txt |
| Overview | https://pionex-doc.gitbook.io/apidocs |
| Change log | https://pionex-doc.gitbook.io/apidocs/readme/change-log.md |
| REST basics (base URL, envelope, error codes) | https://pionex-doc.gitbook.io/apidocs/restful/general/basic.md |
| Rate limit | https://pionex-doc.gitbook.io/apidocs/restful/general/rate-limit.md |
| Authentication (private; not for this repo) | https://pionex-doc.gitbook.io/apidocs/restful/general/authentication.md |
| Symbols (market data page under Common) | https://pionex-doc.gitbook.io/apidocs/restful/common/market-data.md |
| Get Klines | https://pionex-doc.gitbook.io/apidocs/restful/markets/get-klines.md |
| Get Depth | https://pionex-doc.gitbook.io/apidocs/restful/markets/get-depth.md |
| Get Trades | https://pionex-doc.gitbook.io/apidocs/restful/markets/get-trades.md |
| Get 24hr Ticker | https://pionex-doc.gitbook.io/apidocs/restful/markets/get-24hr-ticker.md |
| Get Book Ticker | https://pionex-doc.gitbook.io/apidocs/restful/markets/get-book-ticker.md |
| Orders (documentation only: New Order, Get/Cancel, Fills) | https://pionex-doc.gitbook.io/apidocs/restful/orders.md , `.../orders/new-order.md` |
| WebSocket general info | https://pionex-doc.gitbook.io/apidocs/websocket/general-info.md |
| WebSocket public TRADE / DEPTH | https://pionex-doc.gitbook.io/apidocs/websocket/public-stream/trade.md , `.../depth.md` |
| Newer docs site (Trade, Trade WebSocket, Wallet, Bot, Earn, Earn Dual APIs; Futures/Institution/Partner marked internal) | https://www.pionex.com/docs/api-docs |
| Bot API (spot grid, futures grid, smart copy, signal, KOL) | https://www.pionex.com/docs/api-docs/bot-api/bot-api , `/spot-grid`, `/futures-grid` |
| API key guide and permissions (private use) | https://www.pionex.com/docs/api-docs/references/api-key-guide , `.../api-key-permissions` |
| OpenAPI 3 specs (exact types) | https://github.com/pionex-official/pionex-open-api |
| Official API Telegram group | https://t.me/pionexapi |

`https://www.pionex.com/docs/api-docs/llms.txt` returned 404 (the index only exists on the GitBook host).

## Toolkit

| What | URL |
|---|---|
| AI Kit (CLI + MCP + skills) | https://github.com/pionex-official/pionex-ai-kit |
| Its manual (cli, mcp, skills guides) | https://github.com/pionex-official/pionex-ai-kit/tree/main/manual |
| Skills repo | https://github.com/pionex-official/pionex-skills |
| `pionex-market` skill (public data) | https://github.com/pionex-official/pionex-skills/tree/main/skills/pionex-market |
| Org | https://github.com/pionex-official |

## Fees, bots and help

| What | URL | Fetch status |
|---|---|---|
| Fee schedule | https://www.pionex.com/en/fees | HTTP 403 to automated fetch; open it in a browser |
| Pionex support center (VIP tiers, funding fee, bot guides) | https://support.pionex.com | 403 to automated fetch |
| VIP tier system upgrade (effective 2025-11-01) | https://support.pionex.com/hc/en-us/articles/51746121935641-Pionex-VIP-Tier-System-Upgrade | 403 (seen in search results only) |
| Funding fee | https://support.pionex.com/hc/en-us/articles/45028729414041-Funding-Fee | not read |
| Grid trading bot guide | https://support.pionex.com/hc/en-us/articles/45085712163225-Grid-Trading-Bot | 403 |
| DCA (Martingale) bot | https://support.pionex.com/hc/en-us/articles/49725673393817-DCA-Martingale-Bot-DIY | not read |
| Bot fees FAQ (Pionex blog) | https://www.pionex.com/blog/knowledge-base/whats-the-free-to-use-these-12-trading-bots-on-pionex/ | read |
| Minimum investment per bot (Pionex blog) | https://www.pionex.com/blog/the-minimum-investment-required-to-start-on-pionex/ | listed, not read |
| Rebalancing bot | https://www.pionex.com/blog/pionex-rebalancing-bot/ | listed, not read |

To read a blocked page use the built-in browser or Chrome tool instead of the fetch tool, and still treat the blog and help center as marketing-grade until the fee shows on a real fill.

## Doc errors found by testing (trust the live behaviour)

1. `symbols` example uses `?symbol=BTC_USDT`; the real parameter is `symbols` (plural). The singular is ignored and returns all 413 spot symbols.
2. `bookTickers` example URL says `/bookTicker`; the path is `/bookTickers`. With no parameter it defaults to PERP (the doc table says so), while `tickers` and `symbols` default to SPOT.
3. Depth `limit` is 1 to 1000 (change log 2022-11-24), but the CLI skill and the WebSocket DEPTH cap are 100. Trades `limit` doc says 10 to 500; 5 and 9 also worked. Our client caps both at 100.
4. Field type typos: `tickers[].count` documented as string, returned as number; `trades[].timestamp` documented as string, returned as number; `bookTickers[].bidPrice` documented as number, returned as string.
5. `basePrecision` is described as price decimals of the base currency; it is the base QUANTITY precision. `quotePrecision` is the price precision.
6. The Spot Grid page gives `row` as 2 to 200 for create but accepts up to 1000 in `checkParams`.
7. The WebSocket page's signing example uses `wss://api.pionex.com/ws` while the connection section uses `ws.pionex.com`. The real host is `ws.pionex.com`.
8. Error-code spellings in the basic page are inconsistent (`INVALIE_APIKEY`, `TRADE_INVAILD_SYMBOL`), while the order page uses `TRADE_INVALID_SYMBOL`. Match error codes by prefix, not exact spelling, in code that handles private errors (the lab does not).
9. The older reference in `pionex-trading-lab/references/pionex-api.md` links to `pionex.com/docs/api-docs/trade-api/...`; those paths belong to the newer site and may move.

Re-verify these when the change log (https://pionex-doc.gitbook.io/apidocs/readme/change-log.md) shows an entry newer than 2024-01-04, which was the latest at this check.
