# The Pionex lab as a small trading firm

Modelled on dotta's "zero-human trading firm" (Paperclip), built natively in Claude Code: subagents
with their own model per role, the lab's skill, scheduled routines, and hard limits in code/config.
Paperclip itself is not installed; it would add a dashboard and budgets on top of the same pieces.

## Org chart (5 agents + the lead; dotta: start with 5–6 focused agents, not 30)

| Role | Model | Defined in | Does | May write |
|---|---|---|---|---|
| Lead / portfolio manager | Opus (main session) | this session | priorities, final strategy and settings decisions, commits | code, docs |
| Research scout | Sonnet | `.claude/agents/research-scout.md` | ≤5 new idea cards per night from arXiv, TradingView, GitHub, research blogs, the owner's YouTube channels | `research/ideas/` only |
| Quant / backtester | Sonnet | `.claude/agents/quant-backtester.md` | pre-registers and runs ONE test per idea with the lab frameworks; logs the verdict | research code, tests, `docs/STRATEGY_LOG.md` |
| Red team | Opus | `.claude/agents/red-team.md` | attacks every PASS: look-ahead, bugs, survivorship, data, costs, overfitting | nothing (read-only) |
| Risk officer | Opus | `.claude/agents/risk-officer.md` | gates backtest → paper → owner review against the numbers below | nothing (no shell, no write) |
| Ops / reporter | Haiku | `.claude/agents/ops-reporter.md` | inventory, health checks, plain-English status | `docs/INVENTORY.md`, `docs/status/` |

Cost control: one run of each agent per routine; the scout caps at 5 ideas, the quant at 2 tests per
night; review agents run only on a PASS (dotta: reviews cost tokens; use them where it matters).

## Pipeline (every strategy, no shortcuts)

1. **Idea card** (scout) → checked against `docs/STRATEGY_LOG.md` for repeats.
2. **Pre-registered backtest** (quant): rules and pass criteria written before running; walk-forward
   or untouched out-of-sample; Pionex costs; next-open fills; run once; logged either way.
3. **Red team** (Opus): verdict HOLDS / HOLDS WITH FIXES / BROKEN. Fixes → re-run as a new test.
4. **Paper** (≥ 60 days for daily strategies, ≥ 200 trades for intraday ones): forward on Pionex data,
   no orders. Paper must stay inside the backtest's drawdown and turnover ranges.
5. **Risk officer** sign-off → **owner approval** (only the owner can enable live; mandate change by
   the owner) → **live canary ≤ $100** for at least 30 days → scale only by owner decision.

## Hard limits (in code/config, outside any agent's reach — dotta's agent bypassed a prompt-level limit)

- `config/mandate.v1.json` + `config/mandate.lock.json`: PAPER, `live_enabled=false`, hash-checked by
  the engine at start; `agent_may_raise_limits=false`. Only the owner edits it.
- Live capital cap: never more than $100 of the account (owner's standing rule).
- No order path in the lab repo; the paper engine only sends Pionex dry-run previews.
- **Recommended (owner's call):** restore the `.claude/settings.json` deny rules removed on
  2026-10-10 (mandate/lock edits, `.env`/secrets reads, `review-latch`), so agents are blocked by the
  harness, not only by instructions.

## Routines (session schedules; they stop if the Claude session closes, renewed every 7 days)

| Local time | Routine |
|---|---|
| 02:17 | trend check: paper swing books (defensive + growth), BTC/ETH EMA50 state |
| 02:53 | nightly lab check (paper engine, research cycle results) |
| 03:37 | research routine: scout → quant (≤2 tests) → red team on any PASS → log |
| 07:52 | morning summary for the owner |
| 21:43 | YouTube BTC calls + guidance scorecard |

## Current decision (lead, 2026-10-13, after the red team)

- **Strategy:** CTA trend basket v1.1, *defensive* settings as first tested — no post-hoc tuning.
  10 coins (BTC ETH SOL XRP DOGE LINK ADA BNB AVAX LTC); coin IN while ≥ 2 of its 20/60/120-day returns
  are positive; size (40% ÷ N) ÷ 30-day volatility; total ≤ 100%; long or cash; rebalance once a day
  at 00:00 UTC (02:00 SAST) with a 2% no-trade band.
- **How long to hold:** no fixed time — each coin is held while its trend vote stays positive and sold
  the day it turns. Backtest: median 3 days (whipsaws), mean 16 days, top 10% of holds 48+ days; the
  long trends pay for the short ones, so they must not be cut early.
- **Why not more aggressive:** the growth variant (equal sizing) made more in backtest (68%/yr) but
  with a 55% drawdown; it runs as a paper comparison only.
- **What to expect (planning range, not a forecast):** the backtest is in-sample (35.8%/yr, Sharpe
  1.37, drawdown 26%). The red team's discount for that: plan for roughly 25–30%/yr, Sharpe 1.0–1.2,
  and drawdowns of 30–35%. Long flat or losing stretches in sideways markets are normal for trend
  following.
- **Paper books (from 2026-10-14, 00:00 UTC):** defensive 1000 USDT (10 coins), growth 1000 USDT
  (comparison), canary 100 USDT (BTC + ETH only). 1000 is used because at 100 USDT most coin
  positions fall under Pionex's 10 USDT minimum buy and the 10-coin book would sit ~89% in cash.
- **Live plan under the $100 cap (owner decides; not before 60 paper days + risk-officer review):**
  the canary book exactly — BTC + ETH, vol-sized, ≤ $100. Backtest 32.7%/yr, drawdown 33% (≈ $33 at
  worst), Sharpe 1.15. It tests execution and behaviour, not income: at $100 it makes tens of dollars
  a year at best.
- **Next test (pre-register before running):** a whipsaw filter (e.g. enter on 3 of 3 positive, exit
  on ≤ 1 of 3) — only if the red team and paper period support it.
