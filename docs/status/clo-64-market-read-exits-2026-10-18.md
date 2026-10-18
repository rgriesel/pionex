# CLO-64: owner method and market-read exits

Status: **INCOMPLETE INPUTS; not eligible for live use.** The exit engine is
implemented; measured early-exit benefit, full owner-method tests A/B/C,
leverage expectancy and probability of ruin remain unavailable.

The owner-method definitions and six exit rules were frozen in
`pionex_lab/research/owner_method.py` at 2026-10-18T09:53:29Z and committed
as `4605aad` before evaluation. No performance-driven parameter changes.
The entry feature contract awaits CLO-65 and causal analyst guidance.

Implemented exit triggers: six-bar stall (four/eight-bar neighbours), two
confirmed failed retests, momentum/volume fade or divergence within one ATR
of target, consumption/movement of the identified entry heatmap cluster,
training-only censored time-to-target median, and known news in the next hour.
The pure research signal requires positive reconciled net flatten profit.
Paired replay uses caller-supplied grid ledger settlements, fills at the next
open, rechecks net profit there, and prioritises liquidation on ambiguous
barriers. It has no network, signer, order path or live-monitor integration.

## Read-only source audit

`var/account.db`, table `bots`, latest detailed snapshot by bot id:

| Observation | Count |
|---|---:|
| Bots expected by assignment | 65 |
| Distinct bots actually present, all with raw details | 52 |
| Finished / running | 50 / 2 |
| Manual cancellation before latest configured price target | 33 |
| Manual cancellation, price target unavailable | 14 |
| Recorded profit-stop closure | 2 |
| Recorded liquidation | 1 |
| Target snapshots observed before entry / before exit | 0 / 0 |

These are close-reason labels, not inferred discretionary intent. Latest
`profitStop` values are retrospective settings; grid bounds are never treated
as targets. Margin minus initial investment is retained only as an
unreconciled account field, not banked after-fee trading profit. Transfers,
withdrawals, inventory, fee semantics and funding require reconciliation.

Closed-bar historical context was reconstructable for 34/50 finished bots;
16 lack sufficient recent/gap-free symbol-matched bars. Perpetual bots use
Binance **PERP PROXY**, never silently substituted Pionex spot. Only complete
hourly candles ending before the actual exit are used. Their ingestion at
the time of the owner's decision is not established.

For the 22 manual-before-latest-target closures with context, 8 show a stall
in the trailing 20 bars over the final 6 bars, 4 have nonpositive signed
three-hour momentum, and 2 show volume below half its prior 12-hour mean.
These descriptive counts do not validate the full exit rule, overlap in
time, and do not show whether closing beat holding. Historical news and
matched heatmap cluster state at exit are unavailable.

## Luck suite and dependencies

The unchanged CLO-44 thresholds are recorded, with all nine tests marked
**NOT_EVALUABLE / pass=false**. No CTA-specific luck report is substituted
for owner-method exits. The registry conservatively reserves five frozen
configurations (base, stall4, stall8, fade0.4, fade0.6), count 260 -> 265 at
this run. Missing return panels cannot produce DSR, CSCV/PBO, null-test
p-values, bootstrap bounds, regime results, cost stresses or ruin estimates.
All leverage outputs (3x/5x/10x/20x/40x) are null, not zero. No leverage has
established positive expectancy. No statistical performance test was run.

Dependencies before tests A/B/C and exit benefit can be completed:

1. **CLO-65:** timestamped S/R, OB, heatmap/OI and news pipeline.
2. **Complete 65-bot account-reader evidence:** immutable target versions,
   entry/close parameters, inventory, fills, fees, funding and cash flows.
   Existing account evidence cannot recover unrecorded discretionary intent.
3. Point-in-time analyst calls and forward Pionex exit/hold shadow ledgers.

Next evaluation uses the frozen chronological splits, 24-hour purge,
walk-forward, day-clustered paired comparisons, neighbour checks and 2x/4x
costs. There is no reason to run a proxy performance test with fabricated
targets or missing inventory. CLO-64 should be backlog with these named
dependencies, never done or blocked.

Artifacts:

- `docs/status/clo-64-exit-audit-2026-10-18.json`
- `docs/status/clo-64-exit-context-2026-10-18.json`
- `pionex_lab/research/owner_method.py`
- `pionex_lab/research/owner_exit_study.py`
- `tests/test_owner_method.py`

Validation: 14 focused tests and 12 skill checks pass (synthetic accounting/timing tests, not
profit evidence). Full repository discovery was attempted and stopped after 1,114 seconds
without completion. It showed one error before losing progress in existing
loopback-server tests; its failure details were not emitted. This is an
incomplete broader check, not a suite PASS. The 14 focused tests also pass
on the main integration baseline; all 12 skill checks pass.
