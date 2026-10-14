# Order previews in this repo (dry-run only; nothing is ever sent)

Paper trading needs no keys. An "order" in the lab is a request body that is rendered and validated locally, plus a fill that is SIMULATED later from public quotes. No code in this repo can place an order, and none may be added.

## What the exchange order looks like (for reference) [official-doc]

`POST /api/v1/trade/order` (private, Trade permission, weight 1). Body: `symbol`, `side` BUY|SELL, `type` LIMIT|MARKET, optional `clientOrderId` (letters, digits, hyphens, max 64), `size`, `price`, `amount`, `IOC` (default false). Rules:

| Order | Required |
|---|---|
| LIMIT (BUY or SELL) | `size` + `price` |
| MARKET BUY | `amount` (quote currency to spend) |
| MARKET SELL | `size` (base quantity) |

Response `{"data":{"orderId":..., "clientOrderId":"..."},"result":true,...}`. The documented spot order types are LIMIT and MARKET only; the docs do not establish stop, OCO, post-only or reduce-only support. Do not invent them. The Orders page covers SPOT non-strategy orders only.

## `pionex_lab/execution/dryrun.py`

```python
from decimal import Decimal
from pionex_lab.exchange.pionex_public import PionexPublic
from pionex_lab.execution import dryrun

rules = PionexPublic().symbols(["BTC_USDT"])[0][0]

# 1) Local render + validation (pure Python, no network, no CLI)
req = dryrun.build_order_request(rules, side="BUY", type_="LIMIT", client_order_id="demo-001",
                                 size=Decimal("0.000245"), price=Decimal("81701.83"))
# {"tool": "pionex_orders_new_order", "method": "POST", "path": "/api/v1/trade/order",
#  "args": {"symbol":"BTC_USDT","side":"BUY","type":"LIMIT","clientOrderId":"demo-001",
#           "size":"0.000245","price":"81701.83"}, "sent": False}

# 2) Same, cross-checked against the pinned official CLI's own --dry-run output (still sends nothing)
cli = dryrun.find_official_cli()                       # [node, .../pionex-ai-kit/dist/index.js] or None
req = dryrun.preview(rules, cli, side="BUY", type_="LIMIT", client_order_id="demo-001",
                     size=Decimal("0.000245"), price=Decimal("81701.83"))
# adds req["preview_source"] = "official pionex-trade-cli --dry-run"   (verified identical args on 2026-10-14)
```

Signature: `build_order_request(rules, side, type_, client_order_id, size=None, price=None, amount=None, ioc=None)`. Sizes, prices and amounts are `Decimal`; the body carries plain-decimal strings. `"sent": False` is always present.

Validation raised as `DryRunError(<code>)`:

| Code | Cause |
|---|---|
| `ORDER_SIDE_OR_TYPE` | side not BUY/SELL or type not LIMIT/MARKET |
| `CLIENT_ORDER_ID_LENGTH` | empty or over 64 chars |
| `SYMBOL_DISABLED` | `rules.enabled` false |
| `LIMIT_REQUIRES_PRICE_AND_SIZE`, `MARKET_BUY_REQUIRES_AMOUNT`, `MARKET_SELL_REQUIRES_SIZE` | wrong field combination |
| `SIZE_PRECISION` | size not a multiple of the quantity step (`10^-basePrecision`) |
| `SIZE_BELOW_MINIMUM` / `SIZE_ABOVE_MAXIMUM` | outside `minTradeSize..maxTradeSize` (LIMIT) or `minTradeDumping..maxTradeDumping` (MARKET sell) |
| `PRICE_PRECISION` | price not a multiple of the tick |
| `NOTIONAL_BELOW_MINIMUM` | `size * price < minAmount` |
| `AMOUNT_PRECISION` / `AMOUNT_BELOW_MINIMUM` | market-buy amount violates `amountPrecision` / `minAmount` |
| `OFFICIAL_CLI_FAILED`, `OFFICIAL_CLI_OUTPUT_NOT_JSON`, `OFFICIAL_CLI_MISMATCH` | CLI cross-check failed; the order is rejected |

Verified with live BTC_USDT rules: amount 5 -> `AMOUNT_BELOW_MINIMUM`; size 0.0000015 -> `SIZE_PRECISION`; size 0.00005 at ~81.7k -> `NOTIONAL_BELOW_MINIMUM`; price 81000.001 -> `PRICE_PRECISION`.

Not validated locally: the `buyCeiling`/`sellFloor` price band, available balance, open-order count limit, duplicate `clientOrderId`, and the clientOrderId character set. The exchange would reject these (`TRADE_PRICE_FILTER_DENIED`, `TRADE_NOT_ENOUGH_MONEY`, `TRADE_OPEN_ORDER_EXCEED_LIMIT`, `TRADE_REPEAT_CLIENT_ORDER_ID`); the paper engine does not simulate those rejections.

How the CLI cross-check stays safe: `official_cli_preview` runs `node .../dist/index.js --read-only orders new ... --dry-run` with an empty temporary `HOME`/`USERPROFILE` and every `PIONEX*` environment variable removed. The CLI's `--dry-run` branch prints `{tool, args}` and returns before any signing or network call (checked in the package source), and `--read-only` blocks writes besides.

## Paper fills (`pionex_lab/execution/paper.py`)

`PaperBroker.try_fill` fills only against a book ticker fetched at least `min_latency_ms` (250 ms) AFTER submission, limited by the depth snapshot near that quote (top-of-book size if none), with the unfilled remainder cancelled (entries are marketable LIMIT IOC; exits are MARKET sells). Fees: `fee_rate` (0.0005) on both sides. Candle highs and lows are never used to infer fills or queue position. Results are simulated: label them so, and never present paper or backtest results as evidence of profitability.

## What is forbidden

- Any signed request, any call to `/api/v1/trade/*`, `/api/v1/account/*`, `/api/v1/bot/*`, `/api/v1/wallet/*`, earn endpoints, or the private WebSocket.
- Running the CLI's `orders new|cancel|cancel_all`, `bot ... create|adjust_params|reduce|invest_in|cancel|profit`, `earn ... invest|revoke|collect|stake|unStake` WITHOUT `--dry-run` (without it, and with keys present, they are real). In this repo do not run them at all; use `dryrun.py`.
- Reading or writing keys, tokens, `.env*`, `~/.pionex/config.toml`, `var/account.json`; running `pionex-ai-kit onboard` or `setup`; registering the `pionex-trade-mcp` server.
- Editing `config/mandate.v1.json` or its lock, raising limits, enabling live, or running `review-latch` (agent-prohibited).
