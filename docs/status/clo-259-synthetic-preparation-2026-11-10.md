# CLO-259 H6b preparation — NOT RUN

Trial 173 remains NOT_RUN / PENDING_CONFIRMATION. No historical signal or return
evaluation, new trial reservation, performance verdict, production evaluation
sentinel, or strategy-log performance row was created. Dependency: CLO-253 board
confirmation of inherited gates and authorization for one adaptive historical
evaluation. CEO selection does not supply that confirmation.

Implemented `pionex_lab/research/h6b_clo259.py` with frozen rules, gates and SAST
timestamp in `h6b`'s docstring. Reuses parent `lead_stats` and H5b bar validation.
The pure simulator and guarded callback harness have no historical CLI or order
path. The harness locks the existing trial, recomputes weighted trial count, and
creates its report before calling evaluation. Pending authorization, prior
attempts and interrupted attempts refuse execution. Tests use temporary synthetic
registries and reports, never the production trial registry.

| Scenario | Synthetic coverage | Result | Remaining gap |
|---|---|---|---|
| Delayed fill, exact tick, touch, expiry, busy signals | FillChecks | PASS | Candle evidence cannot prove queue priority or post-only acceptance |
| Ambiguous stop, adverse gap, fill-bar TP sequence, timed open | FillChecks | PASS | Exact intrabar fill time unknown |
| Missing pending bars and held inventory | FillChecks | PASS | Coin halts unresolved; future report must retain the uncertainty |
| Frozen signal geometry, full notional, funding, 1x–4x friction | FillChecks | PASS | Binance spot is PROXY for Pionex perps |
| Authorization, interruption, duplicate and changed-input refusal | HarnessChecks | PASS | Independently verify board comment before authorizing existing reservation |
| Row identity, incomplete lookbacks, prefix invariance | FillChecks | PASS | Future loader must verify manifest and cutoff before callback |

20 H6b checks passed. Required main suite: 622 tests, one skip, one error:
`test_read_only_uri_encodes_awkward_paths` raises WinError 123, the known exception
documented in FIRM_RULES.md. Required skill suite: 12 passed. No tests weakened.

Input rows were fingerprinted without computing signals or returns, preserving
early-archive duplicate precedence, hourly holes and cutoff 2026-10-12 23:00 UTC.
The manifest covers BTC/ETH and all eight alts. Half-spread is frozen at the
registered 5bps/side fallback. Existing official fee and symbol evidence is reused.

Sequencing assumptions are explicit before any historical evaluation: no fill on
submission bar; pending gaps halt the coin because an unseen fill is possible;
held gaps halt with unknown inventory; adverse stop gaps use the worse open;
stop wins ambiguous bars. On an intrabar entry, a favorable candle extreme alone
cannot prove a later TP crossing. That fill-bar TP requires close beyond TP;
open-through fills activate exits immediately. Intrabar exits reserve the full
containing hour, following H5b's conservative exposure convention.

The registered SHA256 `bef1e627...13f873` covers the original CRLF bytes.
The published branch did not yet contain this H6b registration, so delivery adds
those exact original bytes and a file-specific `-text` Git attribute. This
preserves its hash on fresh checkouts without changing the frozen specification.
The production harness and synthetic fixture both check the original bytes.

Before evaluation: obtain the scoped board confirmation, wire a manifest-verified
cutoff-limited historical loader and the unchanged parent metrics to the harness,
and refresh public evidence if stale. Reuse trial 173; recompute weighted count
at execution. Historical eras remain exposed adaptive screening. Quote-based
forward evidence is separately required before promotion. PASS stays open for
independent Red Team (maxReviewRounds 2); FAIL/INSUFFICIENT needs WHY/WHAT/NEXT
and a separately registered queued successor. No routine Telegram.

Evidence: `var/reports/clo259_synthetic_readiness_2026-11-10.json` and
`var/reports/clo259_input_fingerprints_2026-11-10.json`.
