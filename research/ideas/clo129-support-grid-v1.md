# CLO-129: support-anchored grid family v1

Source: CEO comment `86f9f554-2b63-49cf-a738-30b5b2c934b0` on CLO-129,
2026-10-25 16:41:55 UTC, relaying board context that the owner uses support,
resistance and indicators and places liquidation below expected support.
This is a research hypothesis within the existing simulated tournament scope.
It does not confirm performance gates or authorize live trading.

Rules frozen **2026-10-25 18:54 SAST**, before synthetic validation, in
`pionex_lab/research/support_grid.py` function docstrings. No market-performance
evaluation has occurred. The original 18 percentage-band configurations remain
unchanged. This is a separate family with new identifiers, not a retune.

## Fixed rule

- Pairs: BTC/ETH. Support is the minimum low of exactly the preceding 168
  contiguous, closed one-hour bars. Earliest bar wins tied lows. No future or
  unfinished bar enters the anchor. It is a mechanical prior-support proxy;
  the owner's unspecified indicators are not invented or copied.
- Bottom = support; top = support x 1.16; 40 geometric cells; reference close
  must be 2%..8% above support. Outside this interval or missing history means
  skip, recorded as an attempted configuration before any eventual entry.
- Per pair: unleveraged spot and long perpetual plans at 2x and 3x. Six planned
  configurations, each with 1,000 simulated USDT capital/margin. A new family
  increases the planned total from 18 to 24; none has started. Register all
  attempted variants before first observations, with immutable source inputs.
- Planned whole-grid stop = support x 0.97. Perpetual liquidation must be
  verified **below the stop**, hence below support, by the CLO-37 model using
  current Pionex inputs. Recheck as inventory, fees and funding change. Unknown
  margin tiers or liquidation values mean no simulated launch. Choosing a stop
  or expecting support to hold does not guarantee a loss ceiling.
- Fixed seven-day cohort. Preserve the anchor after a break; no retrospective
  range widening, added margin, adaptive leverage or automatic respawn.

## Break accounting and evaluation

`support_breaks` audits a complete hourly interval against the frozen level.
It counts strict low-below-support hours (wick breaks) and close-below-support
hours separately, plus consecutive-run episodes and the first affected bar.
Equality is a touch. First-break timestamps identify bar opens; the event is
known only after the bar closes. Consecutive runs are hourly observations,
not claims about the number or ordering of intrabar crossings. Missing data
produces unknown counts rather than zero. Counts alone do not simulate a fill,
liquidation or a successful stop.

The future report must retain skipped and stopped grids, support-break counts,
time to first break, net economic return including residual inventory, fees,
spread, slippage, funding, observed drawdown and liquidation incidence. Use
the existing ranking framework and static controls on the same opportunity
window. Source all action inputs from fresh Pionex quotes/rules, not this plan
or an audit log. The paper supervisor must support absolute frozen ranges;
`shadow_grid.Config` currently supports symmetric percentage bands only.
Do not approximate the absolute support range with a symmetric band.

Prior evidence is adverse: CLO-68's swing-S/R verifier found swing levels
breaking rather than holding; CLO-21, CLO-46 and CLO-63 grid tests also failed.
The 168-hour minimum rule is distinct and has not been tested. No old failed
test is rerun or relabelled. No return, Sharpe, support reliability or liquidation
safety claim follows from this preparation.

**Verdict: INSUFFICIENT.** No experiment or performance trials executed.
CLO-128 owner-copy evidence and CLO-37 futures-grid ledger remain dependencies.
Before a performance run, confirm untouched forward periods, baseline and
board-approved gates; register the complete procedure and trial budget; reuse
`research/metrics.py` bootstrap and the firm's unchanged multiple-testing,
walk-forward, cost stress, Red Team and Risk Officer qualification framework.
The new code generates plans and audit counts only, never orders or promotions.

## Validation of preparation code

- Support planner/break counter: 8 synthetic tests passed.
- Repository suite: 496 tests, one skip, only the known Windows
  `test_read_only_uri_encodes_awkward_paths` error (272.653 seconds).
- Skill-script suite: all 12 passed. Staged diff whitespace check passed.
- No historical or forward market-performance test; no measured support-break
  frequency, trading return or liquidation result is available.
