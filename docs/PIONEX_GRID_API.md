# Pionex Bot API digest: Spot Grid and Futures Grid (CLO-20)

Docs only. Read 2026-10-16 from the official pages (Markdown copies) and `openapi_bot.yaml` in github.com/pionex-official/pionex-open-api. No keys, no signed calls. Anything not in those sources is **UNKNOWN**.

Source tags (every fact below carries one):
- **[SG]** https://www.pionex.com/docs/api-docs/bot-api/spot-grid
- **[FG]** https://www.pionex.com/docs/api-docs/bot-api/futures-grid
- **[BO]** https://www.pionex.com/docs/api-docs/bot-api/bot-orders
- **[AUTH]** https://www.pionex.com/docs/api-docs/bot-api/general-info/authentication
- **[RL]** https://www.pionex.com/docs/api-docs/bot-api/general-info/rate-limits
- **[BASIC]** https://www.pionex.com/docs/api-docs/bot-api/general-info/basic-info
- **[YAML]** https://github.com/pionex-official/pionex-open-api/blob/main/openapi_bot.yaml
- **[LAB]** `docs/PIONEX.md` (official fee page read 2026-10-14, https://www.pionex.com/docs/api-docs)

All paths under `https://api.pionex.com`. Every endpoint is **signed** (HMAC SHA256, headers `PIONEX-KEY`, `PIONEX-SIGNATURE`, query `timestamp` in ms, valid +/-20 s) [AUTH][BASIC]. There is no public (unsigned) bot endpoint, including checkParams and aiStrategy. Signature string: GET `METHOD+PATH+QUERY+TIMESTAMP`; POST/DELETE adds the JSON body [BASIC]. Zero-valued number parameters are disregarded [BASIC]. Every endpoint is weight 1 [SG][FG][BO].

## 1. Endpoints and key permission

Permission names per [AUTH]: `Bot reading`, `Bot trading`, `Enable trading`. Read = bot reading; trade = bot trading. No bot endpoint listed needs `Enable trading` except the signal push (not a grid endpoint).

### Spot grid ([SG])

| Purpose | Method + path | Permission [AUTH] |
|---|---|---|
| List bot orders (all types, `status=running` default or `finished`) [BO] | GET `/api/v1/bot/orders` | Bot reading |
| Get one order | GET `/api/v1/bot/orders/spotGrid/order` (`buOrderId`) | Bot reading |
| AI strategy suggestion (`base`,`quote`) | GET `/api/v1/bot/orders/spotGrid/aiStrategy` | Bot reading |
| Check params / min-max investment | POST `/api/v1/bot/orders/spotGrid/checkParams` | Bot reading |
| Create | POST `/api/v1/bot/orders/spotGrid/create` | Bot trading |
| Adjust range/rows or add investment | POST `/api/v1/bot/orders/spotGrid/adjustParams` | Bot trading |
| Add investment | POST `/api/v1/bot/orders/spotGrid/investIn` | Bot trading |
| Cancel / close | POST `/api/v1/bot/orders/spotGrid/cancel` | Bot trading |
| Extract (withdraw) grid profit | POST `/api/v1/bot/orders/spotGrid/profit` | Bot trading |

### Futures grid ([FG])

| Purpose | Method + path | Permission [AUTH] |
|---|---|---|
| Get one order | GET `/api/v1/bot/orders/futuresGrid/order` (`buOrderId`, optional `lang`) | Bot reading |
| Check params | POST `.../futuresGrid/checkParams` | Bot reading |
| Check adjust (dry run) | POST `.../futuresGrid/adjustParamsCheck` | Bot reading |
| Check reduce (dry run) | POST `.../futuresGrid/reduceCheck` | Bot reading (per [AUTH]) |
| Create | POST `.../futuresGrid/create` | Bot trading |
| Adjust (add investment / change range / trigger invest) | POST `.../futuresGrid/adjustParams` | Bot trading |
| Reduce position | POST `.../futuresGrid/reduce` | Bot trading |
| Cancel / close | POST `.../futuresGrid/cancel` | Bot trading |
| Pause check / pause / resume check / resume | POST `.../pauseCheck`, `/pause`, `/resumeCheck`, `/resume` | Bot trading (checks too) |
| Add / reduce margin, with `...Check` dry runs | POST `.../addMarginCheck`, `/addMargin`, `/reduceMarginCheck`, `/reduceMargin` | Bot trading |
| Set / update / clear TP and SL on a running order | POST `.../updateTriggerProfitLoss` | Bot trading |

Other bot types (smart copy, signal, KOL) exist [AUTH] and are out of scope. A cross-margin futures grid type `future_hedge_grid` appears in [BO] and [YAML] but has no create endpoint in the docs read: UNKNOWN whether API-creatable.

Observations: the docs mention no spot-grid pause/resume (not in [SG]); no spot "reduce position" endpoint; the `Bot trading` key can create bots, so a key that only reads must be `Bot reading` only. Whether `Bot trading` implies `Bot reading`, whether a bot key can move funds out of the account, and IP whitelist requirements: UNKNOWN (API key guide https://www.pionex.com/docs/api-docs/references/api-key-guide not read).

## 2. Parameters

### Spot grid create ([SG], body; `base`, `quote`, `buOrderData` required)

| Field | Type | Units / limits |
|---|---|---|
| `base`, `quote` | string | e.g. BTC / USDT (spot symbols, no `.PERP`) |
| `note` | string | optional |
| `buOrderData.top`, `bottom` | string | grid upper / lower price, quote per base; checkParams: `bottom < top`, numeric, integer part and decimal part <= 15 digits |
| `buOrderData.row` | integer | grid levels. **Create spec says 2-200; checkParams says 2-1000** (docs disagree; use <=200 until verified) |
| `buOrderData.gridType` | enum | `arithmetic` (equal difference) or `geometric` (equal ratio) |
| `buOrderData.quoteTotalInvestment` | string | investment in quote currency; must be >= `min_investment` from checkParams |
| `lossStopType` / `lossStop` / `lossStopDelay` | enum `price`, `profit_amount`, `profit_ratio` / string / int s | stop loss: price (e.g. "40000"), loss amount in quote (e.g. "-50") or ratio ("-0.1" = -10%); delay: condition must hold continuously, 0/omitted = immediate |
| `profitStopType` / `profitStop` / `profitStopDelay` | same enum / string / int s | take profit; amount or ratio compared with *realized* profit |
| `condition`, `conditionDirection` | string, `"-1"`/`"1"` | optional trigger price; bot starts only after price crosses it; -1 = price drops to, 1 = rises to |
| `slippage` | string | open-position slippage, "0.01" = 1% |
| `closeSellModel` | enum, default `NOT_SELL` | on cancel: `NOT_SELL` keep base+quote, `TO_QUOTE` sell base to quote, `TO_USDT` sell base to USDT |

Stop loss `profit_amount`/`profit_ratio` is "unrealized loss" [SG]. Note the create description also lists `TO_QUOTE`/`TO_USDT` semantics that differ slightly from the order-response description (`TO_QUOTE` "return base+quote as-is"): ambiguity, UNKNOWN which is right. Spot grid direction is always long [SG]. Funds are the base/quote already in the main account; margin: none.

### Spot grid checkParams ([SG])
Body uses snake_case: `buOrderData.top`, `bottom`, `row` (2-1000), `grid_type`, `quote_total_investment`, `condition`, `condition_direction`. Returns `min_investment`, `max_investment`, `slippage` (recommended), `estimate_per_volume`, `estimate_fee` (opening fee). Error `grid price duplicated: reduce row or widen range`, `quote_total_investment not match quote precision`, `less than min investment` return the min/max data even with `result=false`. **Minimum investment: dynamic, only obtainable from this call; no fixed number in docs. UNKNOWN as a rule.** Note create uses camelCase and checkParams snake_case [SG].

### Spot grid adjust / invest / cancel / profit ([SG])
- adjustParams: `buOrderId` (req), `top`, `bottom`, `row`, `quoteInvest`; returns `action_id`. Whether the range change resets open orders or requires a position: UNKNOWN.
- investIn: `buOrderId`, `quoteInvest` (req); returns `action_id`.
- cancel: `buOrderId` (req), `closeSellModel` (`NOT_SELL`/`TO_QUOTE`/`TO_USDT`), `slippage` for the close.
- profit: `buOrderId`, `amount` (req). Moves accumulated grid profit out; returns a transfer record.

### Futures grid create ([FG], body; `base`, `quote`, `buOrderData` required)

| Field | Type | Units / limits |
|---|---|---|
| `base`, `quote` | string | `base` must end with `.PERP` (checkParams) |
| `top`, `bottom` | string | prices; must match symbol price precision; `bottom > 0`, `top > bottom` |
| `row` | number | grid levels, checkParams range 2-500 |
| `grid_type` (create sample uses this name; response `gridType`) | enum | `arithmetic` / `geometric` |
| `trend` | enum | `long`, `short`, `no_trend` (neutral) |
| `leverage` | number | 1 to the symbol's max leverage (checkParams); the max per symbol: UNKNOWN |
| `extraMargin` | string | extra margin amount on top of investment (liquidation buffer) |
| `quoteInvestment` | string | investment in quote; >= `min_investment` |
| `investCoin` | string | `USDT` or the quote currency (default); coin-margined variant via `cateType=FUTURE_GRID_COIN_MARGINED` |
| `lossStopType` / `profitStopType` | enum `price`(default), `profit_amount`, `profit_ratio`, `price_limit` | `price_limit` closes by limit order at `lossStopLimitPrice` / `profitStopLimitPrice` |
| `lossStop`, `profitStop`, `lossStopDelay`, `profitStopDelay` | string / string / number / number | threshold meaning depends on type; delay in seconds |
| `lossStopHigh` | string | upper stop-loss price for a neutral grid (above `top`); `lossStopLimitHighPrice` for the limit variant |
| `condition`, `conditionDirection` | string, `"-1"`/`"1"` | trigger start price |
| `slippage` | string | open slippage, "0.01" = 1% |
| `movingIndicatorType`, `movingIndicatorInterval` (1m,15m,30m,1h,4h,12h), `movingIndicatorParam` (JSON e.g. `{"length":720}`), `movingTrailingUpParam` (e.g. 0.05), `movingTop`, `movingBottom` | strings | moving (trailing) grid options |
| `cateType` | enum | `FULLY_HEDGING`, `LOAN_GRID`, `LEVERAGE_GRID`, `FUTURE_GRID_COIN_MARGINED` |
| `copyFrom`, `copyType`, `copyBotOrderId`, `shareRatio`, `investmentFrom` (`USER`/`FUTURE_GRID_BONUS`), `bonusId`, `enableFollowClosed`, `uiInvestCoin`, `uiExtraData` | various | copy trading and bonus features; not needed for us. **Warning:** `copyBotOrderId` joins an existing copy pool; never set it. |

checkParams ([FG]) adds `extra_margin` (boolean) and `extra_margin_amount`. `extra_margin=false`: `quote_investment` is trading capital and extra margin is separate. `extra_margin=true`: `quote_investment` is the total, the system splits it. Returns `min_investment`, `max_investment`, `estimate_investment`, `estimate_extra_margin`, `estimate_fee`, `estimate_position_occupy_margin`, `estimate_order_occupy_margin`, `estimate_position` (+ long, - short), `estimate_liquidation_price_up/down` (`"0"` when no risk that side). Min investment again dynamic; UNKNOWN as a rule.

Adjust ([FG]): `type` = `invest_in` / `adjust_params` / `invest_in_trigger`; required `buOrderId`, `type`, `extraMargin`, `openPrice`; fields `quoteInvestment`, `top`, `bottom`, `row`, `isReinvest`, `keepInvestment`, `adjustParamsSence=reinvest`, `condition`, `slippage`. Without `keepInvestment`, an adjust needs current PnL > 0 else `PROFIT_LESS_THAN_ZERO`. Reduce: `buOrderId`, `openPrice`, `reduceNum` (order precision x reduceNum), optional `slippage`, `condition`. Cancel: `closeSellModel` (`TO_QUOTE` close position only (default), `TO_USDT` close and sell quote to USDT), `closeSlippage`, `closeNote`, `immediate` (only for orders stuck in `close_position` with an unfilled limit TP/SL). Pause: `mode` immediate/conditional, trigger prices, keep TP/SL while paused (grid stops refilling, position retained). Resume: trigger prices or `isResumeImmediate`. Add/reduce margin: `buOrderId`, `coin`, `amount`; reduce limited to `maxAmount` = min(extra margin, equity - 1.05 x used margin, margin account balance). TP/SL update: `bu_order_id`, `list[]` with `type` (`stop_loss`/`stop_profit`), `stop_type`, `value` (empty clears), `limit_price`, `stop_delay`, sell models, `stop_high_price` for neutral grids.

Close behaviour summary: spot `closeSellModel` default does **not** sell (you keep coins); futures cancel closes the position, optionally selling the quote coin to USDT [SG][FG].

## 3. Status and profit fields

Spot grid `data.buOrderData` ([SG], [YAML]):

| Field | Doc definition |
|---|---|
| `status` | `prepare`, `lock_currency`, `init_grid`, `running`, `destroy_grid`, `unlock_currency`, `canceled` |
| `gridProfit` | "Accumulated grid profit" (no formula given; fees treatment UNKNOWN) |
| `realizedProfit` | "Total realized profit (grid profit + float P&L)" (so float P&L is a component; there is no separate float field in the doc) |
| `profitWithdrawn` | profit extracted so far |
| `baseAmount`, `quoteAmount` | current balances inside the bot |
| `baseInvestment`, `quoteInvestment` | actual investment; `*TotalInvestment` totals |
| `totalCostInBase/Quote`, `averageCost` | cost basis |
| `totalFeeInBase/Quote` | fees charged |
| `breakEvenWithGridProfit`, `breakEvenWithoutGridProfit` | break-even prices |
| `perVolume`, `openPrice`, `pausePrice`, `profitAutoReinvest` | per-level size, creation price, paused price, reinvest flag |
| `reasonBy` | `user_cancel`, `loss_stop`, `profit_stop`, `not_enough_balance`, `create_failed` |

Futures grid order ([FG]): `status` has 18 values (`running`, `paused`, `adjust_params`, `close_position`, etc.), `reasonBy` includes `force_liquidation`, `riskStatus` `TRADING/HOLDING/TAKEOVER/LIQUIDATION`, `position`, `positionOpenPrice`, `marginBalance`, `liquidationPrice`, `estimateLiquidationPriceUp/Down`, `profitReduce` ("Grid profit from position reduction"), `profitExited`, `fundingFeePayment` ("Total funding fee paid (negative value)"), `profitWithdrawn`, `marginStatus` `NORMAL/INSUFFICIENT`, `notionalStatus`. **The plain futures grid order response has no `gridProfit` or unrealized-PnL field in the docs: UNKNOWN how to read them** (`gridProfit` and `totalRealizedProfit`, `totalFee`, `totalFundingFee` exist only on the cross-margin `future_hedge_grid` schema [YAML]). A spot-vs-futures profit comparison via API would need to be derived from fills: not documented.

Order list ([BO]): `buOrderType` `spot_grid`/`futures_grid`/`future_hedge_grid`/`smart_copy` (note the single-order spot response says `grid_v5`), paging with `pageToken`, filters `status`, `base`, `quote`, `buOrderTypes`.

## 4. Fees

| Item | Fact |
|---|---|
| Spot maker / taker | 0.050% / 0.050% [LAB] (official fee page, tiered by VIP; table not read) |
| Futures maker / taker | 0.020% / 0.050% [LAB] |
| Extra bot fee | none, per blog cited in [LAB] (not the API docs) |
| Fee on grid fills stated in bot API docs | **UNKNOWN**: docs expose `totalFeeInBase/Quote` and `estimate_fee` (opening fee) only, with no rate. Whether grid fills are maker or taker: UNKNOWN |
| Futures funding | `fundingFeePayment` is tracked in the order [FG] |
| Liquidation | `liquidationFee` field exists [FG]; rate UNKNOWN |
| Profit sharing | `shareRatio`, `bonusFeeRatio` appear for copy/bonus orders only [FG] |

## 5. Rate limits and errors

- 10 requests per second per IP, shared by all endpoints; and 10 per second per account for private endpoints; exceeding returns HTTP 429; weights per endpoint (all 1 here) [RL]. Per-minute or daily bot-creation limits: UNKNOWN.
- Errors: `BOT_INVALID_ARGUMENT`, `BOT_INTERNAL_ERROR` (retry may help), `PARAMETER_ERROR` [BO][YAML]. Validation failures can carry `data` (min/max investment) [SG].
- Responses are asynchronous for several futures operations (pause, margin, adjust): poll `GET .../order` for the result [FG].

## 6. Gaps to close before any design depends on them

1. Real min and max investment per pair: only checkParams, which needs a signed call with a Bot-reading key (not allowed under FIRM_RULES limit 5 for now).
2. Spot `row` limit (200 in create vs 1000 in checkParams).
3. Is a Bot-reading-only key really incapable of any fund movement (check the API key guide).
4. How grid fills are charged (maker vs taker) and whether `gridProfit` is net of fees.
5. Futures grid unrealized/grid profit field names (only on hedge grid in the spec).
6. Per-symbol max leverage and the `.PERP` symbol list for sideways pairs: use the Trade/Futures API docs.

## 7. Permission map by firm step (CLO-21 1b; built from the docs only, no key was read or tested)

Permission names from [AUTH]: `Bot reading`, `Bot trading`. The owner checks their own key in the Pionex UI; nothing here has been verified against a real key. Firm steps: **S1** read bot status / history (monitor a running bot); **S2** dry-run validation and parameter suggestion before any create; **S3** create a bot; **S4** alter a running bot; **S5** stop a bot or take money out.

| Endpoint | Key permission | Firm step that would need it | Create/alter? |
|---|---|---|---|
| GET `/bot/orders` (list, `status=running|finished`) | Bot reading | S1 | read |
| GET `/bot/orders/spotGrid/order`, GET `/bot/orders/futuresGrid/order` | Bot reading | S1 | read |
| GET `/bot/orders/spotGrid/aiStrategy` | Bot reading | S2 (compare our range with Pionex's suggestion) | read |
| POST `spotGrid/checkParams`, `futuresGrid/checkParams` | Bot reading | S2 (the only source of the real minimum investment) | read (dry run) |
| POST `futuresGrid/adjustParamsCheck`, `/reduceCheck` | Bot reading | S2 / S4 preview | read (dry run) |
| POST `spotGrid/create`, `futuresGrid/create` | Bot trading | S3 | **create** |
| POST `spotGrid/adjustParams`, `/investIn`; `futuresGrid/adjustParams` | Bot trading | S4 | **alter** (moves funds into the bot) |
| POST `futuresGrid/reduce`, `/pause`, `/pauseCheck`, `/resume`, `/resumeCheck` | Bot trading | S4 | **alter** (the check calls too, per [AUTH]) |
| POST `futuresGrid/addMargin`, `/reduceMargin` and their `...Check` | Bot trading | S4 | **alter** |
| POST `futuresGrid/updateTriggerProfitLoss` | Bot trading | S4 (change stop-loss / take-profit) | **alter** |
| POST `spotGrid/cancel`, `futuresGrid/cancel` | Bot trading | S5 | **alter** (closes; `closeSellModel` may sell the base) |
| POST `spotGrid/profit` | Bot trading | S5 (withdraws grid profit out of the bot) | **alter** (moves funds) |

Minimum key for the firm's monitoring and validation work (S1 + S2): **Bot reading only**. Anything under S3-S5 needs `Bot trading`, which no firm step may use while the mandate stays paper (`live_enabled=false`) and the $100 live cap applies. A signed call is still a signed call: even `Bot reading` endpoints are not to be called until the board lifts FIRM_RULES limit 5. Open questions (UNKNOWN in the docs, section 1): whether `Bot trading` includes `Bot reading`, whether a bot-only key can move funds out of the account, whether an IP whitelist is required.
