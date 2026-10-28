# Own strategy: persistence when trending, bounded inventory in ranges

CLO-158, Quant. Design frozen 2026-10-28 12:54 SAST (UTC+02:00).
Status: PROPOSED; no strategy code, performance calculation or test run in this assignment.
Red Team must review this design and the board must confirm the proposed gates before execution.
This document is the idea card and proposed registration; the future function docstring must copy
the reviewed rules, gates, seeds and SAST timestamp before running. A review revision remains visible
as a new version. This is paper research, with no order path or trading authorization.

## Decision and first principles

Build one falsifiable composite rather than restart indicator discovery. The proposed economic
sources are (1) gradual directional repricing, which a slow trend position can follow, and (2)
temporary two-way demand for liquidity inside a stable range, which bounded spot inventory can
serve. Neither mechanism is established by this proposal. Trend loses through whipsaws and late
exits; liquidity provision loses through adverse selection and range breaks. A causal regime rule
must distinguish those paths early enough to cover switching costs. Volatility sizing controls
exposure; it is not a separate source of expected return.

The new hypothesis is that allocating to these different inventory policies using path efficiency
adds return beyond simply holding less trend exposure. It can fail even if both mechanisms sound
plausible. Combining two losing rules does not create an edge. Keep the grid small and require it
to earn its own place. Cash earns zero throughout. No leverage, shorting, yield product or model
training is part of this design.

## Evidence ledger and novelty check

Sources read before design: `docs/STRATEGY_LOG.md`, `research/edge_candidates_2026-10-14.md`,
`research/ideas/2026-10-28.md`, `docs/status/owner-grid-analysis-2026-10-25.md` (CLO-128),
`docs/status/clo-127-why-no-strategy-2026-10-25.md`, and CLO-156's board/CEO discussion.
No matching composite test appears in the strategy log. The components are related to prior tests,
so this is a new composite hypothesis, not a claim of an independent discovery.

| Prior observation | What it supports | What must change or be falsified |
|---|---|---|
| CTA v1.1 fixed survivors: in-sample CAGR 35.8%, DD 26.3%, Sharpe 1.37; PIT top-10: about 25%, 30%, 1.06 | Slow trend is the closest family, worth retaining as control | Today's winners inflate history; use the causal PIT universe. CTA still fails multiple-testing qualification; its old PASS is not eligibility |
| CLO-44 luck suite: defensive DSR 0.893 at N=242, required 0.96; later summaries use different counts/values | Trial correction matters | Recompute at the actual registry count; do not mix vintages or adopt a historical DSR as current |
| CLO-128: +232 USDT realized in 54 bots with the field; +65.5 grid-pair profit, fee sign ambiguous, wallet flows unreconciled | Study inventory and entry/exit context | It is not reconciled net return or a spot strategy backtest. Most bots were leveraged futures, one pair, six weeks, overlapping. Do not copy leverage or infer annual returns |
| CLO-128 31-bot subset: +116 realized, +48.5 grid; aligned bots +92 vs against +24 | Direction mattered alongside cycles | Regime attribution is descriptive, not proof of an observable entry signal |
| CLO-21: 252 range-grid windows, mean -0.74%/14d; +1,977 grid profit, -3,835 float, 60 stops | Completed cycles can coexist with losses | Replace the failed BB/ATR range screen with a separately registered path-efficiency hypothesis; shorter maximum inventory life is a new trial, not a repair to the old verdict |
| BTC gate, vol/volume overlays and adapt-or-die tests failed their frozen gates | A filter often just cuts exposure | Beat an exposure-matched control and a grid-disabled ablation; account for missed trends and switching costs |

The owner profit figures are recorded evidence, not fresh account queries. The headline +232 is
explicitly qualified above. The proposed source of return is not the owner's unrealized gains,
top-ups, manual timing or high leverage. No expected CAGR is inferred from his bots.

## Fixed composite v0.1

One shared cash/inventory ledger, starting research NAV 1,000 USDT. Daily decisions at 00:00 UTC
use only fully closed bars ending before that instant; fills occur at that open or later. Daily
lookbacks refer to consecutive UTC bars, not the last N available observations. Missing/stale
inputs prohibit new exposure. Existing inventory stays marked and is exited at the next observable
tradable price, with the delay recorded. Never manufacture a fill at a missing open.

Define BTC path efficiency on yesterday's close d:

`ER20 = abs(C[d] - C[d-20]) / sum(abs(C[j]-C[j-1]), j=d-19..d)`.

Zero denominator means ER20=0. Require all 21 closes. Set the state afresh each day, with priority:

1. STRESS: BTC trailing 30-day close return <= -25%, or any required BTC daily input missing.
2. TREND: not STRESS and ER20 >= 0.35.
3. RANGE: not STRESS and ER20 <= 0.20, and BTC r20, r60, r120 are not all negative.
4. UNCERTAIN: all other cases. It holds cash after closing sleeve positions at the next available open.

There is no hindsight regime label, discretionary override, confirmation count or refitting.
This coarse classifier may wrongly reject useful noisy trends or accept a slow downtrend; that is
a failure mode to measure, not permission to add indicators after seeing results.

**Trend core.** Use CTA v1.1's exact 2-of-3 positive return vote (20/60/120 days), vol30 sizing,
drifted weights and 2 percentage point rebalance band. Universe is the existing PIT monthly
top-10 by trailing 90-day median quote volume, exclusions and 120-day eligibility from `swing/pit.py`,
including eventual delistings. The trend sleeve has 80% of NAV reserved: calculate CTA targets on
that sleeve using target 0.40, then multiply by 0.80 of total NAV. In TREND its scale is one; in
every other state it is zero. Unused allocations remain cash, without scaling winners up.

**Range grid.** Only BTC spot, only in RANGE; reserve 20% of NAV, never borrow the trend reserve.
On entry freeze bottom/top at the minimum low / maximum high of the last 20 closed daily BTC bars.
Require the next-open price strictly inside the band. Start a two-cell geometric grid (three levels),
using existing `grid.py` equal-base-quantity cash/inventory construction. Require smallest step
>= 3 times the assumed full round-trip cost. Require each cell's order to meet the larger of
10 USDT and the applicable symbol minimum after rounding, with fee cash reserved; otherwise skip,
without adding capital or reducing the number of cells. Check eligibility at the observed open;
no initial order before that observation.

Hold the frozen grid for at most 72 hours. At the first hourly close <= bottom or >= top, or a
daily state other than RANGE, close inventory at the next observed hourly open with full exit
costs. No intrabar stop-fill assumption, take-profit, trailing range, averaging down or capital
top-up. A gap is filled at the actual available next open, never the boundary. After any exit,
wait 72 elapsed hours before another grid can start; only daily decisions can start one. Grid fills
use hourly bars from the first bar after creation, with no credit for pre-creation touches.
Trend and grid ownership never overlap. Close old inventory first, deduct fees, then allocate the
new sleeve from remaining NAV. If a close is unavailable, reserve its capital and forbid opening
the other sleeve until it is closed.

**Sizing and small capital.** Gross inventory plus reserved buy cash cannot exceed NAV; maximum
grid inventory is its 20% reserve. The base is unlevered. Run the identical frozen base at 100 USDT
as a feasibility/ruin diagnostic with minimum buys and precision enforced. A two-cell grid may be
unfundable there after fees: report skips and effective trend-only behavior. Do not call the 1,000
USDT result executable at 100 USDT, or change allocations to make it fit.

## Free data and framework coverage

| Need | Existing source / reuse | Boundary |
|---|---|---|
| Long daily OHLC, hourly BTC OHLC, quote volume and delisted pairs | `var/proxy_market.db`, `var/alpha/*.db`; `swing/pit.py`, `swing/factors.py` timestamp conventions | Binance PROXY. Freeze manifests, UTC coverage, hashes and causal universe before evaluation. Cross-check aggregate daily/hourly bars |
| Recent prices, bid/ask, depth, symbol enable/minimum/precision | Pionex public GET client; `docs/PIONEX.md` and `.claude/skills/pionex-api/SKILL.md` | Free/no authentication; revalidate via skill before collection. Current rules are not historical Pionex membership evidence |
| Historical proxy/Pionex tracking | Overlapping closed BTC/ETH daily bars and recent hourly BTC bars | Proposed preflight: >=30 aligned days each, median absolute close difference <=0.5%, p95 <=1%; otherwise INSUFFICIENT for transfer to Pionex |
| Trend target and overlay | `swing/cta.py` `simulate(scale=..., universe=...)`; `swing/overlays.py` controls and paired bootstrap | Scale can only reduce targets. It cannot implement the shared grid ledger; add a research coordinator, not a second CTA engine |
| Grid mechanics | `swing/grid.py` levels and inventory arithmetic | Existing touch fills and intrabar path are optimistic. Reuse arithmetic, add conservative fills and hourly boundary exits with synthetic tests before any market evaluation |
| Evaluation and uncertainty | `swing/zoo.py` walk-forward conventions, `research/metrics.py`, `swing/overlays.py`, `research/luck.py` and existing trial registry | No zoo strategy search or factor fit. IC is descriptive only if later requested as a new registered analysis |

The minimum return hypothesis needs only price, volume, costs and rules. No Kronos, options, news,
paid API, new account or credentials are needed. Historical Pionex depth/queue data are unavailable
here: hourly historical grid fills remain simulated, and subsequent live-price paper evidence is
essential. Snapshot Pionex public rules/cost observations only after review; no collection is run here.

## One proposed test, frozen before execution

**Question:** does v0.1 improve net return per unit of risk over trend alone, and does the range
grid improve total equity rather than merely its realized-profit counter? Do not run until Red
Team design review is recorded and the board confirms these [proposed] gates. Neither exists yet.

**Windows.** All history through 2026-10-27 is development evidence, including periods called OOS
in older trials. Use the common complete UTC daily/hourly overlap starting no earlier than
2020-01-01 and ending 2026-10-27 for historical diagnostics; freeze its exact first eligible day
from coverage metadata before looking at returns. Use 365 warm-up days, then chronological
nonoverlapping one-year evaluation folds (last partial fold retained); carry holdings across
boundaries, never refit or select a parameter. Report three equal chronological thirds too.
These are walk-forward diagnostics on seen markets, not untouched validation.

The untouched evaluation starts at the first 00:00 UTC after the reviewed code/docstring and data
manifest are committed, and lasts 750 consecutive days (existing luck T1 minimum). Preserve the
same base paper ledger throughout; final statistics are evaluated once, with no early performance
selection. Operational checks may stop on integrity errors, but cannot trigger a retune. Do not
substitute an old historical slice for this future period. If a shorter observation is requested,
it remains INSUFFICIENT for full qualification. This long horizon is a real cost of the evidence
standard, not a promise of a strategy decision within days.

**Execution and costs.** Charge 0.05% fee plus 2 bp slippage plus half the measured spread per side
on every inventory change, including initial grid purchase, each fill, switches and final liquidation.
For PROXY use `cta.COST`, with 10 bp spread for pairs lacking a measured value; freeze the cost
snapshot before the run. For forward paper use timestamped public Pionex spread/depth and symbol
rules; use the greater of the 2 bp floor and estimated impact. Quotes older than 5 seconds or rules
older than one day prohibit new exposure. Missing fees/rules make transfer evidence INSUFFICIENT.
Fee schedule assumptions remain labelled assumptions; no favorable maker rebate is assumed.

Historical grid primary fill rule: price must penetrate the level by one symbol tick, process
open-low-high-close and open-high-low-close paths, and book the worse end-hour equity path
(ties choose low first). Persist that path's inventory. This is a conservative convention, not a
claim to recover the true path or queue. No same-tick buy/sell recycling. Run the two fixed path
alternatives separately as sensitivity scenarios; if the conclusion depends on the path it is
INSUFFICIENT. Forward fills must reuse observed post-submission quotes/depth in the paper engine.

**Controls, same days/costs/ledger limits.** (A) PIT CTA v1.1 at target 0.40, no gate/grid.
(B) uniform scaling of A to the composite's realized average gross exposure on that window,
using the existing overlays exposure-matching procedure. B's full-window scale is an ex-post
diagnostic, never a tradable rule. (C) the exact composite with its grid reserve held in cash.
Also report passive PIT hold, sleeve equity attribution, grid/float/cost decomposition, skipped
orders, time in each state, switch losses and missed trend returns. No control can replace the
base as the selected winner.

**Trial and compute budget.** One base strategy, one evaluation launch, zero adaptive retries or
threshold search. Reuse the existing luck suite's 27 robustness combinations: trend lookbacks
{15/45/90,20/60/120,30/90/180} x target {0.30,0.40,0.50} x band {0.01,0.02,0.05}; the nominated base
is 20/60/120,0.40,0.02. Regime/grid rules and the 80/20 split stay fixed. These are diagnostics,
not candidates from which to select. Together with A/B/C: 30 configurations at 1x/2x/4x costs =
90 configuration-scenarios; two base path scenarios and one base 100-USDT scenario = maximum 93
conservatively counted trial weight. Reserve that entire weight before any results and include
it in correction; no uncounted sensitivity runs. Bootstrap/null draws are inferential resamples,
not selectable strategies. Seed 20261028 everywhere. Local stdlib only, no model calls or paid
compute; maximum 4 CPU hours for the historical batch. Save partial audit and stop INSUFFICIENT
if exhausted; no cheaper substitute test with relaxed gates. The future base observation is
part of this registered experiment, not permission for another search. Any extra configuration
or rerun requires a new registration and trial count.

**Proposed gates (all conjunctive).** Freeze the actual trial-count thresholds and code adapter
after review, before execution. Existing qualification gates remain additional requirements.

1. Data validity: continuous accountable timestamps/marks, causal universe, no negative cash,
   no leverage, reconciled grid + float - separately booked costs = NAV change without double
   subtracting costs. At least 750 evaluated days, 25 nonoverlapping grid episodes and three
   distinct RANGE clusters separated by >=7 non-RANGE days; otherwise INSUFFICIENT.
2. On historical diagnostics AND the untouched period: base Sharpe >=1.0, DD <=35%, Sharpe above
   both A and B, and above A in at least two of three chronological thirds. Paired daily net-return
   differences vs A and vs B each need a positive one-sided block-bootstrap lower bound. Use
   20,000 paired 10-day blocks via overlays, alpha=0.05/(2*93); same fixed block construction and
   correction both windows. This is deliberately stronger than noninferiority.
3. Grid earns its allocation: total net grid P&L including remaining inventory and every exit is
   positive; paired base-minus-C daily-return lower bound >0 at alpha=0.05/93 using the same
   bootstrap. Net range-sleeve mean is positive in each chronological third. Positive grid-profit
   counters alone cannot pass. No single coin contributes >35% of positive net contribution;
   report signed attribution as well.
4. At 2x and 4x *all* execution costs: base CAGR >0, DD <=35%, Sharpe >=0.70 and >=0.50 respectively;
   base Sharpe still exceeds A and B and grid total net P&L remains positive. Missing-bar and
   delisting stress uses the existing 50% last-mark haircut, with Sharpe >=0.85. Disclose if that
   stress never binds. Path-sensitive conclusions are INSUFFICIENT as above.
5. Every existing CLO-44 luck check must pass using the enlarged registry count: T1 history, T2 DSR,
   T3 CSCV/PBO, T4 timing and random-entry/permutation nulls, T5 neighbors, T6 20-day-block lower
   bound, T7 causal bull/bear/sideways/crash floors, T8 stress and T9 100-USDT ruin. Apply the
   existing count-dependent thresholds, never the historical N=242 threshold by assumption.
   Adapt the research suite to accept composite ledgers and preserve all checks; register the
   exact null construction below in the function docstring before launch. A timestamp-shifted
   weight vector is insufficient to simulate grid path dependence.
   Red Team must approve the construction; until then the plan is not executable. Unsupported
   checks are INSUFFICIENT, never implicitly passed. Regime thresholds and the 80/20 split have
   no sensitivity evidence yet; passing trend-neighbor tests alone cannot validate those choices.

**Proposed composite null (10,000 draws, seed above).** For each draw circularly shift the daily
state schedule by one uniformly sampled integer offset from 30 through T-30 days, then replay
the full coordinator on the unchanged market bars, recalculating causal bands, volatility and
fills at the new entry times. Preserve the original per-coin trend signal schedules under the
same shift, but recompute sizing from prices available at execution. Also run a random-entry
null by uniformly permuting nonoverlapping seven-day blocks of the joint state/signal schedule,
retaining each block's internal order. Use original chronology for market prices, cash and
cooldowns; no positions or marks wrap across the sample endpoints. Warm-up and missing-input
rules still apply. This preserves coarse clustering, not exact exposure or hold lengths; disclose
their null distributions and use net mean daily return divided by mean gross inventory exposure
as the statistic (zero-exposure draw scores zero). Each one-sided p-value is
`(1 + count(null_stat >= base_stat)) / 10001`; both must meet the current registry permutation
threshold. Replay every fill and cost, never shift already realized grid profits. Draws are not
variants eligible for selection. Red Team may reject this null as inadequately matched; that
requires a revised registration before any run, rather than an inferred pass.

Report observed 30-day return/ruin distribution and compare the owner's stated $100/30-day
ambition at $100 capital, without redefining these qualification gates or promising that return.
Even a research PASS must separately establish actual $100 sizing feasibility and complete
Red Team / Risk Officer / existing forward requirements. It cannot enable trading.

## Review handoff and stopping rule

Red Team should resolve classifier lag, adverse-selection fills, grid cash reservations, the
100-USDT minimum-size problem, the composite null construction and regime/split sensitivity
coverage before approving execution. Board confirmation must explicitly cover the additional
numerical gates and 93-weight budget. No approval is inferred from silence or this issue closing.

After those dependencies, implement only a research coordinator and optional hooks, with synthetic
tests for causal timestamps, regime boundaries, cash conservation, switching, minimum sizes,
gaps, missing data, adverse path selection and baseline regression. Run both firm test suites and
commit reviewed registration before the one market batch. Do not run strategy/luck commands as
part of document validation. No simulator code is added in this design task.

On execution, save `var/reports/own_strategy_v01.json` with manifest/code hashes, registration,
registry count, all scenarios, uncertainty and PASS/FAIL/INSUFFICIENT; append exactly one test row
to `docs/STRATEGY_LOG.md` and post its result table. On PASS ask the CEO for independent Red Team
review. On FAIL retain the outcome and explain whether selection, costs, inventory or exposure
matching killed it. A changed classifier, allocation, exit or grid is a new idea and trial.

**Current result:** design delivered, 0 trials run, no performance verdict, no strategy-log test row.
No report of simulated performance is fabricated for a proposal. Review and board confirmation
are pending. All quoted performance above is prior evidence, not proof of future profit.
