# CLO-100 ETH base-fee filter: feasibility (2026-10-22, SAST) - verdict: FEASIBLE (narrow, post-Merge only)

Research only. No returns were calculated, nothing traded, no mandate/limit change. Card: `research/ideas/2026-10-22.md` #1. Not previously tested (STRATEGY_LOG has no base-fee row).

## Data and arrival-lag protocol
- Source: PublicNode public JSON-RPC (`eth_getBlockByNumber`, no key). **History is pruned before block 15,500,000** (just before the Merge); pre-Merge/London-era headers are NOT available free this way. Pre-Merge (Aug 2021-Sep 2022) is therefore *not established*; the study is post-Merge only (1,482 daily observations 2022-10-01..2026-10-21, continuous, no gaps).
- Historical causal protocol (frozen): observation for day D = `baseFeePerGas` of the last block with timestamp <= D 00:05 UTC minus 20 min (>1.5 finality epochs post-Merge, so finalized in hindsight with margin). Block number, hash-free timestamp and base fee saved in `var/reports/eth_basefee_daily_clo100.json`. Forward collection uses the card's live `finalized` call at 00:05.
- Caveat: finality was inferred from the 20-min lag, not recorded; reorg-free post-Merge in practice. Not a real arrival log.

## Event count (card rule applied to fee data only)
Rule: B(d) >= 3x median of prior 30 days on two consecutive days; 7-day hold; rearm after two days <= 1.5x. Result: **12 activations, 11 clusters >=30 days apart, all post-Merge** (2023-05-07, 2023-11-03, 2024-09-19, 2024-11-15, 2025-01-20, 2025-05-12, 2025-06-25, 2025-07-18, 2025-12-09, 2026-02-02, 2026-04-20, 2026-09-29). Gate (>=10 clusters, >=5 post-Merge) is met mechanically.

## Honest weakening
- 7 of 12 activations occurred with base fee < 4 gwei, 5 below 1 gwei (median fee 3.9 gwei; 41% of days < 1 gwei). Post-Dencun the ratio triples from a negligible baseline, which the card itself flags as an illusion; these do not plausibly impair collateral top-ups. Only ~4 events (2023-05, 2023-11, 2024-11, 2025-01) are economically meaningful, and they are few and clustered in the bull phases. Adding an absolute-fee floor would be a changed idea (new test, new trial).
- Free historical coverage is 4 years only; ETH-only $100 book minimum notionals may make half-target infeasible.

## Verdict: FEASIBLE under the literal card rule; power is weak. Pre-registration (frozen before any return calculation)
- Single rule exactly as in the card (above), no absolute-fee floor, no parameter grid. Trials: 1 new (registry 265 -> 266 when the run is authorized).
- Data: the frozen series above (PROXY ETH daily price from `var/proxy_market.db` for the later test), 2022-10-01 onward, 30-day warm-up, post-Merge only.
- Gates and controls: as written in the card (unchanged v1.1, constant-scale exposure control, block-matched placebo, trial-adjusted paired block bootstrap LB>0 at 1x/4x costs, >=2/3 chronological thirds positive, no basket max-drawdown increase, positive excluding the largest cluster; the post-Merge-only condition equals the whole sample). Report the fraction of events with B<4 gwei and run the matching ex-low-fee diagnostic as descriptive only.
- Next step needs a separate assignment to run the test once; Red Team review on any PASS. Code: `research/eth_basefee_feas_clo100.py`, test `tests/test_eth_basefee_feas.py`.
