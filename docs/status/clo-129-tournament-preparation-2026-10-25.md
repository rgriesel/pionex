# CLO-129 tournament preparation — 2026-10-25

Disposition: **backlog**, dependencies **CLO-128** (owner-grid analysis) and
**CLO-37** (forward futures-grid funding/liquidation accounting). Qualification
gates must be confirmed before a performance experiment. No forward tournament
has been started, no historical strategy test has been run, and no owner bot
has been copied or modified. Research verdict: **INSUFFICIENT**.

## Delivered independently of those dependencies

`pionex_lab/research/grid_tournament.py` supplies a frozen, offline spot-cohort
scorer and bounded neighbour proposals using the existing `shadow_grid.Config`
and `swing.grid` fee, grid-spacing and minimum-investment framework. Rules are
timestamped **2026-10-25 18:37 SAST** in function docstrings, before validation.

The planned pilot has 18 configurations: BTC/ETH, +/-4/8/16% geometric ranges,
20/40/80 rows, 1,000 simulated USDT per configuration. All attempts must enter
the trial registry before prices are observed; this preparation reserves no
performance trials. Dense initial controls remain in the table even if they
lose after fees. New neighbour proposals enforce the registered spacing bound.

The scorer requires a common complete seven-day cohort and rejects the entire
cohort for missing members, parameter drift, tape gaps, unreconciled cash/base,
or observation gaps over two minutes. It ranks total economic returns after
paid fees and a remaining inventory exit-cost reserve, retains losing rows,
and reports observed drawdown. It proposes retirement of nonpositive returns
or drawdown over 35%, then up to four neighbours of each of the top two remaining
members, capped at four descendant generations. A proposal cannot trade, start
a runner, update a ledger, promote a strategy or change a live gate.

## Coverage check

| Scenario | Existing coverage | Added coverage / remaining gap |
|---|---|---|
| Spot initialisation, crossings, stop and fee accounting | `test_shadow_grid.py`, `test_grid.py` | Reused; no second fill engine |
| Duplicate trade delivery and restart | `test_shadow_grid.py` | Existing runner tests; coordinator is deterministic/read-only |
| Trade-feed gap | Existing runner records gaps but bridges prices | Coordinator rejects the entire cohort; bridged fills cannot win selection |
| Snapshot interruption, missing peer | Existing ledger snapshots | Synthetic incomplete-window and observation-hole rejection |
| Inventory versus realised grid profit | Existing grid/float identity | Rank economic equity; residual fee/slippage test |
| Future observations / changed parameters | Existing immutable ledger | Frozen-parameter match and no-peek tests |
| Bounded variants / lifetime | No tournament policy | Deterministic proposals, constant capital, generation cap |
| Partial/rejected fills and precision | Existing paper execution engine | Tournament runner integration remains pending; no claim of exact exchange execution |
| Futures grids | `swing/perp.py` models individual positions; CLO-63 historical approximation failed | CLO-37 must provide changing grid inventory, settlement funding and liquidation accounting |
| Owner winners | CLO-46 mined historical finished bots; those rules failed | CLO-128 still in progress; no current exact-copy manifest delivered |

## What remains before starting the single forward experiment

1. CLO-128 delivers source-linked owner configurations with product, direction,
   pair, absolute range, grid count/type, leverage, investment and economic P&L.
   Freeze the exact-copy selection rule before the new forward observation.
2. CLO-37 delivers a tested forward futures-grid ledger. Reuse `swing/perp.py`
   where appropriate; multiplying spot P&L by leverage does not account for
   changing inventory, funding, margin or liquidation.
3. Register the complete cohort (including owner copies and leverage variants),
   the adaptive selection procedure and total trial budget. Confirm performance
   gates before running: untouched forward interval, matching benchmark, funding,
   measured spread, fees/slippage stress, bootstrap/multiple-testing and existing
   firm qualification checks. A descriptive weekly winner is never a PASS.
4. Integrate proposals with a persistent, transactional, idempotent paper-only
   cohort supervisor and the existing public-data runner. Validate fresh Pionex
   quotes (5 seconds) and symbol rules (one day) at launch and every action.
   Persist generation/parent lineage and trial registration before spawning.
   Preserve static controls and retired histories. Test interruption between
   retirement, registry append and new-cohort commit before deployment.

This preparatory module is deliberately not connected to a scheduler. It reads
logs for audit only. Current quotes must drive any eventual paper action, per
FIRM_RULES. No order path, mandate, lock, risk engine, settings or secret files
were accessed or changed. Reports are simulated research, not proof of profit.

## Validation

- New tournament tests: **10 passed** (final-source targeted run).
- `py -m unittest discover -s tests`: **488 tests**, one skipped, one known
  Windows portability error in `test_read_only_uri_encodes_awkward_paths`
  (`?` is not a valid Windows directory character). No other errors or failures.
- `py -m unittest discover -s .claude/skills/pionex-trading-lab/scripts -p "test_*.py"`:
  **12 passed**.
- `git diff --check`: passed.

Changes were isolated from the owner's existing dirty workspace in
`var/worktrees/clo129`, branched from main. Only this preparation, its tests,
this record and the strategy-log row are included in the commit.
