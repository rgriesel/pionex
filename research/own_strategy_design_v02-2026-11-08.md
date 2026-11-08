# Own strategy v0.2: interior grid and persistent regimes

CLO-257. Frozen proposal: 2026-11-08 03:52:48 SAST (UTC+02:00).
DESIGN ONLY; zero strategy evaluations. Independent Red Team design/null review and
explicit board confirmation remain outstanding. This document grants no trading authority.

## Evidence and scope

Preserve `own_strategy_design-2026-10-28.md` byte for byte. Its v0.1 verdict remains
**BROKEN**, independently recorded in CLO-160, comment
2799124e-6e8e-4137-8699-22ce04febf11, 2026-10-28 10:59 UTC. Do not run v0.1.
WHY: grid boundary fills conflicted with exits, classifier churn, unfundable small-capital
sleeves, and nulls that confounded trend timing with allocation. WHAT could change that:
interior levels, hysteresis and isolated allocation/grid nulls. NEXT: this separately
registered v0.2, subject to review; no parameter selection from strategy returns.

Read the strategy log, grid/trend playbook, edge-candidate specifications, research-evidence
supplement, original design and full CLO-160 review. No v0.2 test appears in the log or
registry audit. This is an independent rules hypothesis, not a clone of discretionary
owner entries. Historical owner figures in v0.1 are preserved as old, qualified evidence;
none is refreshed, endorsed as net profit, or used to set parameters here.

Mechanism remains directional persistence plus bounded inventory serving two-way flow.
Hysteresis may preserve trends but delay exits; interior levels may permit cycles but
increase turnover and adverse selection. Neither improvement establishes an edge.

## Exact rules proposed for review

One shared 1,000-USDT ledger; unlevered spot, long/cash, zero cash yield. Reserve 80% of
current NAV for trend and 20% for grid, never borrow across reserves. No overlapping sleeve
ownership. Close the old sleeve first, deduct all costs, then size the next from remaining
NAV. An unavailable liquidation reserves its capital and prohibits the other sleeve.

Daily decision at 00:00 UTC uses closed bars strictly before that instant. Observed open
execution follows the decision; never use that day's close. Consecutive calendar lookbacks,
no compressed missing days. Missing BTC inputs force STRESS; missing coin inputs forbid
new buys and require exit at the next observable tradable open. No fabricated fills.

Use v0.1 ER20 exactly: absolute 20-day close change divided by sum of 20 absolute daily
changes; zero denominator gives zero; require all 21 closes. Crash is trailing BTC
30-day close return <= -25%. RANGE veto is BTC r20, r60 and r120 all strictly negative.
Initial state UNCERTAIN. At every daily decision apply this ordered transition table:

1. Missing required BTC history or crash => STRESS immediately, overriding persistence.
2. Otherwise ER20 >= 0.35 => TREND, including from STRESS.
3. Otherwise ER20 <= 0.20 and no RANGE veto => RANGE, including from STRESS.
4. Otherwise retain yesterday's TREND if ER20 >= 0.20.
5. Otherwise retain yesterday's RANGE if ER20 < 0.35 and no RANGE veto.
6. Otherwise UNCERTAIN. STRESS never persists after its condition clears by itself.

At ER20=0.20, eligible RANGE wins over TREND retention; a vetoed TREND can retain at that
boundary. At ER20=0.35, TREND wins. RANGE veto exits RANGE immediately; it does not veto
TREND. This is causal hysteresis with no discretionary duration or hindsight regime.
Record transitions, turnover, dwell time and missed trend attribution only in the later test.

Trend rules stay CTA v1.1: PIT monthly top-10 trailing-90-day median quote volume, original
exclusions and 120-day eligibility; 2-of-3 positive 20/60/120-day returns; vol30 sizing,
target 0.40 on its reserve, drifted weights and 2 percentage point rebalance band. Scale
is one in TREND and zero otherwise. No reallocation of unused coin weights. Retain
delistings and existing 50% last-mark haircut stress. Reuse `cta.simulate(scale=..., universe=...)`.

### Interior executable grid, separate exit band

Only BTC in RANGE. On each permitted daily entry freeze L=min low and U=max high of the
last 20 closed daily bars. Require L>0, U>L, observed entry open strictly between L and U.
Define g=(U/L)^(1/6). Four cells have five levels L*g^i for i=1,2,3,4,5.
Thus the lower stop boundary L and upper take-profit boundary U are each one unrounded
log-cell outside the tradable grid. This deliberately replaces v0.1's two boundary cells.
Require entry open strictly inside the interior endpoints, otherwise skip that entry.

Round buy levels down and sell levels up to the symbol price tick. Preserve the same
cell identities; reject if rounded ordering is not strict, cells overlap, endpoints are
not strictly inside L/U, or either external boundary is less than one smallest rounded
cell distance away in log price. Reject if the smallest executable sell/buy percentage
step is <3 times the full assumed round-trip cost. No changed cell count to rescue a skip.
Recheck against each scenario's stressed costs, so stress can change entry eligibility.

Use `grid.levels` geometry and equal-base-cell inventory accounting, with four cells.
At entry a cell below the open holds quote for its lower buy; a cell above the open holds
base for its upper sell (exact equality follows `bisect_left`). Choose one base quantity
q by flooring the affordable quantity to the quantity tick after reserving initial market
purchase costs, all pending buy costs, and liquidation cost on maximum four-cell inventory
at U. Initial base cells are bought at the observed open, charging all frictions. Never
round quantity up. Require every potential cell buy AND sell notional after rounding to
meet max(10 USDT, applicable exchange minimum), quantity limits, and sell/dump minimum.
Reject otherwise. No top-ups, leverage, averaging-down override, or cross-sleeve subsidy.

Fill only after creation, beginning with the next complete hourly bar. One-tick penetration,
no same-tick recycling; process both O-L-H-C and O-H-L-C paths from the same starting ledger,
book the worse end-hour NAV and retain that path's state (ties low-first). A new fill can
arm its opposite side only on a subsequent path segment, never at the same tick. Gap
opens crossing pending limits execute at the limit without favorable price improvement,
then apply adverse costs; use actual open for liquidation. Primary uncertainty includes
no fill guarantee or reconstructed queue; alternate fixed paths remain mandatory.

At the first hourly close <=L or >=U, daily state other than RANGE, or elapsed 72 hours,
cancel simulated pending cells and liquidate at the next observed hourly open. Boundary
U is a full-inventory profit exit, not a guarantee of positive net P&L. No fill at a
boundary or expiration close. On a scheduled state/expiry exit, cancel before processing
that next hour; on a newly observed boundary close retain prior-hour fills and exit next
open. Gaps execute at the actual price. Missing opens delay exit and prohibit new entries.
After actual exit wait 72 elapsed hours; re-entry only at a later daily decision.

### 100-USDT feasibility is explicitly unresolved for deployment

Run identical rules at 100 USDT only as the retained T9 diagnostic. The 20-USDT reserve
cannot fund four cells each >=10 USDT plus costs. Grid feasibility is **NO by construction**,
even before precision. Ten equal trend allocations from 80 USDT are also below minimum;
vol weights may fund some coins but must not be rounded or redistributed to force trades.
Report executable purchases, skips, exposure and all-cash days. Zero exposure cannot be
evidence of low-risk strategy viability. No full composite eligibility at 100 USDT can
follow from this diagnostic, even if T9's numerical ruin bounds pass.

A BTC/ETH canary with a different reserve/cell shape is a possible NEW idea; it is not
adopted, selected, registered for evaluation, or implicitly approved here. Increasing
capital or altering 80/20 after results would also require a separate registration.

## Data audit and free-source reconciliation

`own_strategy_v02_manifest-2026-11-08.json` records database/table coverage, source hashes,
registry logical digest and source totals, current public Pionex rules/quote, and BTC
hourly-to-daily reconciliation. Read-only SQL and OHLCV aggregation are data integrity
checks, not strategy calculations. Local SQLite backups under
`var/research/clo257_inputs_2026-11-08/` freeze the input vintage. Their SHA256s are authoritative;
live source database hashes are observations and may change as other agents append.

Binance PIT symbols use `BTCUSDT`; normalized proxy stores use `BTC_USDT`. Normalize
explicitly without merging distinct listings. Prefer early_1h before 2022-10-01 and
proxy_market thereafter, compare duplicate hours, reject conflicting OHLCV rather than
choose whichever improves results. Daily aggregation uses UTC open/close, max high,
min low and summed volume; tolerate max(1e-6 absolute, 1e-6 relative). No interpolation.
Archive provenance: existing free Binance public archives, all labelled PROXY.
The 31 missing hours are absent in checksum-verified official daily hourly ZIPs across
18 affected/check dates (including volume-check dates), not recoverable ingestion omissions.
Three days have equal OHLC but inconsistent daily/hourly base volume. On 2021-01-21 the
frozen PIT daily volume also differs from the official daily archive: apply exactly the
one official daily OHLCV/quote-volume overlay in `frozen_daily_corrections` before PIT
ranking. On the other two days the frozen daily row matches the official daily archive;
retain that daily volume for ranking and keep hourly volume source-specific. BTC hourly
volume is not a signal. No other row changes, interpolation or data-dependent selection. Current
Pionex rules are current observations, never historical membership or a verified fee tier.

The PIT archive ends 2026-09-30, not v0.1's intended 2026-10-27. Explicit proposal:
freeze historical diagnostics at 2026-09-30 using the reconciled common overlap from
2020-01-01; do not silently splice proxy daily bars into the PIT ranking universe.
This cutoff change needs independent review and board confirmation. Refreshing the whole
PIT universe through October from free Binance archives is the alternative, requiring a
new manifest/version before evaluation. No paid service/account/key is required.

Historical gaps/conflicts remain disclosed in the manifest. No historical test until
input integrity is signed off; gaps invoke the frozen no-entry/delayed-exit rules, not
an invented mark. Preflight still requires >=30 aligned Pionex/Binance BTC and ETH daily
days, median absolute close difference <=0.5%, p95 <=1%, plus hourly BTC comparison.
That tracking preflight and historical exchange-rule vintage are not established by one
public quote. Transfer evidence stays INSUFFICIENT until reconciled. No collector or
exchange rules are changed here.

## Controls and nulls frozen before evaluation

Controls on identical dates/costs and shared capital constraints: A ungated PIT CTA target
0.40; B A uniformly scaled to base realized mean gross exposure (ex-post diagnostic);
C exact composite with grid reserve in cash; D grid sleeve only, same 20% reserve,
causal RANGE schedule and cash otherwise. Also report passive PIT hold as the existing
descriptive baseline, never a selectable replacement. Attribute initial inventory drift,
completed pairs, remaining marks and costs without subtracting fees twice.

All nulls replay the full coordinator and ledger on unchanged prices, rebuilding bands,
costs and eligibility. Never shift realized profits. 10,000 draws per family, seed 20261108
plus family number. Use p=(1+count(null>=observed))/10001 for BOTH total daily net mean
and net Sharpe. Each family and statistic must pass the current registry permutation
threshold; apply an additional Bonferroni factor of eight across four families x two
statistics. T4's existing requirement remains additional. Undefined statistics are
INSUFFICIENT; all-cash draws count conservatively as ties, never silently discarded.

1. Whole-package timing: independently circular-shift each coin's pre-cost CTA target
sequence and shift the frozen causal state schedule by offsets uniform in [30,T-30].
Recompute inventory from prices; signals are causal in the base, shifted schedules are
explicitly artificial nulls. This keeps the original package-timing question.
2. Seven-day block permutation: permute contiguous seven-day blocks of paired target/state
records (last partial block included), then replay ledger; original v0.1 second family.
3. State-only timing: shift only the complete hysteretic state schedule by a uniform
offset in [30,T-30], locking CTA votes/volatility/targets to original prices and days.
Rebuild grid at resulting entries. Safety crash/missing-input veto always overrides a
shifted state. Record resulting exposure and episodes, not exact-match claims.
4. Grid-only timing: compare D with D replayed on a circularly shifted RANGE-permission
mask, same uniform offset range, daily opportunities, holding/exit/cooldown and safety
veto. This places range entry opportunities randomly in time while preserving clustered
opportunities. Actual accepted count can differ because feasibility depends on price;
report it. Do not randomly move trend signals in this family.

No null is a tradable alternative; no draw can replace the nominated base. Red Team must
specifically assess whether the state-only/grid-only nulls sufficiently isolate allocation
and cycles from BTC drift. If rejected, revise registration before evaluation.

## Budget and unchanged gates

Proposed total conservative trial reservation **126**: original CTA neighbor grid 27
(includes base) + controls A/B/C/D =31, at 1x/2x/4x costs =>93; ten one-at-a-time
structural neighbors at all three costs =>30; two alternate fixed base paths + one
identical 100-USDT base diagnostic =>3. Total 126. Passive-hold reporting and resamples
are inferential/descriptive, never selectable candidates. No other runs authorized.

Ten structural neighbors, all other rules fixed: trend-entry ER {0.30,0.40}; lower ER
boundary {0.15,0.25}; interior cells {3,5} with N+2 log intervals and one outer interval
on either side; grid reserve {0.10,0.30} with trend reserve complement; grid expiry
{48h,96h}. Primary remains four cells, 0.35/0.20, 80/20,72h. Each immediate neighbor
must meet existing T5 CAGR>0 and Sharpe>=0.6*base, an additional proposed requirement.
No selecting a neighbor. All scenarios consumed/reserved even if later skipped.

Reserve the 126 append-only in `var/trials.db` as DESIGN_RESERVED, zero runs, unique ref
CLO-257:v02 before any evaluation. Manifest records before/after count and exact level.
The reviewed v0.1 never ran and had no reservation; do not add fictitious 93 executed
trials. Never subtract this reservation later. At launch re-audit the registry, include
all other reservations, and use the stronger current count-dependent thresholds. An
unreconciled registry is INSUFFICIENT. Prior count 275/368 is stale.
Actual reservation audit: 175 rows/297 weight ->176 rows/423 weight. Level 2 requires
DSR>=0.97, PBO<=0.15, permutation p<=0.0033333333333333335 before additional null-family
correction. Registry is still a lower bound for historical unlogged variants; full
launch reconciliation and stronger current thresholds remain required.

**All five proposed gate groups in v0.1 remain conjunctive, including** 750 days, 25 grid
episodes, three RANGE clusters separated by >=7 non-RANGE days; base Sharpe>=1, DD<=35%;
Sharpe>A and B overall and >A in two thirds; positive paired raw-return lower bounds
against A/B and C; positive total net grid P&L and each-third sleeve mean; coin positive
contribution cap 35%; all cost/path/missing/delisting checks; every CLO-44 T1-T9 check.
Use 126 instead of 93 for this proposal's multiplicity corrections. At 4x retain both
the composite >=0.50 floor and the existing PIT >=0.85 floor wherever applicable; no
weaker gate replaces a stricter inherited one. Unsupported checks are INSUFFICIENT.

Reviewer proposals to replace raw-return superiority with a Sharpe-difference or
volatility-matched control, or remove Sharpe>B, are **NOT adopted**. Report paired Sharpe
differences descriptively using the same draws, with no new route to PASS. They cannot
rescue a failed original gate. The possible mismatch between the economic question and
raw-return superiority remains disclosed for the board, not silently repaired.

For paired A/B bounds retain circular ten-day paired blocks and alpha=0.05/(2*126);
for C use alpha=0.05/126. Freeze **2,000,000** draws per comparison/window, seed 20261108,
ten consecutive batches of 200,000. Report pooled bound, every batch bound, expected
tail count and exact binomial 95% order-statistic rank interval around the target quantile.
Require pooled bound, lower endpoint of that rank interval, and every batch bound >0.
No adaptive draw additions; unstable sign => INSUFFICIENT. Preserve separate T6's
20-day/2,000-draw/2.5% test. This strengthens precision without relaxing alpha.

Historical diagnostics are seen-market evidence, with 365 warm-up days, nonoverlapping
year folds, last partial retained, holdings carried and no refit; also equal thirds.
Untouched validation begins first 00:00 UTC after reviewed implementation/docstring and
final data manifest are committed, runs 750 consecutive days and is scored once. Current
audit/design work does not start that clock. No earlier historical slice is untouched.

Costs unchanged: 5bp fee + >=2bp slippage + half-spread per side on every inventory
change, including initialization, switch and final exit; `cta.COST` for known proxy
pairs, 10bp full spread fallback for others. Forward uses current public spread/depth
and >=2bp impact floor; quote age<=5s, symbol rules<=1 day; no maker rebate. Snapshot
assumptions before launch, never claim a public quote confirms a fee tier. Stress all
costs at 2x/4x, using consistent controls. No funding for unlevered spot.

Local stdlib only; one historical evaluation launch, no performance-based retries,
four CPU hours maximum as in v0.1. Larger bootstrap may exhaust this budget: save audit
and stop INSUFFICIENT, never reduce draws or relax gates. Any budget increase is a
separate board-confirmed registration amendment before launch, not granted here.

## Implementation coverage and independent handoff

Reuse `swing/zoo.py` walk-forward conventions, `swing/factors.py` PIT conventions,
`swing/pit.py` universe, `swing/cta.py` scale hook, `swing/overlays.py` paired blocks,
`research/metrics.py` bootstrap conventions and `research/luck.py` thresholds/registry.
`grid.py` geometry/accounting is reusable; its touch fills, same-candle path and boundary
stop execution are unsuitable unchanged. A future research-only coordinator must handle
the shared ledger, precision, cancellations, next-open exits and full null replay.
No simulator, settings, risk engine, mandate, lock or order path is modified in this task.

Before any run copy reviewed rules/gates/seeds/budget into the new function's docstring
with a fresh actual SAST timestamp; commit it and synthetic tests. Tests must cover state
boundary precedence, crash overrides, empty/missing histories, four interior cells,
rounded spacing, initial/base cash conservation, 100-USDT rejection, same-tick no-recycle,
gaps, exit priority, cooldown, both path states, null isolation and registry idempotency.
Run both firm suites; do not invoke strategy/luck performance commands for validation.

Request independent Red Team design/null review of this exact document and manifest.
Request CEO routing for explicit board confirmation of rule changes, cutoff, 126-weight
budget, stronger inference and all inherited gates. Silence, task closure, or reservation
is not approval. Future historical implementation/evaluation stays backlog until those
dependencies and data-integrity/tracking preflight are satisfied.

Design result: **NOT RUN â€” REVIEW PENDING**, not PASS/FAIL performance. Save design
audit JSON in `var/reports/`; no fabricated strategy-log performance row. Later evaluation
gets exactly one row and report; FAIL/INSUFFICIENT must state WHY/WHAT/NEXT as a new
registration. The 100-USDT construction's known infeasibility remains explicit regardless
of future 1,000-USDT performance. Backtests and paper records cannot prove future profit.
