# Pionex Trading Lab

A bounded, **paper-only** Pionex spot-trading experiment built from the installed
`pionex-trading-lab` skill (`.claude/skills/pionex-trading-lab/`, verified from
`Pionex-Claude-Code-Handoff.json`). It collects public market data, researches four
interpretable hypotheses under a fixed evidence protocol, paper-trades through an independent
risk service, records everything in an append-only hash-chained ledger, and shows progress on a
read-only local dashboard.

> This software does not create an institutional trading capability and does not guarantee any
> return. The $1,000 stretch target is a comparison line, never a reason to take more risk. A
> backtest or a stop rule does not guarantee a loss limit. Live trading is disabled.

## Start it (exact commands)

Requirements: Python 3.11+ (standard library only), outbound HTTPS to `api.pionex.com`.
Optional: Node 18+ for Pionex's official dry-run CLI.

```bash
git clone https://github.com/rgriesel/pionex.git && cd pionex
git checkout claude/pionex-trading-app-build-qtxo88

# Optional, recommended: pinned official Pionex CLI, used only for `--dry-run` order previews.
# It is never given credentials and never sends orders.
npm ci --prefix tools/pionex-cli --ignore-scripts

python3 -m pionex_lab init          # creates var/ (git-ignored): databases + dashboard token
python3 -m pionex_lab verify        # skill hashes, vendored risk gate, mandate lock, journal chain
python3 -m pionex_lab capability    # probes the public endpoints; writes var/capability/*.json
python3 -m pionex_lab run           # supervises collector + paper engine + dashboard
```

`run` prints `dashboard (read-only) ready. Open locally: http://127.0.0.1:8765/#token=…`.
Open that URL in a browser on the same machine. The token is removed from the address bar and kept
only for that tab. If you lose the URL, use
`http://127.0.0.1:8765/#token=$(cat var/dashboard.token)`. Stop everything with Ctrl-C.

What happens on first start:

1. The collector backfills 150 days of 5-minute and 1-hour candles for BTC_USDT and ETH_USDT
   (about 200 requests at the 5 requests/second local budget), then polls book tickers every 1s,
   depth every 3s, and candles every 20s. Failed backfills are retried every 10 minutes, and gaps
   after outages are refilled.
2. The paper engine enters `PAPER`. It starts the 30-day experiment clock only after all feeds are
   fresh and the bar history is complete. Until then it latches `DATA_STALE` and places no entries.
3. Run research once history exists. It is limited to one cycle per UTC day:

   ```bash
   python3 -m pionex_lab research
   ```

   The engine reloads the frozen candidates within an hour (or on restart). A strategy can
   trade the paper book only if the risk gate accepts it. The gate needs a research-derived,
   search-adjusted edge above round-trip costs plus 5 bps. Otherwise the correct outcome is
   `NO_TRADE`, and every signal is still measured in a virtual shadow book.
4. Once per day: `python3 -m pionex_lab daily-review` (reconciliation + attribution into the journal).

Other commands: `collect`, `paper`, `serve` (run the components separately); `status`; `report --out
report.json` (a snapshot file you can import into `dashboard/index.html` opened directly);
`live-preflight` (lists every live gate; always refuses); `record-cost --usd X --note …` (external
operating costs such as hosting — the mandate ceiling is $3 total).

Tests:

```bash
python3 -m unittest discover -s tests -v                                              # 56 tests
python3 -m unittest discover -s .claude/skills/pionex-trading-lab/scripts -p 'test_*.py' -v   # 12 skill tests
```

## Paper trading with the Pionex dry-run feature

Pionex's official AI Kit CLI (`@pionex/pionex-ai-kit`, pinned to 0.2.55 in `tools/pionex-cli`) has
`pionex-trade-cli orders new … --dry-run`. Its source shows that it prints the resolved
`POST /api/v1/trade/order` request body and returns **without contacting the exchange**. So it
produces no fills, balances, or exchange-side validation. This app uses it as follows:

* Every paper order (entry `LIMIT` + `IOC`, exit `MARKET` sell by base size) is rendered with the
  official tool's field rules, validated against the symbol's precision and minimums, and then
  cross-checked against the official CLI's own `--dry-run` output. A mismatch rejects the order.
  The CLI runs with `--read-only`, an empty `HOME`, and no `PIONEX_*` variables.
* The request is journaled with `"sent": false`. Fills are simulated separately. They use only a
  quote observed **after** submission and are limited by the recorded depth. Fees are charged on
  both sides.
* Without Node, a built-in renderer produces the same body, and the journal records which source
  was used.

## Architecture

| Component | Code | Boundary |
|---|---|---|
| Exchange adapter | `pionex_lab/exchange/` | Public GET endpoints only; strict parsers fail closed; 5 weight/s budget with exit headroom; honors 429/418 bans |
| Collector | `pionex_lab/data/collector.py`, `store.py` | Only process that calls the exchange; sole writer of `market.db` |
| Data quality | `pionex_lab/data/quality.py` | Completed bars only, gaps, OHLC validity, freshness |
| Strategies | `pionex_lab/strategies/catalog.py` | Volatility breakout, trend pullback, range reversion, relative strength; long or cash; stop/target/≤4h time exit declared up front |
| Research | `pionex_lab/research/` | Next-open execution, stop-first ambiguity, gap fills, trade-through targets, both-side costs, purge + embargo, 3 walk-forward folds + untouched test, Bonferroni-adjusted block bootstrap, cost/delay/missed-fill stress; every trial kept in `research.db` |
| Risk service | `pionex_lab/risk/service.py` | Limits only from the hash-locked mandate; the skill's reference gate is used byte-identical; persistent latches and UTC baselines; atomic reservations; lease + fencing token; narrow proposal schema (no limits, balances, edge, or qualification fields) |
| Paper execution | `pionex_lab/execution/paper.py`, `dryrun.py` | Simulated fills on later quotes; dry-run request previews |
| Live gate | `pionex_lab/execution/live.py` | No live path exists; `live-preflight` lists each failing gate |
| Ledger | `pionex_lab/ledger/` | Append-only SQLite journal with SHA-256 chain; the book is derived by replay and reconciled every minute |
| Engine | `pionex_lab/runtime/engine.py` | Single writer; exits never blocked by entry halts; shadow books; snapshots; BTC buy-and-hold benchmark; deadline unwind and frozen final report |
| Dashboard | `pionex_lab/reporting/`, `dashboard/index.html` | Built from the skill template by `tools/build_dashboard.py`; token-authenticated, read-only, localhost-bound; labels show connected versus snapshot versus test feed |

## Risk mandate (preserved as delivered)

`config/mandate.v1.json` is byte-identical to the skill's `assets/mandate.json`. It is locked by
SHA-256 in `config/mandate.lock.json`, the Claude Code settings deny edits to it, and it is
checked again every minute. A change latches `POLICY_TAMPER`.

| Control | Limit |
|---|---|
| Market | Unleveraged spot, long or cash |
| Planned loss per trade (incl. costs) | 0.50% of equity (0.25% canary) |
| Aggregate planned loss incl. pending | 1.00% of equity |
| Position notional / gross exposure | 25% / 50% of equity |
| Concurrent positions | 2 |
| Daily / weekly loss latch | 2% of UTC day start / 4% of UTC Monday start |
| Peak drawdown / absolute loss | 10% / USD 10 fixed (never compounded) |
| Operating spend | USD 3 total; paid services disabled |

Daily and weekly latches clear only after their period ends and all checks pass. Peak-drawdown,
absolute-loss, tamper, and unexplained-balance latches need a human `review-latch` decision. That
command requires an interactive terminal, and Claude Code is denied it. Loss latches unwind open
positions, and exits keep working while entries are halted.

## Status as of 2026-09-28

Working and verified in the build environment:

* All 9 skill files installed, with SHA-256 verified; the skill's 12 risk tests pass; 56 project
  tests pass.
* End-to-end runs against a local **synthetic** fake exchange (`tests/fake_pionex.py`) exercise
  collection, backfill, the entry, fill, exit, and close lifecycle, restart recovery with lease
  fencing, loss-latch unwinding, stale-feed freezing with the 60-second recovery rule, 429 bans,
  gap repair, deadline unwind, and the final report.
* Dry-run previews cross-checked against the official `pionex-trade-cli` 0.2.55.
* Dashboard checked in headless Chromium at desktop and phone widths while connected to a ledger
  server. Unauthenticated API calls get 401; writes get 405.

Not yet verified, and the remaining blockers:

1. **Real Pionex data.** The cloud build environment's network policy blocks `api.pionex.com`
   (403 at the proxy), so no real quotes have been collected yet and no real paper result exists.
   Run it on your own machine, or allow `api.pionex.com` in the environment's network settings.
   On the first real run, check `python3 -m pionex_lab capability` and compare the saved fixtures
   with the parsers. The response fields follow Pionex's docs and official AI Kit but have not been
   observed from here.
2. **No qualified strategy.** Qualification needs at least 200 out-of-sample trades over at least
   60 days, plus profit-factor, confidence-bound, and stress gates. Expect `NO_TRADE` until research
   on real history says otherwise. It may never say so, and that is a legitimate result.
3. **Live trading stays disabled** (15 gates; 1 passes). Missing: your authorization record for
   the exact account, capital, instruments, and mandate hash; a dedicated or segregated account; a
   live symbol allowlist; verified account fees; exchange-side protective exits (the spot API
   documents only LIMIT/MARKET); a server-side secret store and separate signer; separate service
   identities; reconciliation against the exchange; a canary path; and paper evidence (72 hours
   AND 50 closed trades with the frozen qualified candidate).
4. **24/7 hosting.** The `deploy/systemd/` units (sandboxed, code and mandate root-owned and read-only
   for the service user) are provided but were not exercised in this environment.
5. **USD valuation** assumes 1 USDT = 1 USD. This is labeled everywhere; the USDC_USDT cross
   latches `QUOTE_DEPEG` if it moves beyond 1%.
6. **Human comparison** is unavailable until a dated human ledger for the same window is supplied.

## Credentials

Paper trading needs **no API key**. Do not paste keys into chat, source, or the dashboard. Do not
reuse a key from another project: a key that reaches unrelated funds fails the capital-boundary
gate. If live trading is ever authorized, create a dedicated sub-account key with read/trade only,
IP-restricted, and no withdrawal permission. Keep it in a server-side secret store readable only by
a separate signer service. That signer is not part of this build.

## Deploying on a server (systemd)

```bash
sudo useradd --system --home /var/lib/pionex-lab pionex-lab
sudo mkdir -p /opt/pionex-lab /var/lib/pionex-lab && sudo chown pionex-lab: /var/lib/pionex-lab
sudo rsync -a --exclude var/ ./ /opt/pionex-lab/ && sudo chown -R root:root /opt/pionex-lab   # code + mandate read-only
sudo cp deploy/systemd/*.service /etc/systemd/system/
(cd /opt/pionex-lab && sudo -u pionex-lab PIONEX_LAB_VAR=/var/lib/pionex-lab python3 -m pionex_lab init)
sudo systemctl daemon-reload
sudo systemctl enable --now pionex-lab-collector pionex-lab-paper pionex-lab-dashboard
```

The dashboard binds to 127.0.0.1. For remote viewing, use an SSH tunnel
(`ssh -L 8765:127.0.0.1:8765 host`) or an authenticated TLS reverse proxy. The existing hosted
ChatGPT report viewer is a private viewer only; it cannot connect to this ledger.
