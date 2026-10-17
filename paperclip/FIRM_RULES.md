# Cloudworks Technologies AI trading — rules every agent follows

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

## The owner's real Pionex account (read-only view)
A separate read-only reader (Windows task "Pionex account reader", `py -m pionex_lab account`) loads the
owner's read-only API key at runtime and writes balances to `var/account.db` (table `snapshots`) every
minute, and the owner's grid bots (running and finished: pair, range, grids, investment, grid profit, status) to table `bots` every hour. Agents may READ that database to compare the owner's real account with the paper books. Agents
never open the key file, never call signed endpoints themselves, and never place, change or cancel
orders or bots. The key is read-only by the owner's choice; live trading still needs the owner's switch.

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
