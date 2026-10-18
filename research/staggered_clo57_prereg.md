# CLO-57: frozen one-shot research protocol

Registered 2026-10-18T09:09:41.377778+00:00, before loading return data or running this test.

Card 4, research/ideas/2026-10-16.md. Compare CTA v1.1 tsmom_vote/vol with seven weekday-only books, each starting with 1/7 of total capital. No transfers between sleeves: combine by their actual NAV, never by resetting daily capital shares. Each sleeve drifts daily and rebalances at its assigned weekday 00:00 UTC using yesterday's closed bar only. Same 40% vol target, 2% sleeve band, 100% gross cap, costs and missing-bar rules as v1.1. Baseline is unchanged daily v1.1. No signal fitting or weekday selection.

Primary: fractional-capital historical proxy comparison. PASS only if absolute whole-period Sharpe difference <= 0.10 at standard costs AND staggered-minus-v1.1 Sharpe >= -0.15 at 4x costs, with all seven weekday Sharpes reported. Otherwise FAIL; this resolves the card's unspecified intermediate zone conservatively. 2x stress is diagnostic. Report CAGR, DD, exposure, turnover, weekday range and population SD. No hourly offsets: daily data only.

Report three chronological expanding-origin evaluation folds after a 730-day initial history, with no fit or parameter changes. Already-researched history is pseudo-out-of-sample, not untouched evidence. New forward observations and independent review remain mandatory for promotion.

Diagnostics: capital total 100 and 1000 USDT (each sleeve's fixed capital cap = total/7; 10 USDT minimum buys); these do not change the primary verdict. Account for 10 new trial variants (seven weekdays, combined, two capital cases) before evaluation; report deflated Sharpe against firm count. Reused daily baseline is not a new search. Costs 1x/2x/4x are fixed stresses, not selection.

Paired circular block bootstrap on combined-minus-baseline daily net returns: 20-day blocks, 2000 resamples, seed 20261018, 95% interval of mean difference; diagnostic, not a new gate. Preserve data coverage/gaps, normalized daily input SHA256, simulator/preregistration SHA256 and all daily return series in the report. Refuse to overwrite an existing result. Unit checks on synthetic data precede the single real-data run. No live path, no mandate/risk edits.
