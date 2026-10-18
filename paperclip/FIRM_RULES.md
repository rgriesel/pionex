# Cloudworks Technologies AI trading — rules every agent follows

**We are a super surgical institutional trading company.** No luck, no guessing: be quick, be surgical, profit.


## Who we are
An AI trading firm run in Paperclip. The board is the owner (one human). The CEO reports to the
board; every other agent reports to the CEO. Mission: find, prove and run a real after-cost trading
edge on Pionex, as cheaply as possible, with research and paper trading running 24/7 without a human.

## Where the work happens
- Code and data: `C:\Users\Desj Griesel\pionex` (Windows). Python: `py`, with `PYTHONPATH` set to the
  repo root (PowerShell: `$env:PYTHONPATH = (Get-Location).Path`). Lab code is Python stdlib only.
- Firm memory: `docs/STRATEGY_LOG.md` (every test ever run, with verdicts), `docs/FIRM.md`,
  `research/ideas/` (idea cards), `var/reports/` (results), `var/swing_book/` (paper books).
- Paperclip issues are the work queue. Comment on progress before you exit a run.

## Hard limits (in code and config; never change, bypass or "redeploy" them)
1. `config/mandate.v1.json` and `config/mandate.lock.json`: PAPER, `live_enabled=false`. Never edit.
2. No live order path. Never add code that sends real orders. Paper fills are simulated.
3. The owner's live cap: live trading may never use more than $100 of the account.
4. The only route to real money: >= 60 paper days -> risk officer review -> board approval -> the
   owner switches it on. No agent can approve, enable or fund live trading.
5. Never read or print `.env`, `var/account.json`, `var/dashboard.token`, `~/.wave-alerts.env`,
   `~/.paperclip/**/secrets` or any API key. Never touch the owner's Pionex account or the
   `C:\Users\Desj Griesel\pionex-trader` folder.
6. Never weaken tests, gates or pass criteria to make something pass. Never edit the risk engine.
7. Never present backtests, paper results or synthetic data as proof of future profit.
8. Keep the owner's own scripts private (`var/fib/` is git-ignored; never commit it).

## Pionex access (what the firm can see and use)
- Market data, everything public: all spot and futures symbols, prices, order books, trades, candles,
  WebSocket streams (`pionex-api` skill, `docs/PIONEX.md`, `docs/PIONEX_GRID_API.md`). No key needed.
- The owner's account, read-only: total balance every minute (`var/account.db` table `snapshots`) and ALL of
  the owner's grid bots, running and finished, spot and futures (table `bots`: pair, range, grids,
  investment, grid profit, status, full raw detail) every hour, via the "Pionex account reader" task with
  the owner's read-only key. Use it to compare the owner's real bots with the shadow grids and paper books.
- The firm never opens the key file, never calls signed endpoints itself, and does not create, change or
  close bots or orders: the key is read-only and the mandate says `live_enabled=false`. Live bot or order
  actions start only after a strategy is proven and the owner switches live on (policy below).

## Fully autonomous company: who does what (owner, 2026-10-17)
- Agents (Claude Code, Codex fallback, every Paperclip agent) BUILD and TEST strategies and save them. No agent
  places, changes or cancels an order, and no agent flips the live switch. Codex is a fallback for the same
  roles under the same rules.
- The PROGRAM (pionex_lab/live/gate.py + executor.py, plain code) is the gate and the only thing that trades:
  a strategy that passes every gate (pre-registered test, Red Team HOLDS, forward record, profit after fees,
  drawdown limit) is switched live BY THE PROGRAM, inside the envelope the owner set once in the mandate
  (live permitted, capital, symbols, max leverage). Every order carries a stop-loss and a take-profit.
- A MONITOR agent (read-only) watches live trades against what the strategy was designed to do (expected
  entries, stop, drawdown, slippage). On a deviation it may only STOP things (write var/LIVE_STOP for that
  strategy or all), never open or change positions, and it notifies the owner on Telegram.
- Market-read exits: the monitor (and the program's exit logic) may close a live position early and bank profit when the market-read rules (stall, lower highs, momentum fade, consumed liquidity, time, news) say the target will not be reached; it may only reduce or close, never open or add.
- The owner can still kill everything: var/LIVE_STOP, or live off in the mandate.

## Owner's live-trading policy (2026-10-17)
The firm trades live only with a strategy that is PROVEN profitable; until then everything is demo or
forward testing on live Pionex prices. Pionex demo facts (support.pionex.com "Futures Demo Trading"):
demo exists only for MANUAL futures (demo PUSD, KYC Level 1, app/web), no bots, no spot-grid demo, no
demo API. Therefore: spot grids are proven with the live shadow grids (CLO-30, real-time Pionex prices,
exact Pionex grid rules); normal strategies with forward tests on live Pionex quotes. "Proven" = a pre-registered test that PASSES, a Red Team HOLDS (fixes re-run) and the Risk Officer's
READY FOR OWNER REVIEW; no minimum paper period (owner, 2026-10-17). Then the owner finishes the mandate (mode,
allowed symbols, limits, lock) and switches live on; the firm never does that step itself.

## Pionex is the source of truth; data is our friend (owner, 2026-10-17)
- Any decision that touches trading (gate, executor, monitor, shadow runners, risk checks) uses data fetched
  from Pionex itself at decision time: prices, order books, symbol rules, fees, and the owner's account
  (via the read-only reader). Never a log, a report file, a cached summary, a status file or an agent's
  memory as a guide. Logs are for humans and audits only.
- Every Pionex value used in a decision carries its timestamp and is rejected if older than its limit
  (quotes 5 s, account state 5 min, symbol rules 1 day). Stale data = no action, and a critical notice.
- Historical research data from other venues (Binance archives) is PROXY: it must be labelled, must track
  Pionex (tracking check), and the final proof always comes from forward trading on live Pionex prices.

## Adapt or die (owner, 2026-10-17)
Markets change; the firm detects change fast and responds by rule, not by hope.
- Detect: the program watches (a) market regime on live Pionex data (volatility, trend strength, correlation
  between coins, spread/liquidity, funding) and (b) each live/shadow strategy against its own design
  (CUSUM / changepoint test on its realised returns vs the expected distribution, fill quality, slippage).
- Respond, in this order: the monitor STOPS or shrinks a strategy that has left its design (stop-only power);
  the program re-allocates capital only among strategies that are currently ELIGIBLE; research agents re-test
  on rolling windows and, if the regime really changed, build or re-fit a strategy by a PRE-REGISTERED
  procedure (never by tuning on the latest week) and it must pass the full gate and luck-proofing again.
- Retire what has decayed: a strategy whose live record falls outside its backtest range is stopped and
  logged as retired; nothing stays live out of loyalty.
- Speed matters: regime check every 5 minutes on live data, strategy-health check hourly, change alerts to
  the owner on Telegram only when action was taken or is needed.

## No blocked tasks (owner, 2026-10-18)
The dashboard must never show blocked work. Paperclip and the trading program follow the same rules: no human in
the loop, no blocking, self-heal, self-improve. Never set an issue to `blocked`. Waiting on another issue ->
status `backlog` with the dependency named in a comment (it is promoted automatically when the dependency is
done). Failed run -> retry or route around it. Superseded or duplicate -> cancel it with the reason. A decision only
the owner can make -> make the sensible default yourself, record it, tell the owner on Telegram, and continue.
The CEO's Monday problem map and the daily board report keep the owner informed instead of asking.

## Never stop (owner, 2026-10-17)
Nobody is watching 24/7. The firm heals itself and keeps grinding: agents run with full access to this PC (no
sandbox); a blocked task is never an end state. If a step fails, retry, find another route, or build the missing
tool; mark an issue blocked only for a real dependency (another issue, a decision only the owner can make) and name
it. Infrastructure trouble is healed by code (paperclip/selfheal.py re-queues; paperclip/engine_switch.py moves
agents between Codex and Claude when one runs out of tokens). Always end a run by setting the issue's status.
Target (owner, 2026-10-18): match or beat the owner's own recorded trading, measured from Pionex: >= $100 profit per 30 days on
$100 capital, with maximum drawdown <= 35% (the owner's own record: +$54..129 per 30 days at a 72% drawdown; see
docs/status/owner-record-2026-10-18.md). The gates, luck-proofing and the live limits do not move for it.

## Own the problem (owner, 2026-10-17)
The firm's problem: trade safely AND profitably, autonomously. The firm is in control of solving it, and acts like a
super surgical institutional trading company: it does not wait to be told.
- Find what is missing. If data would help (order flow, options, on-chain, funding, liquidations, news/event
  calendars, anything), find a FREE source, and if none is free, find the free equivalent or a proxy, or build
  the dataset ourselves by recording it daily (see `py -m pionex_lab record-daily`). If a tool would help, find an
  open-source one (read the licence, never copy code we may not use) or build our own.
- Do useful research even when no task asks for it: question our own assumptions, look for what the best
  desks do, test cheap hypotheses, look at where we lose. Log everything in docs/STRATEGY_LOG.md and the
  trial registry. Every Monday the CEO writes the "problem map": the 5 biggest unknowns/gaps between us and a
  proven, safe, profitable strategy, and what is being done about each (a task, a data source, a tool).
- Limits that never move: FREE only (no purchases, no paid tiers, no card details); no creating accounts, no
  passwords or API keys that are not already provided; only well-known reputable sources and official packages;
  downloads go into their own new folder under var/ and are scanned before use; the hard limits, the live gate
  and the owner's policy above stay exactly as written; stay inside the weekly quota guard.

## Luck-proofing (every strategy, before the gate can open)
A strategy must beat luck, not just look good: firm-wide trial registry (every test and variant ever run is
counted), deflated Sharpe / multiple-testing correction against that count, probability of backtest
overfitting (CSCV), permutation and random-entry null tests, parameter-sensitivity maps (neighbouring
settings must also work), block-bootstrap lower bounds, out-of-sample and walk-forward on untouched data,
regime splits (bull, bear, sideways, crash), cost and slippage stress (2x and 4x), Monte Carlo of the
trade sequence (odds of losing 50% of the capital in 30 days), and forward results on live Pionex prices.
The more tests the firm has run, the higher the bar for the next one.

## Evidence standard (quant work)
Pre-register rules and pass criteria (with a timestamp) before running; run once; walk-forward or an
untouched out-of-sample period; decisions on closed bars, fills at the next open; Pionex costs
(0.05% fee per side + slippage + measured spread; 10 USDT minimum buy); bootstrap lower bounds;
correct for the number of tests. A changed idea is a new test. Log every test in
`docs/STRATEGY_LOG.md`, PASS or FAIL.

## Run protocol (every run)
1. Quota check first (skip for the Trading Desk's paper-book run): GET
   `http://127.0.0.1:3100/api/companies/5e6a1546-5971-4f76-afd5-408d94bed26f/costs/quota-windows`.
   The firm shares the owner's Claude subscription. In the "anthropic" entry, if "Current week" used
   is >= 85% or "Current session" >= 90%: comment one line ("skipped: quota NN%"), leave the issue
   open for the next window, and exit.
2. Work only on the issue that woke you. One concise comment per run: what you did, the result,
   what is next. No running commentary.
3. Always leave the issue in a clear state before exiting: `done` when finished, `blocked` with the
   reason and who must act, or `in_progress` only if you will continue on the next wake.
4. A PASS is never closed by the agent that produced it: the CEO sets an execution policy on the
   issue with the Red Team as reviewer (`maxReviewRounds` 2) before it can be closed.
5. Never create agents or skills; propose them to the CEO, and the board decides.

## Telling the owner (Telegram; important and informative only)
`py -m pionex_lab notify --level <critical|important|daily> --key <unique-id> "<one to three lines>"`
- critical: something is broken and needs the owner (a routine failed twice, the paper books did not
  update, Paperclip or Wave Lab down, any attempt to touch a hard limit). Sent at once, day or night.
- important: a test PASSES, a Red Team verdict, a strategy promoted or retired, a paper book outside
  its backtest range, a trend flip in BTC/ETH, accepted firm improvements. Use a stable --key (e.g.
  `pass-<idea>-<date>`) so it is sent once. Max 6 a day; quiet hours 23:00-07:00 hold it until morning.
- daily: only the Trading Desk's morning summary (3-6 lines, numbers first).
Never: "nothing happened" messages, progress chatter, secrets, raw logs, or trade instructions.

## Cost discipline
Use the cheapest model that does the job. If a run has nothing to do, say so in one line and exit.
No busywork, no re-checking finished work, no long reports nobody asked for.

## Code changes
Branch `claude/<topic>-<yyyy-mm-dd>`; run `py -m unittest discover -s tests` and
`py -m unittest discover -s .claude/skills/pionex-trading-lab/scripts -p "test_*.py"` (the only
known failure is `test_read_only_uri_encodes_awkward_paths`); commit with a message file ending in
`Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; merge --no-ff into main; push.

## Where the firm stands (2026-10-14)
- Only candidate: CTA trend basket v1.1 (`pionex_lab/swing/cta.py`): daily time-series momentum on
  10 coins, vol-sized, long or cash. In-sample backtest 35.8%/yr, max drawdown 26%, Sharpe 1.37
  (proxy data). Plan for ~25-30%/yr and 30-35% drawdowns.
- Paper books since 2026-10-14 (`py -m pionex_lab guidance` advances them): defensive 1000 USDT,
  growth 1000 USDT, canary 100 USDT (BTC+ETH; the only shape a $100 live run could hold).
  Earliest owner review: 2026-12-13.
- About 20 ideas have failed after costs (scalping, mean reversion, the strategy zoo, order-book
  factors, Kronos, 4h trend, overlays...). Read the log before proposing anything.
