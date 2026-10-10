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
when idle, and its default network policy blocks `api.pionex.com`. A session opened from the Claude
Desktop app can still be a cloud session. To let Claude do this on your PC, start a **Local**
session there (or run `claude remote-control` in a terminal) and ask it to run the line below.

**One line.** This installs everything, starts the lab in the background, and starts it again
after every logon or reboot. Re-running it updates the code and restarts the lab.

Windows (PowerShell):

```powershell
irm https://raw.githubusercontent.com/rgriesel/pionex/main/tools/install/windows.ps1 | iex
```

macOS / Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/rgriesel/pionex/main/tools/install/unix.sh | bash
```

What the installer does: it installs Python 3.12, Git, and Node.js LTS with `winget` if they are
missing (Windows; on macOS/Linux it needs Python 3.11+ and Git). It clones the repository into
`~/pionex` (`%USERPROFILE%\pionex`), installs the pinned official Pionex CLI, and runs `init`,
`verify`, and `capability`. It then starts `run` and registers auto-start: a per-user scheduled
task `PionexLab` at logon that restarts on failure (Windows; it also sets sleep on mains power to
"never"), or an `@reboot` crontab entry (macOS/Linux). Finally it opens the dashboard; on Windows it
also leaves a "Pionex Lab Dashboard" shortcut on the desktop. No API key is asked for or used.

After that nothing needs your input. `run` supervises the collector, paper engine and dashboard,
restarts any that exit, and once each UTC day (from 00:10 UTC, and no earlier than 15 minutes
after start so the history download can finish) runs `daily-review` and one research cycle. The
research cycle alternates between the 1-hour and 5-minute strategies by UTC day. It is skipped,
without spending the research budget, until there is enough history (20 days for 5-minute, 90 days
for 1-hour). Logs are in `var/logs/`. Stop it with `Stop-ScheduledTask -TaskName PionexLab`
(Windows) or `pkill -f 'pionex_lab run'` (macOS/Linux).

**Manual install.** Requirements: Python 3.11+ (standard library only), Git, and outbound HTTPS to
`api.pionex.com`. Optional: Node 18+ for Pionex's official dry-run CLI.

```bash
git clone https://github.com/rgriesel/pionex.git && cd pionex
npm ci --prefix tools/pionex-cli --ignore-scripts   # optional: official Pionex dry-run CLI (needs Node)
python3 -m pionex_lab init          # creates var/ (git-ignored): databases + dashboard token
python3 -m pionex_lab verify        # skill hashes, vendored risk gate, mandate lock, journal chain
python3 -m pionex_lab capability    # probes the public endpoints; writes var/capability/*.json
python3 -m pionex_lab run           # supervises collector + paper engine + dashboard + daily jobs
```

On Windows use `py -m pionex_lab …` instead of `python3 -m pionex_lab …`.

The official CLI is used only for `--dry-run` order previews. It is never given credentials and
never sends orders; without Node, a built-in renderer produces the same request.

`run` prints `dashboard (read-only) ready. Open locally: http://127.0.0.1:8765/#token=…`.
Open that URL in a browser on the same machine. The token is removed from the address bar and kept
only for that tab. If you lose the URL, rebuild it from `var/dashboard.token`:
`http://127.0.0.1:8765/#token=$(cat var/dashboard.token)` on macOS/Linux, or
`"http://127.0.0.1:8765/#token=" + (Get-Content var\dashboard.token)` in PowerShell.
The paper engine recovers its state from the journal on restart.

What happens on first start:

1. The collector backfills up to 420 days of 5-minute and 1-hour candles for BTC_USDT and ETH_USDT
   (Pionex stops at about 10,000 candles: ~35 days of 5-minute and ~417 days of 1-hour history;
   about 80 requests at the 5 requests/second local budget), then polls book tickers every 1s,
   depth every 3s, and candles every 20s. Failed backfills are retried every 10 minutes, and gaps
   after outages are refilled.
2. The paper engine enters `PAPER`. It starts the 30-day experiment clock only after all feeds are
   fresh and the bar history is complete. Until then it latches `DATA_STALE` and places no entries.
3. Research runs automatically once a day (see above). You can also run it by hand. It is limited
   to one cycle (at most 5 hypotheses) per UTC day across all timeframes:

   ```bash
   python3 -m pionex_lab research                   # 5-minute strategies
   python3 -m pionex_lab research --timeframe 1h    # hourly strategies (use a different UTC day)
   ```

   Pionex serves about 10,000 candles per interval: ~35 days of 5-minute candles but ~417 days of
   hourly candles, so the hourly variants (same ideas and frozen grids on 1-hour candles with 4-hour context, holding at most
   4 hours) can reach the 60-day out-of-sample requirement from existing history. The paper
   engine trades both sets: 5-minute strategies on each closed 5-minute candle, and hourly
   variants on each closed hour, built the same way as in research (4-hour context resampled
   from 1-hour candles). An hourly candle is acted on only within 5 minutes of its close, so a
   start or restart mid-hour waits for the next hour.

   Because ~35 days of Pionex 5-minute candles can never meet the 60-day out-of-sample gate,
   5-minute research runs on openly labelled **proxy-venue** history: `fetch-proxy` downloads
   Binance's public, checksummed kline archives (no account or key) into a separate
   `var/proxy_market.db`, never into Pionex's store. `research --data proxy` refuses the proxy
   (without spending the day's budget) unless it tracks Pionex's own bars closely (median close
   difference <= 5 bps, 5-minute return correlation >= 0.95); the cycle records the venue and the
   tracking evidence, and the dashboard names the venue. Costs stay Pionex fees and observed
   Pionex spreads, and a qualified candidate must still pass its paper trial on Pionex quotes.
   The daily automation alternates: 5-minute days refresh the proxy and research on it; hourly
   days research on Pionex's own hourly history.

   A hypothesis REJECTED in two cycles is retired from research (re-testing a frozen grid adds no
   information) but stays in the paper engine's shadow book. New hypotheses are pre-registered in
   `pionex_lab/strategies/catalog.py` with their date, rationale and bounded grid before any test:
   2026-10-06 added capitulation reversal, a Bollinger snapback scalp and a US-open breakout scalp
   (5-minute, holds <= 60 min for the scalps), plus hourly session drift and deep pullback.
   2026-10-08 added `funding_extreme_1h`, the first hypothesis on information other than OHLCV:
   `fetch-proxy` also stores Binance USD-M perpetual funding rates (public, labelled proxy venue)
   and hourly research attaches them to the bars. The live engine has no funding feed yet, so
   the hypothesis cannot signal there until one is added (only worth doing if it qualifies).
   2026-10-09 added `funding_settlement_bounce` (5-minute, holds <= 60 min): buy 5-15 minutes after
   an 8-hourly funding settlement whose rate was positive and in its top tail (crowded longs).
   2026-10-09 also added `elliott_abc_continuation_1h`: objective, point-in-time Elliott wave rules
   (k x ATR zigzag pivots known only once confirmed; 5-wave impulse obeying the three rules, ABC
   correction retracing 38.2-78.6%, buy the first close above the B high; optional RSI divergence).
   On 1h bars those rules fired once in ~417 days, so 2026-10-10 added the identical rules on
   5-minute bars as `elliott_abc_continuation` (still rare: ~47 signals a year across BTC and ETH).

   The engine reloads the frozen candidates within an hour (or on restart). A strategy can
   trade the paper book only if the risk gate accepts it. The gate needs a research-derived,
   search-adjusted edge above round-trip costs plus 5 bps. Otherwise the correct outcome is
   `NO_TRADE`, and every signal is still measured in a virtual shadow book.
4. Once per day, automatically: `daily-review` (reconciliation + attribution into the journal).

Other commands: `collect`, `paper`, `serve` (run the components separately); `status`; `report --out
report.json` (a snapshot file you can import into `dashboard/index.html` opened directly);
`live-preflight` (lists every live gate; always refuses); `record-cost --usd X --note …` (external
operating costs such as hosting — the mandate ceiling is $3 total).

Tests:

```bash
python3 -m unittest discover -s tests -v                                              # 65 tests
python3 -m unittest discover -s .claude/skills/pionex-trading-lab/scripts -p 'test_*.py' -v   # 12 skill tests
```

## Wave Lab (local Elliott Wave charting)

A local, read-only charting app modelled on Elliott Wave platforms such as WaveBasis. It runs on
your computer with the standard library only, and reads public Pionex market data. It needs no API
key and has no order path.

```bash
python3 -m pionex_lab waves --open          # http://127.0.0.1:8770/
python3 -m pionex_lab waves --feed demo     # offline: labelled SYNTHETIC prices, not market data
```

`--feed auto` (the default) uses Pionex public klines if `api.pionex.com` is reachable. Otherwise it
uses bars already collected in `var/market.db`, and then labelled demo data. The active source is
shown in the header badge, and demo data is shown in red.

Features:

- **Charts.** Canvas engine with pan, zoom, price-axis drag/zoom (double-click to reset), log scale,
  crosshair with OHLC legend, and PNG export. Nine timeframes (1m to 1D). Eight styles: candles,
  hollow, Heikin Ashi, OHLC, line, area, step and baseline. Light and dark themes.
- **Layouts.** 1, 2 side-by-side, 2 stacked, or a 2x2 grid. Each pane has its own timeframe, the
  symbol can be linked across panes, and the crosshair is synchronised.
- **Automatic wave counts.** Zigzag swings at Minor, Intermediate or Primary degree (or a manual
  swing %) are tested as 5-wave impulses and A-B-C zigzags or flats. Hard Elliott rules filter the
  candidates and guideline ratios score them. You get a primary count plus alternates, earlier
  completed patterns, the wave in progress, an invalidation level, and Fibonacci targets.
- **Smart tools.** Smart Fibs appear when you hover a wave label. There are also Elliott channels
  (0-2 and 2-4), support/resistance from pivot clusters, and swing pivots.
- **Indicators.** About 20 indicators plus volume: SMA, EMA, WMA, Bollinger, Keltner, Donchian,
  Ichimoku, Parabolic SAR, Supertrend, VWAP, RSI, MACD, the Elliott Wave Oscillator, Stochastic,
  Stochastic RSI, CCI, ATR, ADX/DMI, OBV, MFI, Williams %R and ROC. All parameters are editable.
- **Drawing tools.** Trend line, ray, horizontal and vertical lines, rectangle, Fibonacci
  retracement, trend-based Fibonacci extension, manual wave labels (1-5, A-B-C, W-X-Y), text, a
  measure tool and an eraser. A magnet option snaps to OHLC. Drawings can be selected, dragged or
  deleted, and are saved per symbol.
- **Watchlists.** Multiple lists with last price, 24h change and a sparkline. Each row also shows
  the wave in progress on 1H.
- **Wave scanner.** Scans a watchlist, a custom list or the top symbols across timeframes. Filters
  include in wave 3, in wave 5, a wave 2/4 pullback, wave B, wave C, a completed structure,
  direction and minimum score.
- **Alerts.** Price above/below, wave target reached, count invalidated, and wave-in-progress
  changed. They can notify by popup, sound, spoken voice or desktop notification, and have a log.
  Alerts are checked while the page is open.

Watchlists, drawings, alerts and settings are kept in the browser's local storage. The server binds
to 127.0.0.1 only, rejects foreign `Host` headers, and accepts no writes.

Wave counts are pattern hypotheses with known subjectivity. A score measures how closely the swing
ratios match textbook guidelines. It is not a probability, a forecast, a trade signal or evidence
of profitability.

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

* All 9 skill files installed, with SHA-256 verified; the skill's 12 risk tests pass; 65 project
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

1. **The continuous paper runtime needs a host that stays on.** Claude Code cloud sessions cannot
   host it: the container is temporary and its network policy blocks `api.pionex.com` (403 at its
   proxy). Run the one-line installer on your always-on PC. Until then, GitHub Actions runs the
   research side automatically on real Pionex data (Monday: 1-hour, Thursday: 5-minute strategies).
   Results appear in the run summaries of `pionex-public-data`. CI does not run the paper engine,
   because it is not a persistent host. The CI and PC research registries are kept separately; a
   candidate may trade the PC's paper book only if it qualifies in the PC's own registry.
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
4. **Server deployment.** The installers were tested end to end on Linux (runtime, dashboard, and daily
   jobs), and the Windows installer was parse-checked with PowerShell 7. The `deploy/systemd/`
   units (sandboxed, code and mandate root-owned and read-only for the service user) are an
   alternative for servers, but they were not exercised in this environment.
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
