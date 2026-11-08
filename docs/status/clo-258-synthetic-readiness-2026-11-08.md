# CLO-258 H5b synthetic implementation readiness

Latest CEO direction: prepare existing trial 172 only. Historical evaluation is NOT RUN.
No new trial, performance verdict, evaluation sentinel, or historical return calculation.
Research only; no live eligibility or profit claim. No routine Telegram notice.

The prior H5 simulator has three rungs, no adverse stop-gap fill, no half-spread,
and different exit timing. It is unsuitable for H5b. The new pure simulator reuses
`research/own_edge_b_clo248.py:h5_signals` unchanged, with separately testable
validation, execution costs, and single-position fills. Only the parent source and
its tests are integrated from commit 1620a18; unrelated parent branch history is excluded.
The parent's disputed pre-registration chronology remains as disclosed in CLO-256;
its old docstring is not evidence of H5b registration or approval.

| Scenario | Synthetic coverage | Readiness / remaining gap |
|---|---|---|
| Real compression signal -> return inside range -> opposite entry | `test_real_parent_signal_integration_on_synthetic_compression` | Checked with synthetic prices only |
| Frozen range and ATR; first close, fourth-hour limit, inclusive range boundary | confirmation, boundary, geometry tests | No entry on confirmation bar; no retry for better geometry |
| Pending candidate / held position | overlap test | One position per coin; signals during pending/holding ignored |
| Long and short; immediate brackets; ambiguous candle | symmetry and stop-priority tests | Stop precedes TP, including entry candle |
| Adverse stop gap / favorable TP gap | gap tests in both directions | Worse opening stop fill; no favorable TP improvement |
| 96 elapsed hours, scheduled-open extremes | time-exit tests | Open at entry+96h; later candle extremes cannot affect open exit |
| Missing lookback, confirmation, entry | missing-window tests | No interpolation, synthetic fill, or delayed entry |
| Missing active-position bar / truncated history | unresolved-position tests | Explicit unknown inventory; stop processing that coin, not silent removal and resumption |
| Full notional, fee/slippage/spread/funding | arithmetic and stress tests | Default 13bps/side; funding charged on both sides; execution-only 2x/3x/4x |
| Causal excursion / malformed inputs | prefix-invariance and invalid-data tests | Future excursion cannot move frozen stop; reject invalid OHLC/costs |

Conservative timing convention: intrabar exits are timestamped at the containing
hour's end for funding/exposure; known gap/time exits use the opening timestamp.
Inventory is 1x notional, and inventory-notional-hours are recorded. This is a
linear PROXY short simulation, not evidence of venue short availability or liquidation safety.

Frozen specification unchanged: original workspace CRLF bytes SHA256
`9ff7dee18ee8a3790beea369f37954b7d8c67a1bf3825024370f49feeb261d9e`;
Git/LF canonical bytes SHA256
`ce60ad444cd7f7b47f18ce2f90ab8561a0e7574fe884ba928fabaedfc4f21b72`.
Only newline encoding differs. Registry 172 remains weight 1, PRE-REGISTERED NOT RUN,
gate status PENDING_CONFIRMATION. No registry mutation is needed for preparation.

Exact unresolved approval decision for CLO-253: confirm the inherited screen gates
and explicitly authorize the ONE adaptive historical evaluation of existing trial 172:

- At least 100 trades in each of full and final eras; fewer => INSUFFICIENT.
- Positive mean net in each era; final profit factor >=1.2.
- Positive final mean at 2x execution costs; positive final mean excluding best trade.
- Positive final one-sided 95% three-day block-bootstrap lower bound.
- Report additional Bonferroni 0.05/max(295,current SUM(weight)), 3x/4x costs,
  without replacing or weakening gates. Previously exposed eras are adaptive
  successor screening, never untouched OOS.

Preparation is ready for review at the simulator level. Before any authorized return
evaluation, finish the separate create-only evaluation harness: frozen row fingerprints,
existing-trial accounting, paired same-signal continuation diagnostic, report metrics,
and gate evaluation using current research.metrics defaults. Those reporting steps
were not run under preparation authority. A data gap leaving unknown inventory must
be disclosed and cannot support PASS. No synthetic result is a strategy FAIL/INSUFFICIENT.
Any eventual FAIL/INSUFFICIENT needs WHY/WHAT/NEXT as a separately registered queued
variant; any eventual PASS stays open for CEO-assigned independent Red Team,
maxReviewRounds 2. Separate forward Pionex evidence remains required for promotion.

Validation totals and publication evidence are recorded in
`var/reports/clo258_synthetic_readiness_2026-11-08.json` and the issue closeout comment.

Validation: 19/19 H5b synthetic checks pass. Full suite: 596 run, 594 pass,
1 skip, 1 known error (`test_read_only_uri_encodes_awkward_paths`, WinError 123
on a Windows-illegal question mark in a test directory). Lab-skill suite: 12/12 pass.
No new failure is attributed to H5b; the documented baseline error remains unresolved.
