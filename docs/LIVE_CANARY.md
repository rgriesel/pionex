# CLO-243 LIVE CANARY contract

Pre-registered 2026-11-07 11:44 SAST in `pionex_lab/live/canary.py:qualify`, before synthetic validation. This implements the board's separate loose canary screen. It leaves the forward tier unchanged. Eligibility is permission for a bounded experiment, never proof of profit. Canary P&L is **real money**.

The existing coverage was the forward gate's days, trades, profit, drawdown, freshness, continuity, luck suite and parameter-pinned Red Team review (`tests/test_live_gate.py`). It had no owner-method canary registration, lifetime scale/retire rule or current-data adapter. No new strategy backtest was run for this infrastructure assignment.

## Fixed policy, before any live trade

- Begin with $5 total margin per bot, including extra margin. After at least five closed live bots, at least $1 net realized profit, no losing closed bot and nonnegative marked strategy P&L, permit $10. No larger automatic tier.
- Any losing closed bot, or marked strategy P&L at or below -$1, retires that strategy id. Full lifetime history must survive restart; deleting history is forbidden. A different strategy requires a new registration and review.
- Total committed margin plus proposed margin must remain at or below the smaller of $100 and mandate capital. The adapter reserves margin atomically, including concurrent creates and uncertain outstanding requests.
- Halt new activity at daily high-water drawdown of $2 or cumulative loss of $10, or the mandate's stricter limits. Existing latched halts remain authoritative. Monitor/exit handling must reduce or close risk according to the registered rules, independently of new-entry eligibility.
- Every bot requires stop-loss and take-profit on the appropriate side of its range. Initial support is long/short geometric futures grids, 2–200 rows. Neutral and spot grids remain unsupported by this tier pending bracket enforcement.
- Leverage cannot exceed the strategy-specific independently reviewed certification or the mandate cap. An unrelated leverage study cannot certify another rule.

## Registration and review

Research supplies `var/canary_registry.db` table `candidates(id TEXT PRIMARY KEY, candidate TEXT)`. `candidate` is JSON containing `params` and `evidence`. The gate opens this database read-only. The new code does not create a registry or invent evidence.

`params`: `symbol` (Pionex `.PERP_USDT`), `trend` (`long`/`short`), integer `rows`, positive `bottom`, `top`, `loss_stop`, `profit_stop`, numeric `leverage`, optional `extra_margin` (default zero), optional `type` (`geometric`). Runtime allocation supplies `invest`; it is never selected by a caller.

`evidence`: `method="owner-method"`, positive integer `observations`, finite positive `net_expectancy` measured on total equity, `includes` with exact boolean true for each of `fees`, `slippage`, `spread`, `funding`, `exit`, `inventory`; exact true `closed_bar_decisions` and `next_open_fills`; `venue="PIONEX"` or `"PROXY"`; and `certified_max_leverage`. Research must retain the registered test and provenance for independent inspection. These fields are review assertions, not automated proof of causality or simulation correctness.

Red Team independently reviews bookkeeping, timing, provenance and leverage applicability. Its latest exact `HOLDS` row under `## Red Team registry` in the strategy log carries `review_hash(candidate)` in `params_sha256`. This pins the entire evidence, parameters and policy, rather than just a parameter subset. Any change or later non-HOLDS revokes qualification.

## CLO-238 executor integration dependency

`gate.evaluate_all(..., canary_observer=observer)` calls `observer(strategy_id, params, policy)` at decision time. It must return freshly fetched Pionex data, not a report, cached database summary or agent assertion:

| Field | Required meaning |
|---|---|
| `source`, `complete`, `enforced_policy` | `PIONEX`, true, `CLO-243-v1`; adapter has implemented the full policy |
| `account_ts`, `quote_ts`, `rules_ts` | Epoch milliseconds, ages 0–5 minutes / 0–5 seconds / 0–1 day |
| `closed_bots` | Full lifetime deduplicated strategy bots: unique nonempty `id` and finite `net_pnl` after fees and funding |
| `strategy_total_pnl` | Lifetime total equity P&L, including open inventory and all costs |
| `committed_margin` | Firm-wide committed margin, including extra margin and outstanding reservations |
| `day_peak_pnl`, `firm_total_pnl` | Today's high-water and current cumulative firm P&L, including float, fees, funding |
| `halted` | Current durable global/strategy halt state; exact false required |

Incomplete API coverage must set `complete=false`; absence of history must never be interpreted as zero losing bots. Observer failures and invalid/nonfinite values reject. A malformed registry suppresses forward fallback; a registered id always belongs to the canary tier even when its screen fails.

The result has `tier="LIVE_CANARY"`, `kind="canary_grid"`, fixed bracket parameters and allocated `invest`/`extra_margin`. This distinct kind deliberately prevents the current legacy planner/executor from accepting it without integration. CLO-238 must consume this kind, recheck the gate at create, enforce exact reviewed params and allocated margin, serialize reservations, implement retire/stop handling and supply live observations on every decision. It must not merely set an adapter flag. Executor fixtures must exercise concurrency, restart, partial API history, liquidation, funding, and loss/retirement handling. CLO-239 must include eligible canary ids in its setup allowlist through the same adapter without requiring live arming first.

The gate never reads credentials, writes a mandate, arms live, or sends orders. The CEO's delegated one-shot arming remains conditional on CLO-243 merged, CLO-238/CLO-239 done, CLO-241 HOLDS, and an actual ELIGIBLE canary.

## Coverage

| Scenario | Test | Result / remaining gap |
|---|---|---|
| Loose screen, no paper history | `test_loose_screen_initial_five_without_paper_record` | Synthetic pass, $5 |
| Scale/retire and repeated evaluation | `test_scale_and_retire_survive_repeated_evaluation` | Synthetic pass; live restart completeness belongs to adapter |
| Missing, stale, future, failed inputs | no-adapter, freshness, observer-error tests | Reject |
| Review revocation and changed evidence | pin mutation and registry tests | Reject |
| Margin/extra margin, halts, strict mandate | margin and loss-halt tests | Reject breaches; concurrency belongs to adapter |
| TP/SL, leverage, unsupported direction | bracket/leverage test | Reject breaches |
| Corrupt registry | registry test | Reject; no forward fallback |
| Existing health stop / forward requalification | health-stop and registry tests | Canary stays stopped; cannot reactivate via forward tier |

No live eligibility or performance claim is made from these synthetic tests. Remaining dependencies are CLO-238 adapter/enforcement, CLO-239 setup integration, CLO-237 reviewed positive evidence, CLO-242 applicable leverage certification, and CLO-241 independent HOLDS.
