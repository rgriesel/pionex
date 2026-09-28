# Progress dashboard and telemetry contract

Use `assets/dashboard.html` as the standalone dashboard or as a frontend starter. A private companion page may be available from this skill's handoff. The template imports a report entirely in the browser, can show an explicit synthetic demonstration, and exports its active report. It does not connect to Pionex, persist account data, place orders, or run a bot. Imported data remains only in page memory and disappears on reload. Never claim it is live-connected.

For continuous monitoring, implement a backend producer that exports this schema from the canonical ledger and an authenticated read-only endpoint; poll or stream that endpoint to the frontend. Label imported snapshots versus a verified streaming connection. Use no exchange keys in the browser. Authenticate on the server. Keep private reports private. Never count frontend refreshes as proof of healthy execution.

## Report schema

Require `schema_version: 1`, `mode: LIVE | PAPER | BACKTEST | DEMO`, `generated_at` (ISO UTC), `source_label`, and these objects/arrays. The template validates bounded, finite inputs and monotonic dates before replacing the current report.

```json
{
  "schema_version": 1,
  "mode": "PAPER",
  "source_label": "Canonical paper ledger export",
  "generated_at": "2026-09-28T19:00:00Z",
  "experiment": {
    "start_at": "2026-09-28T00:00:00Z",
    "duration_days": 30,
    "initial_capital_usd": 100,
    "target_profit_usd": 1000
  },
  "snapshots": [],
  "trades": [],
  "strategies": [],
  "learning": {
    "status": "UNPROVEN", "paired_observations": 0,
    "mean_delta_usd": null, "ci95_low_usd": null, "ci95_high_usd": null,
    "method": "No matched forward comparison available"
  },
  "operations": {
    "state": "PAPER", "open_positions": 0, "gross_exposure_usd": 0,
    "feed_age_seconds": null, "reconciled": false,
    "protection": "UNVERIFIED", "reason": "Awaiting telemetry"
  },
  "human_comparison": {"comparable": false, "note": "No dated human ledger supplied"}
}
```

Snapshot fields: `at`, `equity_usd`, `net_cashflow_usd` (cumulative additional deposits minus withdrawals; initial capital excluded), `cumulative_operating_cost_usd`, optional `btc_benchmark_usd` and `human_equity_usd`. Every monetary value must already be consistently USD-valued, using retained FX evidence in the backend. `equity_usd` is exchange liquidation-value equity after actual trading fees and estimated remaining closing costs. Track free/frozen/bot inventory without double counting. Runtime costs here are ONLY costs paid outside that exchange equity; do not subtract costs already deducted from it a second time.

Trade fields: `id`, `closed_at`, `symbol`, `strategy`, `net_pnl_usd`, `fees_usd`, `slippage_usd`, `exit_reason`. Report complete position episodes, not each partial fill as another winning trade. Net P&L already includes actual execution costs. Fees/slippage are attribution fields, not another subtraction from equity. Slippage is measured against a defined decision/arrival benchmark and can be negative.

Strategy fields: `name`, `version`, `state`, `closed_trades`, `net_pnl_usd`, `change_note`, `evidence`. Keep live and paper versions in different reports; do not merge them.

`learning` carries a predeclared matched forward comparison, with sample count, mean challenger-minus-frozen-baseline expectancy difference, a dependence/search-adjusted confidence interval, and method. A positive lower interval bound can be reported as improvement only in that particular evaluation, subject to the research gates. The template rejects an `IMPROVING` label without a positive lower bound and a nonzero sample; it does not itself validate the statistical method or claim the result is live evidence.

## Metrics

- Economic value: `equity_usd - net_cashflow_usd - cumulative_operating_cost_usd`.
- Net economic P&L: economic value minus initial capital. Include unrealized inventory in equity. With no extra cash flows, target economic value is USD 1,100.
- Progress: `net economic P&L / 1000`, displayed with negative/over-target values honestly; bound only the visual meter to 0–100%.
- Return: net economic P&L / initial capital. Additional flows invalidate the fixed-capital challenge; flag them and use unitized/time-weighted returns for any separate performance study.
- Drawdown: largest percentage decline from the running high-water mark of economic value, starting with initial capital. A simple cash-flow-adjusted dollar curve is appropriate only for this fixed-capital challenge. Flag any extra flow prominently.
- Win rate: positive closed episodes / all closed episodes; zero-P&L episodes stay in the denominator. No trades means unavailable.
- Profit factor: sum of positive net trade P&L / absolute sum of negative net trade P&L. With no losses, show unavailable plus the reason; never display infinite skill.
- Expectancy: average net closed-trade P&L, including zero outcomes. Keep operating costs separate and include them in account-level economics.
- Fees: actual charged fees from complete fills, converted at contemporaneous FX. Do not infer total account cost from an incomplete closed-trade list. The template labels its number as closed-trade fees.

Retain full-resolution equity for risk even if chart data is downsampled. The standalone template's drawdown is sampled from the supplied snapshots and is labeled as such. A production backend must supply the authoritative high-frequency drawdown alongside it.

Show status/as-of, stale data, disconnects, missing human data, open exposure, trade reasons, champion/challenger versions, and empty states. Do not substitute a fake human benchmark. The BTC benchmark must use the same start/end and explicit costs. Claim a human difference only if `human_comparison.comparable` is true and both values cover the same interval; otherwise label it unmatched/unavailable.

At day 30, freeze a reconciled report. Keep target attainment, net profitability, benchmark outperformance, and statistically supported learning as separate findings. No single one establishes all the others.
