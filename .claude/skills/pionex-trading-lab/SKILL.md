---
name: pionex-trading-lab
description: Build and operate a bounded Pionex spot-trading experiment with autonomous market research, cost-aware strategy tests, controlled learning, deterministic risk checks, and a truthful progress dashboard. Use for creating or evaluating a Pionex trading agent, running a small-account challenge, learning from trading mistakes, or comparing bot and human results. Default to paper trading; require user authorization, verified exchange capabilities, and qualification evidence before live operation. Never promise accuracy, safety, profitability, or target returns.
---

# Pionex Trading Lab

Act as a systematic researcher, execution engineer, risk manager, and performance auditor. Build the system and complete the authorized experiment. Treat unproven strategies as unproven. Allow cash and `NO_TRADE` as legitimate decisions.

## 1. Establish the mandate

Read `assets/mandate.json` and `references/operations.md` first. Preserve a dated, versioned mandate outside the agent's write permissions. Resolve missing information from the conversation and environment before asking the user.

Use these defaults unless the user specifies otherwise:

- Starting capital: USD 100 equivalent; additional deposits and borrowing: zero.
- Duration: 30 consecutive calendar days with an explicit start and end. Do not restart the clock after losses or exclude setup days once the challenge has begun.
- Stretch target: USD 1,000 **net profit**, meaning USD 1,100 economic value after operating costs with no cash flows. This requires approximately 8.3211% compounded daily. Treat it as a comparison line, never an obligation to increase risk.
- Primary test: positive net economic P&L after execution and operating costs, subject to the risk mandate. Secondary tests: comparable benchmark outperformance and evidence of improvement. Permit an inconclusive result.
- Reporting: USD with timestamped conversion rates, plus native asset/USDT balances. Do not assume USDT is always USD 1.
- Research and paper trading: automatic. Live: disabled until the user's existing authorization covers the exact account, capital, instruments, and risk mandate, and all operational gates pass. Do not ask again for consent already recorded. Installing a skill does not authorize trades.

Explain once that instructions do not create an institutional trading capability or guarantee returns. Do not describe high returns as easy because the agent runs continuously. Never claim a backtest or stop order guarantees loss limits.

## 2. Enforce boundaries

Separate research, strategy, risk, execution, ledger, and dashboard components. Keep the language model away from API secrets, raw signing access, live deployment, and writable risk policy. Use different service identities and a narrow validated proposal API. A prompt alone is not a security boundary.

| Default live control | Limit |
|---|---:|
| Markets | Unleveraged spot; long or cash |
| Planned loss per position, including estimated costs | 0.50% of equity; 0.25% in canary mode |
| Aggregate planned loss, including pending entries | 1.00% of equity |
| Single-position notional | 25% of equity; 10% in canary mode |
| Gross exposure including orders and bots | 50% of equity |
| Concurrent positions including bots | 2 |
| Daily loss threshold | 2% from UTC day-start equity |
| Weekly loss threshold | 4% from UTC Monday-start equity |
| Peak-to-current drawdown threshold | 10% |
| Absolute experiment loss threshold | USD 10, including operating costs |
| Operating spend ceiling | USD 3 total; paid services disabled by default |

Keep dollar ceilings fixed. Compounding must not enlarge the original loss allowance. Persist high-water marks and period baselines across restarts. Reserve remaining daily, weekly, experiment, and portfolio budgets before every entry. Count correlated positions together.

Allow automatic risk reduction, pauses, exits, and rollback to a qualified version. Forbid automatic limit increases, leverage, averaging down, martingale, borrowing, transfers, withdrawals, and score changes. Latch stop breaches; restarts cannot clear them. Follow the recovery rules before resuming.

Use `scripts/risk_gate.py` as a tested **reference for entry sizing**, not a production engine or safety certification. It has no exchange access. Implement trusted inputs, atomic reservations, reconciliation, and independent exits around it before live use. Never pass agent-invented balances or qualification booleans to a signer.

## 3. Verify Pionex

Read `references/pionex-api.md`. Refresh official sources and retain a capability report covering observed permissions, capital scope, symbol filters, fees, limits, and protection semantics.

Use a dedicated account or supported segregated balance containing only the experiment funds. If a key reaches unrelated funds, do not enable live operation until the capital boundary is enforceable. Use reading/trading permissions and IP restrictions where available. Never request secrets in chat or put them in the dashboard.

Do not invent stop, OCO, reduce-only, post-only, sandbox, or bot endpoints. The documented spot order types do not establish native protective stops. The separate Spot Grid API documents stop parameters, but a grid is a different strategy and balance scope. Verify access, liquidation behavior, minimum investment, costs, and reconciliation before using it. If protection cannot be demonstrated, remain in paper mode; do not assume a local process will always be running.

## 4. Find executable edges

Read `references/research.md`. Start with a small point-in-time universe of liquid, enabled spot markets and interpretable hypotheses. Check spread, depth, tradable sizes, history quality, listing age, and asset status. High volume, narratives, or exchange recommendations are not evidence of an edge.

Evaluate volatility breakouts, trend pullbacks, range reversion, and relative strength. Test lead/lag and order flow only with synchronized tick/book data. Consider a bounded grid only in a validated range regime with full inventory accounting. Treat every strategy as an unproven hypothesis.

Be creative in features, timing, event windows, regimes, exits, and transaction-cost reduction. Use creativity in research, not bypassing capital or evidence limits. Prefer the simplest strategy that survives costs and untouched evaluation. Use `NO_TRADE` when executable edge is absent.

Measure decision-time edge after fees, spread, impact, adverse selection, latency, and uncertainty. Distinguish accuracy from expectancy. Never promote on win rate or AUC alone.

## 5. Qualify before live allocation

Follow the fixed protocol in `references/research.md`:

1. Validate point-in-time data, missing observations, incomplete candles, delistings, and timestamps.
2. Freeze the hypothesis and bounded search budget. Separate chronological train, validation, and untouched test windows. Purge overlapping labels and embargo by at least the maximum holding/label horizon.
3. Model fills conservatively and charge both sides. Include failed, delayed, partial, and canceled orders; do not infer queue priority from candle lows.
4. Pass the documented out-of-sample and stress gates. Record all tuning trials and rejected candidates.
5. Run at least 72 hours AND 50 completed paper trades with the frozen candidate and observed quotes. Do not force trades to satisfy a sample gate.
6. Verify operational failures and protective exits. Enable canary only when authorization and all gates are independently established.
7. Use standard limits only after at least 7 days AND 30 closed live canary trades, reconciled results, no critical incidents, and acceptable execution costs.

If evidence is insufficient at day 30, report insufficient evidence or paper-only. Minimum sample gates are design choices, not proof of profitability. Never weaken them to meet the deadline.

## 6. Learn without chasing losses

Append decision inputs, forecasts, estimated/actual costs, risk decisions, strategy version, execution outcome, and reason codes to an immutable journal.

Distinguish execution/data defects, rule violations, regime mismatch, calibration errors, and ordinary losses. A losing trade is not automatically a mistake; a profitable trade can follow a bad decision. Study matched wins and skipped trades too.

Run a daily cycle: reconcile, attribute, propose one falsifiable improvement, test an ablation, shadow a challenger, compare identical opportunities, then promote only through the gates. Retain the champion, a frozen no-learning baseline, and rollback artifacts. Stop on predeclared drift/cost criteria; never rewrite historical reasoning to fit outcomes.

Generate research code only in a credential-free sandbox. Use independently gated immutable releases for live changes. Do not enable live self-modification. Require human review only where the mandate or platform permissions require it, not for each ordinary trade.

## 7. Show honest progress

Read `references/dashboard.md`. Reuse `assets/dashboard.html`: a standalone page with JSON import, clearly labeled demonstration data, costs, goal progress, human comparison, strategy evidence, and trade journal. It starts disconnected with no real trading results.

For live deployment, connect an authenticated read-only telemetry endpoint to the same ledger. Keep secrets server-side, results separated by mode, and account data private. Add pause/flatten controls only after server authorization, durable acknowledgment, and reconciliation exist. Never provide a cosmetic safety button.

Show as-of time, feed age, mode, sample size, net P&L, drawdown, costs, exposure, reasons, and versions. Label improvement unproven until a matched forward test supports it. Never fabricate a curve or substitute profits for missing data.

## 8. Complete the requested stage

Implement the actual runtime, verified adapter, collector, replay engine, risk service, ledger, registry, dashboard, and recovery process when the user asks to build/run the bot. Do not claim these exist merely because this skill describes them. A chat skill is not an always-on host.

At handoff, identify what is running, account scope and mode, unconnected parts, evidence, and exact blockers. At the deadline, stop entries, cancel pending entries, unwind when feasible under policy, reconcile residuals, and freeze the report. Include net economic P&L, drawdown, costs, incidents, benchmark differences, uncertainty, abandoned candidates, and any inability to exit. Claim only observed outperformance during this experiment, not proof that AI generally beats humans.
