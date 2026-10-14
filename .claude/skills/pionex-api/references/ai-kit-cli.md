# Official Pionex AI Kit, CLI, MCP server and skills

Pionex publishes an official toolkit (GitHub org `pionex-official`, MIT): https://github.com/pionex-official/pionex-ai-kit . It has three parts.

| Part | What it is | Use in this repo |
|---|---|---|
| `@pionex/pionex-ai-kit` (npm) | CLI package. Binaries `pionex-ai-kit` (onboard, setup) and `pionex-trade-cli` (market, account, wallet, orders, bot, earn) | Pinned at 0.2.55 in `tools/pionex-cli/` (`package.json`, `node_modules`). Used for PUBLIC market commands and order `--dry-run` previews only |
| `@pionex/pionex-trade-mcp` | MCP server exposing the same tools to MCP clients; reads credentials from `~/.pionex/config.toml` | NOT installed and must not be registered here (needs keys and exposes order tools) |
| `pionex-official/pionex-skills` | Markdown skills (`pionex-market`, `pionex-portfolio`, `pionex-wallet`, `pionex-trade`, `pionex-bot`, `pionex-earn-dual`, `pionex-earn-arbitrage`) | Read for ideas. Only `pionex-market` is relevant (public). Do not install the others |

Related: `pionex-official/pionex-open-api` (OpenAPI 3 YAML specs: `openapi.yaml` Trade API, `websocketapi.yaml`, `openapi_bot.yaml`, `openapi_futures.yaml`, wallet, earn, partner), `pionex-official/ccxt` (a ccxt fork). The OpenAPI YAML is the machine-readable source for exact field types: https://github.com/pionex-official/pionex-open-api .

## Running the pinned CLI safely

Node 18+ required (Node 24 installed). The entry point is `tools/pionex-cli/node_modules/@pionex/pionex-ai-kit/dist/index.js`. The CLI's credential lookup order is env `PIONEX_API_KEY` / `PIONEX_API_SECRET` / `PIONEX_BASE_URL`, then `~/.pionex/config.toml`. To make sure no key can be loaded, run it exactly as `dryrun.py` does: empty `HOME`/`USERPROFILE` and no `PIONEX*` variables, always with `--read-only`.

```bash
# Git Bash, from the repo root. Public data needs no credentials.
T=$(mktemp -d)
for v in $(env | grep -i '^PIONEX' | cut -d= -f1); do unset $v; done
export HOME="$T" USERPROFILE="$T"
CLI=tools/pionex-cli/node_modules/@pionex/pionex-ai-kit/dist/index.js
node $CLI --read-only market klines BTC_USDT 1D --limit 2        # verified 2026-10-14
node $CLI --read-only market book_tickers --symbol BTC_USDT      # verified
node $CLI --read-only market symbols --symbols BTC_USDT          # verified
node $CLI --read-only market depth BTC_USDT --limit 5            # verified
node $CLI --read-only market trades BTC_USDT --limit 10          # verified
node $CLI --read-only market tickers --symbol BTC_USDT           # verified
node $CLI --read-only capabilities                                # JSON list of ALL commands, offline (verified)
```

In Python, prefer `PionexPublic`; the CLI adds nothing for market data except an independent cross-check. CLI output is the same JSON envelope (`result`, `data`, `timestamp`).

Global flags: `--profile <name>`, `--modules <list>` (market,account,wallet,orders,bot,earn), `--base-url <url>`, `--read-only` (disables write tools), `--dry-run` (prints the resolved request body for write commands; verified to return before any config load or network call).

## Market command syntax [official-doc: manual/cli/cli-guides-trade.md; verified]

| Command | Notes |
|---|---|
| `market depth <symbol> [--limit n]` | limit 1 to 100, default 5 (REST itself allows more) |
| `market trades <symbol> [--limit n]` | limit 1 to 100 (REST allows 500) |
| `market symbols [--symbols a,b] [--type SPOT\|PERP]` | trading rules |
| `market tickers [--symbol s] [--type SPOT\|PERP]` | 24h stats |
| `market book_tickers [--symbol s] [--type SPOT\|PERP]` | best bid/ask |
| `market klines <symbol> <interval> [--endTime ms] [--limit n]` | intervals 1M 5M 15M 30M 60M 4H 8H 12H 1D |

## Tool inventory of the installed package (v0.2.55, 52 tools; names `pionex_<area>_<action>`)

- Market (public, safe): `pionex_market_get_depth`, `_get_trades`, `_get_symbol_info`, `_get_tickers`, `_get_book_tickers`, `_get_klines`.
- Private reads (need keys; do not use): `pionex_account_get_balance`, `pionex_wallet_get_balance_full`, `pionex_orders_get_order`, `_get_order_by_client_order_id`, `_get_open_orders`, `_get_all_orders`, `_get_fills`, `_get_fills_by_order_id`, `pionex_bot_*_get_order`, `pionex_bot_*_check_params`, `pionex_bot_spot_grid_get_ai_strategy`, `pionex_bot_order_list`, `pionex_earn_*` read tools.
- Write tools (20; flagged `isWrite`; FORBIDDEN here): `pionex_orders_new_order`, `_cancel_order`, `_cancel_all_orders`, `pionex_bot_futures_grid_create|adjust_params|reduce|cancel`, `pionex_bot_spot_grid_create|adjust_params|invest_in|cancel|profit`, `pionex_bot_smart_copy_create|cancel`, `pionex_bot_signal_listener`, `pionex_earn_dual_invest|revoke_invest|collect`, `pionex_earn_arbitrage_stake|un_stake`.

The GitHub README (newer than the pinned copy) also lists user-signal CRUD tools. The README of the pinned copy says: "CLI for Pionex MCP: initializes credentials in ~/.pionex/config.toml." Updating the pin is a lead decision: check the new dist for new write paths and re-run `py -m unittest discover -s tests` first.

## Order dry-run through the CLI

```bash
node $CLI --read-only orders new --symbol BTC_USDT --side BUY --type LIMIT --price 81000 --size 0.0002 --client-order-id demo-1 --dry-run
# prints {"tool":"pionex_orders_new_order","args":{...}}  and exits; nothing is sent (verified 2026-10-14)
```

Flags: `--symbol --side BUY|SELL --type MARKET|LIMIT --amount --size --price --client-order-id --IOC --dry-run`. Without `--dry-run` this command is a real order when keys exist. In this repo go through `pionex_lab/execution/dryrun.py` instead (`order-previews.md`).
