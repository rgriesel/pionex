# CLO-129 confluence family and random-level controls v1

Source: CEO comment `38cb338c-7bac-433b-a6d3-26875b2cfbd0` dated
2026-10-25 16:52:38 UTC, referring to the owner-provided workspace document
`research/owner_method/owner_rules_v1.md`. This adds a separate hypothesis;
it does not replace the previously frozen band/support families.

Rules frozen **2026-10-25 19:02 SAST**, before synthetic validation, in
`pionex_lab/research/confluence_grid.py::confluence_family`. No market returns,
fills or performance series were read. This preparation is **INSUFFICIENT**,
not an executed performance test or a strategy PASS.

## Fixed family

BTC/ETH on 4H and 1D; mirrored resistance shorts and support longs; directional
fade and directional grid modes; 1x isolated perpetuals in both directions.
These 32 planned configurations include the random controls (2 pairs x 2
frames x 2 sides x 2 modes x 2 arms). Existing support-family 2x/3x plans remain
unchanged. The combined plan budget for the three prepared families is 56,
before owner copies. This is a planned ceiling, not trials already executed.
Every attempted configuration, including skips, must be registered before
its first forward observation. Any leverage expansion is a new registration.

Evidence adapter inputs are timestamped levels, ATR14, reference close and
decision time. It excludes future-known levels, rejects invalid types/data,
and requires at least three touches for SR input. The upstream indicator
pipeline must separately prove causal n=5 fractal confirmation, anchored VWAP
from the latest confirmed high/low, EMA50/EMA200, Fibonacci 0.5/0.618 of the
last confirmed swing and a frozen SR cluster definition. Reuse `swing/zoo.py`
EMA/ATR helpers and existing factor conventions. The adapter **does not build
or validate those indicators** from raw bars. The owner's exact SRchannel
parameters remain unknown; tagged input is not proof of correctness.

Confluence needs two distinct families from SR, AVWAP, EMA and Fibonacci in
a complete-link span no wider than 0.5 ATR. EMA50 plus EMA200 counts as one
family; likewise two Fibonacci ratios or both AVWAP anchors. Chained clusters
may not exceed the tolerance. Short entries require AVWAP-from-high plus
another type, wholly above reference; long entries mirror with AVWAP-from-low.
Target the nearest opposite-side confluence across reference, which need not
contain AVWAP. Stop one ATR beyond the entry zone's far boundary. No Elliott
coding, score or discretionary exception is included.

Plans wait for a touch from below (short) or above (long). An eventual runner
must observe a closed-bar trigger and fill at the next open using fresh quotes,
then revalidate stop/target geometry. The stored level is not a guaranteed fill.
Grid mode spans entry to target with ten geometric cells and a minimum step
of three round-trip fees. Both arms skip grid mode if either fails spacing.
Capital is fixed at 1,000 simulated USDT per configuration; cohort seven days.
There is no automatic parameter evolution for this hypothesis.

## R3 controls

The random seed is 20261025 combined with SHA256 of pair, timeframe, decision
timestamp and direction. Up to 100 draws choose a signed entry distance of
0.5..4 ATR from reference; take the first point more than 0.5 ATR outside every
confluence zone. Translate the whole zone, stop and target by the same amount,
preserving risk/reward distances, mode, costs, capital and horizon. Both arms
are skipped if no valid control exists; never rank unmatched survivors.

Controls use the same touch/next-open rules. The target is translated and does
not have to coincide with a real confluence. Distance from the current price
changes, so touch frequency, time in market and exposure must be reported;
this is a geometry-matched control, not an exact entry-distance placebo.
No draw may be selected using subsequent outcomes. Identical input gives the
same control, independent of Python hash randomisation or other strategies.

## Evaluation remains unstarted

Before evaluating returns: freeze and test the indicator pipeline, exact
control-comparison method and untouched chronological holdout, inferential
thresholds, bootstrap/multiple-testing procedure and stress protocol. The
owner document calls for at least 100 trades per rule, after-cost positive
expectancy, confluence beating R3, out-of-sample confirmation and DSR. These
requirements do not replace the firm's other unchanged qualification gates.
Report expectancy, hit rate, mean win/loss, break-through rate, samples,
paired uplift, funding, fees, spread/slippage and liquidation incidence.

CLO-37 still supplies dynamic futures-grid margin/funding/liquidation accounting.
CLO-128 is now **done**: owner-copy evidence is available in the workspace at
`docs/status/owner-grid-analysis-2026-10-25.md` and
`var/reports/owner_grid_attrib_2026-10-25.json`; integration remains to be done,
but CLO-128 is no longer an outstanding dependency. The persistent absolute-range paper
supervisor and causal indicator pipeline are not delivered by this adapter.
Every generated plan has `launch_eligible=false`, `liquidation_price=null`;
the report has `pass=false`, `live_eligible=false`. A 1x short is a perpetual
plan, never a spot short. No orders, scheduler or promotion path was added.

## Existing indicator coverage and limits

The workspace's `pionex_lab/research/owner_grid_levels.py` already contains
descriptive daily pivot/SR/AVWAP/EMA/fib calculations. Reuse that work when
building the causal forward pipeline rather than running the owner analysis
again. It is not ready to be passed straight into this adapter: daily bars
accept 23 observations, SR groups use adjacent-gap chaining, EMA50 and EMA200
are counted separately by its descriptive confluence function, and it does
not emit the source/availability evidence this adapter needs. These are
integration gaps; this change does not alter or rejudge that finished report.
The report's small confluence sample is adverse, not qualification evidence.

## Validation of adapter code

- Nine synthetic tests passed: distinct types, no chained wide clusters,
  causal visibility, SR touch minimum, directional anchors, next opposite
  target, deterministic non-confluent controls, paired geometry and fail-closed
  control generation. These tests do not measure market performance.
- Repository suite: 505 tests in 202.830 seconds; one skipped and only the
  known Windows `test_read_only_uri_encodes_awkward_paths` error.
- Skill-script suite: 12 passed. Staged whitespace check passed.
