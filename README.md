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

Run it on a computer that stays on and can reach `api.pionex.com`, such as your own always-on PC.
A Claude Code *cloud* session cannot host it: it runs in a temporary container that is reclaimed
when idle and cannot reach Pionex. (A session opened from the Claude Desktop app can still be a
cloud session; check that it runs on your computer before asking it to start the bot.)

Requirements: Python 3.11+ (standard library only), Git, outbound HTTPS to `api.pionex.com`.
Optional: Node 18+ for Pionex's official dry-run CLI.

**Windows (PowerShell).** Install Python from python.org (tick "Add python.exe to PATH") and Git
for Windows, then:

```powershell
git clone https://github.com/rgriesel/pionex.git
cd pionex
npm ci --prefix tools/pionex-cli --ignore-scripts   # optional: official Pionex dry-run CLI (needs Node)
py -m pionex_lab init
py -m pionex_lab verify
py -m pionex_lab capability
py -m pionex_lab run
```

**macOS / Linux.**

```bash
git clone https://github.com/rgriesel/pionex.git && cd pionex
npm ci --prefix tools/pionex-cli --ignore-scripts   # optional: official Pionex dry-run CLI (needs Node)
python3 -m pionex_lab init          # creates var/ (git-ignored): databases + dashboard token
python3 -m pionex_lab verify        # skill hashes, vendored risk gate, mandate lock, journal chain
python3 -m pionex_lab capability    # probes the public endpoints; writes var/capability/*.json
python3 -m pionex_lab run           # supervises collector + paper engine + dashboard
```

The official CLI is used only for `--dry-run` order previews. It is never given credentials and
never sends orders; without Node, a built-in renderer produces the same request.

`run` prints `dashboard (read-only) ready. Open locally: http://127.0.0.1:8765/#token=…`.
Open that URL in a browser on the same machine. The token is removed from the address bar and kept
only for that tab. If you lose the URL, rebuild it from `var/dashboard.token`:
`http://127.0.0.1:8765/#token=$(cat var/dashboard.token)` on macOS/Linux, or
`"http://127.0.0.1:8765/#token=" + (Get-Content var\dashboard.token)` in PowerShell.
Stop everything with Ctrl-C.

Keep it running: leave the window open and set the computer's sleep to "never" (sleep pauses the
bot even when the power stays on). To restart it automatically after a reboot, use Task Scheduler
on Windows ("At log on", program `py`, arguments `-m pionex_lab run`, start in the `pionex`
folder) or the systemd units below on Linux. The paper engine recovers its state from the journal
on restart.

What happens on first start:

1. The collector backfills 150 days of 5-minute and 1-hour candles for BTC_USDT and ETH_USDT
   (about 200 requests at the 5 requests/second local budget), then polls book tickers every 1s,
   depth every 3s, and candles every 20s. Failed backfills are retried every 10 minutes, and gaps
   after outages are refilled.
2. The paper engine enters `PAPER`. It starts the 30-day experiment clock only after all feeds are
   fresh and the bar history is complete. Until then it latches `DATA_STALE` and places no entries.
3. Run research once history exists. It is limited to one cycle (at most 5 hypotheses) per UTC
   day across all timeframes:

   ```bash
   python3 -m pionex_lab research                   # 5-minute strategies
   python3 -m pionex_lab research --timeframe 1h    # hourly strategies (use a different UTC day)
   ```

   Pionex serves only ~35 days of 5-minute candles but much longer hourly history, so the hourly
   variants (same ideas and frozen grids on 1-hour candles with 4-hour context, holding at most
   4 hours) can reach the 60-day out-of-sample requirement from existing history. Hourly variants
   are research-only for now; the paper engine trades the 5-minute set.

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
python3 -m unittest discover -s tests -v                                              # 62 tests
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

## Status as of 2026-09-29

Working and verified:

* All 9 skill files installed, with SHA-256 verified; the skill's 12 risk tests pass; 62 project
  tests pass, locally and in GitHub Actions (`.github/workflows/tests.yml`).
* **Real Pionex public data:** the manual workflow `pionex-public-data` (GitHub Actions run
  36547328965) reached `api.pionex.com`. Every parser accepted the live symbols, book-ticker,
  depth, kline, and trade responses (clock skew 86 ms, latency 231 ms).
* End-to-end runs against a local **synthetic** fake exchange (`tests/fake_pionex.py`) exercise
  collection, backfill, the entry, fill, exit, and close lifecycle, restart recovery with lease
  fencing, loss-latch unwinding, stale-feed freezing with the 60-second recovery rule, 429 bans,
  gap repair, the venue history limit, deadline unwind, and the final report.
* Dry-run previews cross-checked against the official `pionex-trade-cli` 0.2.55.
* Dashboard checked in headless Chromium at desktop and phone widths while connected to a ledger
  server. Unauthenticated API calls get 401; writes get 405.

First research cycle on real Pionex history (2026-09-29, about 34.7 days of 5-minute candles).
This is evidence **against** the current hypotheses, not a forecast:

| Hypothesis | Out-of-sample trades | Mean net per trade | Result |
|---|---:|---:|---|
| Volatility breakout | 30 | −26.9 bps | Rejected |
| Trend pullback | 38 | −12.3 bps | Rejected |
| Range reversion | 70 | −16.4 bps | Rejected |
| Relative strength | 135 | −14.6 bps | Rejected |

The paper engine therefore makes `NO_TRADE` decisions and measures every signal in shadow books.

Remaining blockers:

1. **This cloud session cannot reach `api.pionex.com`** (403 at its proxy). The paper runtime needs
   a host that can: your machine, a server, or this environment after `api.pionex.com` is allowed in
   its network settings. GitHub Actions can reach it, but CI is not a persistent host.
2. **The out-of-sample evidence window is limited by the venue.** Pionex serves about 10,000
   five-minute bars (~34.7 days), so the 60-day out-of-sample gate cannot be met from exchange
   history alone. The collector must keep collecting going forward (roughly 3+ months of continuous
   running). Alternatively, hourly-resolution hypotheses can use the longer 60M history; that is a
   research design choice for you, and the gates stay unchanged either way.
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
