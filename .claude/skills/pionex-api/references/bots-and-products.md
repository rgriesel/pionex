# Pionex trading-bot products and their API (reference only)

Pionex's headline feature is its built-in bots. In THIS repo they are research context only: the mandate is paper, there is no bot or order path, and none may be added. Do not call any bot endpoint (all are private and signed). You may model bot behaviour on candles in research (labelled as a model) and cite the rules below.

## Products

| Product | What it does | API / CLI coverage |
|---|---|---|
| Spot Grid (arithmetic or geometric) | Places a ladder of buy/sell orders inside a price range; earns the grid spread, keeps inventory risk | Bot API `spotGrid`: CLI `bot spot_grid get/get_ai_strategy/create/adjust_params/invest_in/cancel/profit` |
| Infinity Grid | Grid with no upper bound; needs more capital (older blog: 50 USDT minimum) | Not separately documented in the API pages read |
| Futures Grid (leveraged, `trend` long/short/no_trend) | Grid on a perpetual (`base` ends with `.PERP`); liquidation risk | Bot API `futuresGrid`: CLI `bot futures_grid get/create/adjust_params/reduce/cancel` |
| Smart Copy, Signal bot, KOL | Copy trading / signal following | Bot API pages `smart-copy`, `signal`, `kol`; CLI `bot smart_copy`, `bot signal` |
| DCA (Martingale) bot | Staged buying with safety orders aiming at a target profit | No API or CLI tool found (2026-10-14) |
| Rebalancing bot | Keeps a basket at target weights (checks about every 5 minutes) | No API or CLI tool found |
| Reverse, Leveraged, Margin grids; Stop Limit; Trailing; TWAP; Crypto/Spot-Futures Arbitrage | Other app-only bots | No API found; "Earn Arbitrage" has CLI/MCP tools |
| Dual Investment, Earn Arbitrage | Structured/earn products | Earn APIs (Beta) |

"No API found" means absent from the API docs index and from the installed AI Kit tool list (v0.2.55, 52 tools), not that Pionex could not add one later.

## Spot Grid API facts [official-doc: https://www.pionex.com/docs/api-docs/bot-api/spot-grid]

- All private: `PIONEX-KEY` + `PIONEX-SIGNATURE` headers and `timestamp` within 20 s. Each endpoint weight 1.
- Paths under `/api/v1/bot/orders/spotGrid/`: `order` (GET), `aiStrategy` (GET), `checkParams`, `create`, `adjustParams`, `investIn`, `profit`, `cancel` (POST).
- `checkParams` validates a plan and returns `min_investment` and `max_investment` in quote currency without creating anything. The minimum is NOT fixed; it depends on pair, range and grid count.
- Grid count `row`: create schema says 2 to 200, `checkParams` accepts up to 1000 (the page does not reconcile this).
- `top > bottom`; `gridType` is `arithmetic` or `geometric`.
- Stops: `lossStop` / `profitStop` with type `price`, `profit_amount` or `profit_ratio`; optional `lossStopDelay` / `profitStopDelay` in seconds (omitted or 0 means immediate); optional trigger `condition` with `conditionDirection` 1 (rising) or -1 (falling).
- On close, `closeSellModel` is `NOT_SELL` (default, keep assets), `TO_QUOTE` or `TO_USDT`; `slippage` ratio (for example 0.01).

## Futures Grid API facts [official-doc: .../bot-api/futures-grid]

Paths under `/api/v1/bot/orders/futuresGrid/`: `order`, `create`, `checkParams`, `adjustParams` / `adjustParamsCheck`, `reduce` / `reduceCheck`, `cancel`, `pause` / `pauseCheck`, `resume` / `resumeCheck`, `addMargin` / `addMarginCheck`. Leverage is an integer from 1 up to the symbol maximum; `row` 2 to 500; `trend` long/short/no_trend; `grid_type` arithmetic/geometric; minimum investment from `checkParams`. Futures are outside the mandate (spot only, leverage 1).

## Minimum investment (what the sources say; the order panel or `checkParams` is the authority)

- Spot grid: depends on pair, range and grid count (Pionex guide). A blog example needs 3.8 USDT for a BTC/USDT grid. Infinity grid 50 USDT (older post).
- Futures grid: blog says from 10 USDT; an older FAQ gives tiers (more than 20 grids: above 50 USDT; more than 50 grids: above 200 USDT). The two conflict.
- DCA: roughly the pair's minimum trade volume times the total number of "shares" (Pionex example: 0.35 USDT x 100 = 35 USDT). Capital for all planned safety orders is reserved up front.
- Rebalancing: an older FAQ says 100 USDT per coin (200 for two coins). Check the live panel.
- Quoted limits above are from Pionex blog and support pages summarised by a search tool, several years old; treat as [secondary].

## How this connects to the lab

- A grid is a different strategy with a different balance scope (bot balances are excluded from `GET /api/v1/account/balances`) and its own stop/close semantics. `pionex-trading-lab/SKILL.md` section 3 and 4 say: consider a bounded grid only in a validated range regime, with full inventory accounting, and never assume protection that has not been shown.
- Bot fees = normal trading fees per order (`fees-sizes-limits.md`). Grid "profit" shown by Pionex is not total P&L (it excludes inventory mark-to-market).
- Any grid study here is a candle-based simulation with Pionex fees, tagged as a model, and cannot be presented as evidence of profit.
