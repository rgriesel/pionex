# Proposal: mandate v2 — add a paper "swing" sleeve (for the owner to review and apply)

Written 2026-10-14 by the lab agent. The agent may not edit `config/mandate.v1.json` or its lock;
this file only describes the change. Nothing here enables live trading.

## Why

Every strategy with holds of 4 hours or less failed the lab's tests after fees (scalping zoo, order
book factors, the owner's Fibonacci strategy). One rule set passed with long holds: the **CTA trend
basket** (`pionex_lab/swing/cta.py` v1.1, report `var/reports/cta_basket_v1_1.json`).

- 10 Pionex coins; a coin is held while at least 2 of its 20/60/120-day returns are positive.
- Each held coin gets (40% / N) / its 30-day volatility of capital; total ≤ 100%; daily rebalance at
  00:00 UTC with a 2% no-trade band; spot only, no leverage, no shorts.
- Backtest (Binance proxy data, in-sample) 2017-12 → 2026-10: 35.8%/yr, max drawdown 26%, Sharpe 1.37
  (holding all 10: 45.6%/yr, 82% drawdown, Sharpe 0.88). 4x costs: Sharpe 1.22, drawdown 31%. The red
  team (Opus) found bookkeeping issues, all fixed in v1.1; plan for ~25–30%/yr and 30–35% drawdowns.
  Backtests are not proof of future profit; it is paper-tracked forward in `var/swing_book/`.
- Live canary under the $100 cap: BTC + ETH only (backtest at $100: 32.7%/yr, drawdown 33%,
  Sharpe 1.15); the 10-coin book cannot run at $100 because of Pionex's 10 USDT minimum buy.

## Changes needed (v2 = v1 plus a separate swing sleeve; v1 intraday rules unchanged)

| Setting | v1 | Proposed for the swing sleeve | Reason |
|---|---|---|---|
| `execution.max_intraday_holding_hours` | 4 | keep 4 for intraday; add `swing.max_holding_days: 365` | trends last weeks to months |
| `risk.max_positions` | 2 | `swing.max_positions: 10` | basket of 10 coins |
| `risk.gross_exposure_fraction` | 0.50 | `swing.gross_exposure_fraction: 1.0` | weights sum up to 100% (avg ~27%) |
| `risk.position_notional_fraction` | 0.25 | `swing.position_notional_fraction: 0.20` (BTC+ETH canary: 0.60) | 10-coin weights ~3–20%; with 2 coins BTC can reach ~50% |
| `risk.peak_drawdown_fraction` | 0.10 | `swing.peak_drawdown_fraction: 0.35` | backtest worst 26% (31% at 4x costs, 33% BTC+ETH); or lower the vol target (25% target ≈ 16% drawdown) |
| `risk.daily_loss_fraction` / weekly | 0.02 / 0.04 | `swing.daily_loss_fraction: 0.06`, weekly 0.12 | basket can move 3–5% in a day |
| `execution.allowed_symbols` | [] | the 10 coins | BTC ETH SOL XRP DOGE LINK ADA BNB AVAX LTC (USDT spot) |
| qualification | trade-count based | `swing.min_paper_days: 60` | a rebalancer makes few, small trades |

Kept as is: `mode: PAPER`, `live_enabled: false`, `spot_only: true`, `leverage: 1`,
`agent_may_raise_limits: false`, the $100 live cap (memory: live may never use more than $100).

## What the agent would build after approval

A portfolio-rebalancer strategy type in the paper engine (today's engine sizes single trades with
stops), wired to the mandate's swing section, plus a dashboard panel. Until then the swing book runs
as a separate paper tracker and is reported daily.
