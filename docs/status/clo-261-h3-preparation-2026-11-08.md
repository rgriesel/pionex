# CLO-261: existing H3 trial 171 preparation

Data preparation completed; strategy remains **PREREGISTERED, NOT RUN**.
No signal counts, strategy returns, new registration, or eligibility evidence.
H3 execution ownership is CLO-261; H1/H2 remain CLO-247. CLO-257 and CLO-159 are unchanged.

Frozen source `pionex_lab/research/own_edge_clo247.py` matches registry 171:
SHA256 CRLF `4d18507a0149f011e54661e12e67eea47dff6b8608e5d75775d51703069cbbbb`;
the identical LF Git blob is `f150c7211e6adadce88f48d7a545d8fc14bf491aa8e00bfecd982dbabeee368c`.
No rule edits. Preserve 24h planned hold, always-active 1.5 ATR14 stop / 3 ATR14 TP,
$10 notional, spot long/cash, no leverage, and original costs and proposed gates.
Existing registration remains counted once; no performance evaluation has occurred.

Data-only snapshot: `var/research/clo261_h3_inputs_2026-11-08/manifest.json`
and its two hashed hourly JSON files, from a single read-only SQLite transaction.
Interval is the original [2023-01-01, 2026-10-01) UTC. Binance spot **PROXY**,
base BTC / ETH volume, not quote turnover or liquidations. Volume mapping is
confirmed against existing archive parser column 5. This is local data lineage,
not a fresh independent venue-source reconciliation. Original archive checksums
and Pionex tracking evidence must be audited before any eventual screen.

| Symbol | Expected hours | Present | Missing UTC hour | Complete 4h bins |
|---|---:|---:|---|---:|
| BTC_USDT | 32,856 | 32,855 | 2023-03-24 13:00 | 8,213 / 8,214 |
| ETH_USDT | 32,856 | 32,855 | 2023-03-24 13:00 | 8,213 / 8,214 |

The incomplete 12:00 UTC 4h bin is excluded. **Neither full sample is contiguous.**
The unchanged strategy validator rejects concatenating across this gap. No missing
bar was filled, no segment-reset rule invented, and the interval was not shortened.
Each symbol has one zero-volume hour, retained explicitly rather than treated as absent.

| Scenario | Coverage | Observed result | Remaining gap |
|---|---|---|---|
| Exact hourly bins/base volume | new synthetic preparation tests | four-hour volume sums conserved | source-vintage audit before screen |
| Internal/boundary gaps | new synthetic preparation tests | incomplete bins omitted; missing timestamps explicit | source repair if real observation exists |
| Duplicates/order/partial/NaN/OHLC errors | new synthetic preparation tests | rejected | none for these fixtures |
| Cross-gap strategy input | unchanged validator, synthetic test | rejected | full interval cannot run as currently frozen |
| Causal H3 confirmation/next-open/stop-first/time exit | existing 8 mechanics tests | pass | market evaluation prohibited pending dependencies |
| Emergency TP before 24h | new synthetic mechanics test | target remains active on entry bar | no execution authority implied |

Exact outstanding decision: **CLO-247 owns CEO/board confirmation of its proposed
screen gates** (100 closed trades, 25 UTC exit weeks, PF >=1.1, positive expectancy
and both fixed halves, 7-day bootstrap alpha=.05/firm-wide trials, 200,000 resamples,
seed 20261107, positive expectancy at 2x and 4x costs). No confirmation was found
in its issue comments; preparation is not confirmation. CLO-253 receives this handoff.
Data dependency: establish authentic missing-hour coverage for the exact frozen
interval, or route any changed missing-data/interval rule through a new approved
specification and trial; do not silently change trial 171. No variant is registered
by this preparation assignment. Historical archive remains screening-only, never
untouched OOS; original Pionex forward evidence and unchanged firm gates still apply.

Protocol metadata correction: the initial preparation docstring mistakenly said
03:57:00 SAST, later than the first invocation at 03:55:45. File creation records
03:55:31 SAST and the complete rules were written before execution. Corrected the
timestamp to that creation time; no rules or data selection changed. This is not
a new strategy preregistration or a claim of a performance run.

Disposition: CLO-261 backlog on CLO-247 gate confirmation and exact-interval data
continuity/source evidence. No strategy PASS/FAIL/INSUFFICIENT issued. Any eventual
PASS stays open for CEO-required independent Red Team review, maxReviewRounds=2.

Validation: 14 focused synthetic tests pass (6 preparation/mechanics plus 8 frozen
mechanics); 12 skill-suite tests pass. Required full suite ran 578 tests in 226.165s,
one skip, only the documented Windows `test_read_only_uri_encodes_awkward_paths`
error (WinError 123). The additional early-TP test was added after full-suite
discovery and passed in the final focused run. `git diff --check` passes.
