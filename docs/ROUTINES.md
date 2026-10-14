# Lab routines — what runs when, and how it survives the PC sleeping

Two layers (lesson of 2026-10-14: the PC sat in Modern Standby 00:00–09:34; the Windows-task
supervisor still ran its 02:10 jobs, but the Claude app was suspended and every Claude routine was
missed, so nothing reached the dashboard).

## 1. Lab supervisor (no Claude needed; runs even in standby)

Windows scheduled task `PionexLab` → `pyw -m pionex_lab run`. At 00:10 UTC (02:10 SAST) it runs
`daily-review` (which also advances the three paper swing books and the guidance scorecard and
stamps `supervisor_books`), `fetch-proxy` and one research cycle. Never start a second
`pionex_lab run`; use `Start-ScheduledTask -TaskName PionexLab` only if the task is not running.

## 2. Claude routines (need the Claude app open and the PC awake)

One hourly heartbeat cron in the Claude session (minute 11) runs:

```
py -m pionex_lab firm due
```

It prints the routines whose latest scheduled time has passed without a stamp (so a routine missed
during sleep runs at the first heartbeat after wake-up), plus `renew_heartbeat` when the cron is
near its 7-day expiry. For each name, follow its section below, then
`py -m pionex_lab firm stamp <name>`. If it prints `[]`, stop without messaging the owner.

Heartbeat cron prompt (recreate it in a new session with CronCreate, cron `11 * * * *`):

> Lab heartbeat (C:\Users\Desj Griesel\pionex). Do not ask the owner questions. Run
> `py -m pionex_lab firm due`. If it prints [], stop silently. Otherwise handle each listed name in
> order by following its section in docs/ROUTINES.md, then run `py -m pionex_lab firm stamp <name>`.

Rules for every routine: paper only; never place or suggest orders; never edit the mandate, its lock
or `.claude/settings.json`; never read `.env` or keys; never present backtests or paper results as
proof of profit; always give the owner a clear update, even when nothing worked.

### renew_heartbeat
CronDelete the current heartbeat job (CronList shows it) and CronCreate it again with the prompt
above, cron `11 * * * *`. Then `py -m pionex_lab firm stamp heartbeat`. Tell the owner nothing
unless it fails.

### nightly_check (02:53)
1. Exactly one supervisor (`pyw`/`pythonw -m pionex_lab run`) and `py -m pionex_lab status` shows
   PAPER, feed_ok and fresh heartbeats.
2. `var/logs/supervisor.log`: today's daily jobs; research registry: today's cycle (venue, hypotheses
   researched or retired, failed gates, gross/net OOS expectancy, profit factor).
3. If a candidate is QUALIFIED_FOR_PAPER, confirm the engine loaded it and its paper trial started.
4. Swing books: `var/reports/btc_guidance.json` (`swing_book`, `swing_book_growth`,
   `swing_book_canary`) were updated today; if not, run `py -m pionex_lab guidance`.
5. On or after 2026-10-29 19:44 UTC: the experiment window ends; confirm the engine unwound and wrote
   `var/reports/final-*.json`, and summarise the result honestly.
Append a short dated note to the lab-run-2026-09 memory. Message the owner only if something is
broken (the morning summary carries the news).

### research (03:37)
Use the Agent tool per role; if the custom agent types are unavailable, use `general-purpose` with
the model from `.claude/agents/<role>.md` and start the prompt with "Follow the role rules in
.claude/agents/<role>.md (read it first)".
1. research-scout (sonnet): at most 5 idea cards to `research/ideas/<today>.md`, skipping anything
   in `docs/STRATEGY_LOG.md`.
2. Lead picks at most 2 cards (holds ≥ 4h, structural reason). quant-backtester (sonnet) pre-registers
   and runs ONE test each, logged in `docs/STRATEGY_LOG.md`.
3. Any PASS → red-team (opus, read-only); record the verdict.
4. Test suites, then commit on `claude/research-<date>`, merge to main, push (attribution line).
5. Five-line summary for the morning summary.

### morning_summary (07:52)
Health (`py -m pionex_lab status`, process list), then briefly:
- the three paper swing books from `var/reports/btc_guidance.json`: equity vs start (defensive 1000,
  growth 1000, canary 100 USDT), the last day's return, coins IN/out and any flip, current weights;
  BTC/ETH EMA50 state and any flip. Context: CTA basket v1.1 is an in-sample backtest (35.8%/yr, max
  drawdown 26%, Sharpe 1.37 on proxy data); plan for ~25–30%/yr and 30–35% drawdowns;
- last night's research (scout ideas, quant tests, verdicts) and the supervisor's research cycle;
- the paper lab: readiness stage, paper trades, equity, drawdown, latches, incidents, shadow books;
- the owner's Pionex account value from `var/account.db`;
- what runs next; days to the earliest swing-book review (2026-12-13).
State that paper results are not evidence of profitability and no real money was used.

### youtube_calls (21:43)
BTC only, forward only (never backfill). In the built-in browser find each channel's newest video
since the last recorded call: More Crypto Online (youtube.com/@MoreCryptoOnline/videos), Daily Entry
(youtube.com/@DailyEntry/videos), Chart Hackers (youtube.com/@ChartHackersGroup/streams). Skip non-BTC
videos. Transcript: `var/tools` yt-dlp with `--write-auto-subs --sub-format json3` (or the transcript
panel). Keep only what is said about BTC: 1–3 day bias (LONG/SHORT/NEUTRAL), long/short zones,
conditional triggers, targets, short notes; never invent levels. Set `recorded` to the current UTC
time, write a JSON list to the scratchpad, run `py -m pionex_lab guidance --add <file>`. Short update
for the owner: each channel's call, the scorecard so far, any new WL Oscillator diamond. Caveats: too
early to judge before ~30 scored calls per channel; Daily Entry and Chart Hackers are the same
presenter; diamonds are rare.
