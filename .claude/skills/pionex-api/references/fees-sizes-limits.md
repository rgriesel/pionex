# Fees, minimum sizes, precision, and limits

Confidence tags: [official-doc] read on an official Pionex docs page; [observed] returned by a live public call on 2026-10-14; [secondary] Pionex blog or search-result summary, or the support center as summarised by a search tool (the fee page itself blocked automated fetching); [lab] a lab assumption.

## Fees

| Item | Value | Confidence |
|---|---|---|
| Spot trading fee | 0.05% of the transaction, charged on each trade (so ~0.10% for a round trip), maker and taker alike at the standard level | [secondary] Pionex blog posts (older ones from 2021, a 2026 review repeats it) |
| Trading bots (grid etc.) | No bot subscription or activation fee; each bot order pays the applicable trading fee | [secondary] Pionex blog, updated 2026-09-09 |
| Futures/perpetual (standard) | 0.02% maker, 0.05% taker, plus funding every 8 hours | [secondary] Pionex blog |
| VIP discounts | VIP tier recalculated daily at 01:30 UTC from the 30-day rolling volume and average account assets; tier system upgraded effective 2025-11-01 (VIP1 from 20 BTC 30-day spot volume or 3,000,000 USD futures; VIP10 added). A superseded June 2025 table showed spot VIP1 0.045% maker / 0.050% taker and VIP5 0.025% / 0.050%. Current per-tier table NOT read | [secondary] |
| Fixed-fee products (no VIP discount) | XStock-Spot, Leveraged Tokens, Spot Innovation Zone, MEME Guru | [secondary] |
| Spot-futures arbitrage bot | extra 10% fee on the bot's profit | [secondary], older |
| Referral discount | promotional pages claim 20% off; do not assume | [secondary] |
| Lab research fee | `assumed_spot_fee_per_side_for_research_only = 0.0005` (5 bps) per side in `config/mandate.v1.json`; `verified_fee_source` is still `null` | [lab] |
| Fee asset | The paper broker charges buys in the base asset and sells in quote. This is an assumption until checked against a real fill record | [lab] |

How to use this: charge 5 bps on both sides plus spread and impact in every backtest or paper trade, and run the 2x cost stress the mandate requires. The authoritative number for a given account is the fee on its own fills (a private endpoint; not available to this repo). Official fee page to check in a browser: https://www.pionex.com/en/fees (returned HTTP 403 to the fetch tool). Say "unverified from a primary source" when quoting these numbers.

## Rate limits

- REST [official-doc]: public endpoints share 10 weight/s per IP; private endpoints share 10/s per account; the two are independent. Exceeding the limit returns HTTP 429 and bans the IP or account for 60 seconds; continuing to send requests extends the ban by 10 seconds per request. No rate-limit headers are documented.
- Weights [official-doc]: `/api/v1/common/symbols` 5; `tickers`, `bookTickers`, `depth`, `trades`, `klines` 1 each.
- Lab budget [lab]: 5 weight/s (half the cap), 1 unit reserved for exit/reconciliation traffic. The collector's steady state for 2 symbols is about 3 requests per second.
- Never retry a 429 immediately. `PionexPublic` bans its own limiter for the server interval or a jittered backoff and raises `RateLimited`.
- WebSocket [official-doc]: 10 connections per IP; a per-connection topic cap exists (error `SUBSCRIBED_TOPICS_EXCEED_LIMIT`, number not documented).

## Symbol rules (min order size, precision)

Source: `GET /api/v1/common/symbols`. Re-read before any size calculation; never hard-code (rules vary by pair and change).

| Field | Meaning in this repo |
|---|---|
| `basePrecision` | decimals of base quantity. Size step = `10^-basePrecision` (`SymbolRules.quantity_step`) |
| `quotePrecision` | decimals of price. Price tick = `10^-quotePrecision` (`SymbolRules.price_step`) |
| `amountPrecision` | decimals of the quote `amount` in a market BUY |
| `minAmount` | minimum quote notional: market BUY `amount`, and `size * price` of a LIMIT order |
| `minTradeSize` / `maxTradeSize` | LIMIT order size range (base) |
| `minTradeDumping` / `maxTradeDumping` | MARKET SELL size range (base) |
| `enable` | tradable now; skip when false |
| `buyCeiling` / `sellFloor` | price band as a ratio of the latest price (1.1 and 0.9 on all pairs seen: limit prices outside +10% / -10% are denied, exact reference price not documented) |

The doc text calls `basePrecision` "decimals for prices in the base currency"; live data shows it is the quantity precision (BTC_USDT `basePrecision` 6 matches `minTradeSize` 0.000001; `quotePrecision` 2 matches a 0.01 price tick).

Observed 2026-10-14:

| Symbol | basePrec | quotePrec | amountPrec | minAmount | minTradeSize | maxTradeSize | minTradeDumping | maxTradeDumping |
|---|---|---|---|---|---|---|---|---|
| BTC_USDT | 6 | 2 | 8 | 10 | 0.000001 | 1000 | 0.000001 | 100 |
| ETH_USDT | 5 | 2 | 8 | 10 | 0.00001 | 10000 | 0.00001 | 1000 |
| SOL_USDT | 2 | 2 | 8 | 10 | 0.01 | 900000 | 0.01 | 900000 |
| DOGE_USDT | 2 | 5 | 8 | 10 | 1 | 200000000 | 1 | 20000000 |

Among 324 enabled USDT spot pairs: `minAmount` was 10 USDT on 300, 5 on 8, 1 on 16. So the practical floor for a USDT order is 10 USDT notional on majors. At the lab's USD 100 scale that is 10% of capital per minimum order, which limits sizing granularity.

The error codes when a rule is broken [official-doc]: `TRADE_PRICE_FILTER_DENIED`, `TRADE_SIZE_FILTER_DENIED`, `TRADE_AMOUNT_FILTER_DENIED` (also bad price x size), `TRADE_NOT_ENOUGH_MONEY`, `TRADE_REPEAT_CLIENT_ORDER_ID`, `TRADE_OPEN_ORDER_EXCEED_LIMIT`, `TRADE_PARAMETER_ERROR`, `TRADE_INVALID_SYMBOL`, `TRADE_OPERATION_DENIED`. The lab's dry-run validator mirrors these locally (see `order-previews.md`).

Bot minimums are different and set per product (`bots-and-products.md`).

## Data limits

| What | Limit |
|---|---|
| Klines per call | 500 |
| Kline history | ~10,000 bars back from now per interval (`MARKET_INVALID_TIME` beyond). 1D reaches 2017-10-26 for BTC/ETH |
| REST depth | 1 to 1000 levels (client 100) |
| Recent trades | 500 per call, no history |
| WebSocket depth | 1 to 100 levels |
| Order `clientOrderId` | 64 characters; letters, digits, hyphens |
