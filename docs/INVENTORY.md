# Pionex Trading Lab: inventory

Prepared 2026-10-13 for the owner. Everything here is research or paper (simulated) trading. Nothing places a live order (`config\mandate.v1.json` has `live_enabled: false`). The separate Pionex Trader can place real bots, but only after you click Confirm. Sizes are approximate. Private files (`.env`, `var\account.json`, `var\dashboard.token`) were not opened.

## 1. Main repository: `C:\Users\Desj Griesel\pionex`

Public on GitHub (rgriesel/pionex). The `var\` data folder is git-ignored.

| What | Where | What it does | Status |
|---|---|---|---|
| Lab code | `pionex_lab\` | Collects data, researches, paper trades, checks risk, builds reports | Running |
| Swing research | `pionex_lab\swing\` | Nine research modules, see section 2 | Research and paper |
| Tests | `tests\` | Automated checks | Not run for this inventory |
| Lab dashboard | `dashboard\`, `tools\build_dashboard.py` | Read-only progress page; edit the builder, not the page | Running on port 8765 |
| Wave Lab | `wavelab\`, `pionex_lab\waves\` | Elliott-wave counting site and alerts | Running on port 8770 |
| TradingView scripts | `tradingview\` | `wl_oscillator.pine`, `wl_trend_filter.pine` | Ready to paste |
| Rules | `config\` | Mandate (limits, live off) and its lock | Hash-checked by the engine at start. The settings rules that blocked agents from editing it were removed on 2026-10-10; restoring them is recommended (see `docs\FIRM.md`) |
| Docs | `docs\` | `mandate_v2_swing_proposal.md`, a proposed swing sleeve | Waiting for your decision |
| Agent setup | `.claude\` | Lab skill, settings, five agent definitions | `agents\` is new and not in git yet |
| Installers, CI | `tools\install\`, `.github\`, `deploy\` | One-line installer, GitHub workflows, Linux service files | Reference |

## 2. Swing research: `pionex_lab\swing\`

| What | Where | What it does | Status |
|---|---|---|---|
| btc_swing | `btc_swing.py` | Tests a fixed BTC swing checklist for your own futures trades | Research; no orders |
| guidance | `guidance.py` | Records YouTube channels' BTC calls, then scores them on later moves | 3 calls logged |
| osc_study | `osc_study.py` | Tests whether the WL Oscillator has an edge on BTC | v1 failed; v2 saved |
| carry | `carry.py` | Measures what a spot-buy plus futures-short "funding carry" would pay | Research; outside lab rules |
| trend | `trend.py` | Checks whether a daily trend filter beats holding BTC or ETH | Research; results saved |
| zoo | `zoo.py` | Walk-forward test of popular public strategies on BTC | Research; results saved |
| factors | `factors.py` | Screens market signals against BTC's next 4, 24 and 72 hours | Research; results saved |
| cta | `cta.py` | Trend-following basket across 10 Pionex coins | Pre-registered test passed (backtest) |
| swing_book | `swing_book.py` | Runs the CTA basket forward with 100 USDT of paper money | Paper only; starts 2026-10-14 |

Backtests and paper results are research only, not proof of profit.

## 3. Runtime data: `C:\Users\Desj Griesel\pionex\var\` (not in git, about 2.1 GB)

| What | Where | What it does | Status |
|---|---|---|---|
| Market candles | `market.db` | Pionex price and candle data, 207 MB | Active, written 23:21 |
| Proxy history | `proxy_market.db` | Binance history used as a labelled stand-in, 207 MB | Active, 22:13 |
| Order-book depth | `orderbook\depth.db` | Binance futures depth archive (proxy), 563 MB | Active, 22:45 |
| Live order book | `orderbook\live.db` | Minute-by-minute recorder | Active, 23:24 |
| Your account copy | `account.db` | Read-only copy of your Pionex account for the dashboard, 133 MB. Private | Active, 23:24 |
| Paper ledger | `ledger.db` | Paper trade journal, append-only, 20 MB | Active, 22:40 |
| Risk and research | `risk.db`, `research.db` | Risk service state; registry of every trial and rejection | Risk active 22:25; research last 10-11 |
| Alternative data | `alpha\alt.db`, `alts_1h.db` | Fear and Greed, stablecoin and alt-coin data, 34 MB | Active, 23:23 |
| Fibonacci strategy | `fib\` | Your private 1-minute BTC strategy, scripts and results, 76 MB. Kept out of git on purpose | Last written 21:57 |
| Kronos AI test | `kronos\` | Forecast-model test: repo, packages, model cache, `forecasts.json`, 866 MB | forecasts 23:23; log empty |
| Video tools | `tools\` | yt-dlp 2026.8.19 and subtitles for one video, 21 MB | Installed |
| Results, logs, paper books | `reports\`, `logs\`, `swing_book\` | Output of each research run (14 files); 30 log files; defensive and growth paper books | Active; books start 10-14 |
| Small extras | `guidance\btc_calls.jsonl`, `capability\`, `wave_alerts.db` | The 3 logged YouTube calls; Pionex capability and fee checks (Sept); Wave Lab alerts | Static |

## 4. Pionex Trader (separate app)

| What | Where | What it does | Status |
|---|---|---|---|
| Pionex Trader | `C:\Users\Desj Griesel\pionex-trader\` | Panel for Pionex futures grid bots. Every change is Check, then Confirm. Caps: $100 total, 3x leverage, stop loss required | Running on port 8780 |

## 5. What is running

| What | Where | What it does | Status |
|---|---|---|---|
| Lab dashboard | port 8765 | Read-only progress page | Listening; likely the PionexLab process |
| Wave Lab | port 8770 | Wave counting site | Listening since 10-12 16:11 |
| Pionex Trader | port 8780 | Bot panel | Listening since 10-11 17:49 |
| PionexLab task | Windows Task Scheduler | 24/7 paper-lab supervisor | Running since 10-11 14:41 |
| Assistant-session jobs | assistant session | Order-book recorder (every minute), Kronos test, daily reports at 02:17, 02:53, 07:52 and 21:43 | Reported, not checked here; stop if the session closes |

## 6. What changed recently (last 15 commits on main)

| Commit | Change |
|---|---|
| 334a2b4 | Growth paper book beside the defensive one; zoo pooled 4h test |
| 70bea42 | CTA trend basket (passed its pre-registered test), paper swing book, mandate v2 proposal |
| 5b5b820 | Factors: any-coin build, ETH replication, fixed combo; live depth recorder |
| 6b52215 | Edge search: strategy zoo, order-book depth, alt data, factor engine |
| 09c6f4b | TradingView WL Trend Filter (daily EMA50, long only, flip alerts) |
| 76c1afa | TradingView WL Oscillator in Pine v6, with install notes |
| f0f96cb | TradingView WL Oscillator as a private Pine script |
| 2aff441 | Wave Lab WL Oscillator gets the Pro modes |

The other seven of the last 15 are branch-merge commits. Two more untracked files appeared in `docs\` during this run (`FIRM.md`, `STRATEGY_LOG.md`); they are not reviewed here.

## 7. Where to look first

1. **Lab dashboard**: http://127.0.0.1:8765/ (this PC only; data calls need the token in `var\dashboard.token`)
2. **Wave Lab**: http://127.0.0.1:8770/
3. **Paper swing book state**: `var\swing_book\state.json` (defensive) and `state_growth.json` (growth). Starts 2026-10-14; no positions yet.
4. **Reports folder**: `var\reports\`
5. **Mandate v2 proposal**: `docs\mandate_v2_swing_proposal.md`. A proposal only; nothing is applied.
