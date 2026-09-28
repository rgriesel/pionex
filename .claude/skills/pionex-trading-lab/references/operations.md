# Runtime and recovery

## Boundaries and states

Use a persistent supervised external host for collectors, execution, reconciliation, and risk. A chat or skill is not an always-on host. Keep asynchronous research away from the stop/recovery path.

Separate the research identity from production code, policy, approvals, secrets, signer, and ledger. Pin artifacts and dependencies. Use independently gated immutable releases. An LLM with a shell that can modify the signer defeats this boundary.

Persist `SETUP -> RESEARCH -> PAPER -> LIVE_CANARY -> LIVE` plus `PAUSED`, `HALTED`, `UNWINDING`, `COMPLETE`. Log reason, evidence, actor, time, and policy hash. No live transition follows from time elapsed or target pressure.

Persist pause/stop latches. A transient data pause may clear after full resnapshot/reconciliation and 60 healthy seconds. Daily/weekly stops may clear only after the period ends and checks pass, with no remaining higher-level stop. Peak drawdown, absolute loss, policy tampering, authorization, or unexplained balances require a reviewed mandate decision; never auto-reset.

Keep keys in a server secret store. No keys in prompts, frontend, screenshots, logs, or source. Use reading/trading scope and IP restrictions; no transfers/withdrawals. Respect account/region rules and use authorized official APIs. Send alerts only through user-authorized destinations.

## Preflight and execution

Verify isolated funded scope, authorization/policy hash, strategy qualification, fees, symbol filters, complete/fresh data, reconciled balances, remaining budgets, independent monitoring, and proven protective exits. Record stop trigger basis, fill behavior, residuals, and recovery. Stop-limit orders may remain unfilled.

The default requires exchange-side protection. Standard spot order documentation alone is insufficient. A supported bot must prove inventory liquidation, balance coverage, minimum investment, and suitable strategy evidence. Never substitute an untested grid just to obtain a stop field. If unavailable, remain paper-only and report why.

Set invalidation from the strategy, then size from executable prices, conservative exit assumptions, both-side fees, and impact. Do not narrow the stop to enlarge a position. Use Decimal, round quantity down, and validate all exchange minima/maxima. Never round up to meet a minimum.

Reserve capital, entry fees, and planned loss atomically in the signer. Require a current account snapshot version. Include open/pending/partial orders and bot inventory. Recheck every fill. Use one writer with a durable lease/fencing token. The included sizing helper does not implement these production mechanisms.

Persist intent and a unique client ID before sending. Timeouts have unknown outcome. Resolve the original ID and fills before retrying; do not assume idempotency. Use bounded jittered backoff and a shared weighted limiter with exit/recovery headroom. Honor bans.

Cancel stale entries. Accepted orders are not fills; cancellation requests are not confirmed cancels. Handle cancel/fill races. A limit order can be a taker. Use a default four-hour maximum holding period; monitoring 24/7 does not require trading continuously.

Separate exit from entry admission. Entry halts, high spreads, weak edge, or spent daily budgets must not block risk-reducing exits. Cap spot sales to verified owned/available quantity net of fees and pending sells; reconcile locked balances. Never oversell. If balances are uncertain, reconcile urgently rather than guessing.

Reconcile startup, reconnects, order transitions, and periodic state within the rate budget. Preserve redacted responses. Order events in UTC; display Johannesburg time if useful. Monitor clock skew, book sequence gaps, account/feed age, service heartbeat, disk, and backlog. A fresh top-of-book timestamp does not establish book consistency.

## Failure behavior

| Event | Required action |
|---|---|
| Stale/gapped data | Freeze entries, cancel stale entries, resnapshot, retain native protection |
| Order timeout | Query original ID/fills; no blind duplicates |
| Manual trade/balance mismatch | Freeze entries; reconcile all scopes; expose discrepancy |
| Missing/rejected protection | Stop entries, attempt verified unwind, alert, show unprotected state |
| Loss threshold reached | Latch, cancel entries, unwind per policy; show residual risk |
| HTTP 429 | Honor retry/ban interval; never hammer |
| Exchange/network outage | Keep native protection; no entries; reconcile on recovery; disclose unavailable exits |
| Process restart | Recover latches/reservations; reconcile before ordering |
| Compromised key | Disable signing and follow authorized revocation without exposing keys |
| Quote depeg/disabled market | Freeze entries, show native and USD marks, use predeclared exit plan if executable |
| Cost ceiling | Stop new paid work; preserve protection/monitoring; unwind before resources run out |

Ensure monitoring fits the budget before deploying. Loss thresholds are action triggers, not insurance: gaps, slippage, outages, fraud, or custody failure can exceed them or lose the entire exchange balance.

## Acceptance checks

Test stale/missing data, NaN/negative inputs, conversion, lot rounding, base-denominated fees, minimums, duplicate submission, partial fills, cancel races, clock skew, weighted throttling, concurrent reservations, crash recovery, persistent stops, tampered policy, and account scope. Do not place real orders merely to satisfy a test without existing authorization and a qualified mandate.

Demonstrate the research identity cannot raise limits; the signer refuses unqualified versions and stale state; halted entries still permit verified exits. Connect the dashboard to an actual ledger before labeling it connected. Distinguish mocked tests from observed exchange tests. A small unit-test suite is not a production audit.
