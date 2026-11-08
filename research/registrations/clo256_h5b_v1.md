# H5b: fade a confirmed failed compression breakout

Source: CLO-248 H5 requested NEXT; docs/STRATEGY_LOG.md, H5 row. WHY: final gross -37.7 bps,
net -55.3, PF 0.65; compression breakouts reversed. WHAT: require failure before fading,
rather than entering another breakout. The earlier flipped-side diagnostic is already observed
and cannot be counted as a new untouched test or reused as this trial's result.

Frozen: 2026-11-08T03:45:19+02:00 (SAST, UTC+02:00), BEFORE any successor evaluation.
Owner: Quant B; assignment CLO-256 under CLO-253. Research/paper only.
Status: PRE-REGISTERED NOT RUN; gates pending board confirmation, not executable approval.
Budget: ONE specification, ONE evaluation, no optimization or extra variants. Stress runs are
predefined diagnostics within this trial. Write the implementation function docstring with this
specification and its SAST timestamp before running; implement tests and run both firm suites.

Inherited CLO-248 screen gates, unchanged: >=100 trades in full and final eras; mean net >0
in each; final profit factor >=1.2; final mean net >0 at 2x costs; final mean excluding the best
trade >0; final one-sided 95% three-day block-bootstrap lower bound >0. Below 100 trades in
either era is INSUFFICIENT; otherwise any failed gate is FAIL. Report 0.05/ntrials Bonferroni
bound, ntrials=max(295,SUM(weight) at run time), and 3x and 4x cost stress; these additional
reports do not weaken or replace any gate. Reuse research.metrics.block_bootstrap_lower and
summarize. Seeds and bootstrap implementation stay as in research/own_edge_b_clo248.py.
PASS is only a historical research screen and remains open for CEO-assigned independent Red
Team review (maxReviewRounds 2); never live eligibility or proof of profit.

Data: same frozen historical hourly Binance spot PROXY archive as CLO-248, cut off
2026-10-12 23:00 UTC. Full begins with each coin's available history from 2019-01;
final entries >=2023-04-01 00:00 UTC. All historical eras were exposed by parent trials;
call this adaptive successor screening, NEVER untouched OOS. Future Pionex evidence must be
separately registered before promotion. Keep missing hours missing, skip incomplete windows,
no signal until all lookbacks exist, no overlapping positions per coin, no synthetic fills at
missing bars. Freeze input row fingerprints and a report create-only sentinel before evaluation.
Costs/fills and gap handling must be unit-tested before the single authorized run. No order path.
Every FAIL/INSUFFICIENT must identify WHY, WHAT would change it, and NEXT a separately
registered successor with its queued issue; do not rerun this specification.

Rules and fixed parameters:
1. BTC_USDT and ETH_USDT. Reuse CLO-248 h5_signals unchanged (72-hour prior range;
   3-day/14-day range ratio <=0.70; ATR sampled over 14 daily intervals).
2. At original closed-bar signal i freeze prior 72-hour high U, low L and ATR A.
   Consider only the first subsequent closed bar j in i+1..i+4 whose close returns
   inside [L,U]. If none, expire. A long breakout is faded short; short breakout long.
   Signals while a pending candidate/position exists are ignored. No entry on bar j.
3. Enter a SINGLE full-notional position at open j+1. This is not the parent's
   mirrored three-rung diagnostic. Stop beyond the failed excursion: for a short,
   max(high[i..j])+0.25*A; for a long, min(low[i..j])-0.25*A.
   TP is midpoint (L+U)/2. Skip if next-open geometry is not stop-entry-TP in order.
4. Time exit next open after 96 elapsed hours from entry; stop/TP active immediately.
   Stop precedes TP on an ambiguous bar. Stop gap fills at worse of stop or opening
   price; TP never receives favorable improvement; time exits pay market friction.
5. 1x notional, no leverage, no liquidation claim. 8 bps/side at base (6 fee allowance
   +2 slippage), plus measured half-spread; absent measured spread use 5 bps/side,
   fixed before evaluation. Funding charge 1 bp per 8h on filled notional both sides.
   Multiply all execution friction by 2,3,4; funding unchanged. Report gross, net,
   inventory exposure, stop/TP/time reasons and paired same-signal continuation diagnostic.

Dependencies: board confirmation of inherited screen gates; tested implementation with
conservative gaps/spread and causal failure confirmation. First executable step: implement
this frozen failed-breakout state machine with synthetic-bar tests; do not evaluate returns.
