# H6b: extreme lead-lag with conservative maker-entry simulation

Source: CLO-248 H6 requested NEXT. WHY: final gross +18.6 bps against 16 bps round-trip,
net +2 bps, PF 1.04, LB95 -10; full mean -15.2 bps. WHAT: stronger lead signal and
passive entry, without selecting winning coins or changing thresholds after the run.
The parent's final era is seen and its favorable coin/year splits are not selection rules.

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
1. Reuse CLO-248 lead_stats and H6 eligibility/coin universe, changing only abs(z)>=3.0
   instead of 2.0 and the entry execution described here. BTC+ETH same-sign four-hour
   leader; trailing 720-hour normalization (>=360 valid); each of ADA,AVAX,BNB,DOGE,
   LINK,LTC,SOL,XRP must lag by the original <50% rule. No coin selection.
2. After signal i closes, at open i+1 submit a simulated post-only limit at that open.
   No fill on submission bar. Thereafter, for up to four bars i+2..i+5, require price
   to trade strictly through the limit by >=one Pionex tick to count a fill, not touch.
   At most one pending order/position per coin. Unfilled orders expire; never chase.
   This candle model cannot prove queue priority: report that limitation and unfilled
   signals separately; a quote-based forward fill check is required before promotion.
3. Freeze gap and 168-hour alt volatility at original signal. TP = actual fill price *
   exp(direction*0.5*gap); SL = fill*exp(-direction*1.5*sd1h*sqrt(8)), unchanged H6
   distances. Time exit next open after 8 elapsed hours from fill, not signal.
   Full notional, 1x, same worst-case ambiguous stop precedence and stop gaps as H5b.
4. Fee proposal is 2 bps ONLY on a verified passive-entry leg, not on forced exits.
   Stop/time/TP exits conservatively pay 6 bps fee allowance +2 bps slippage and
   measured half-spread (fallback 5 bps/side if absent, frozen before run).
   Passive entry also reserves 2 bps adverse-selection/slippage allowance; do not book
   spread capture. Funding 1 bp/8h on held notional. Stress all execution friction
   2x/3x/4x, funding unchanged. No optimistic 2-bps market stop.
5. Maker assumption is conditional: confirm official current Pionex PERP fees and
   per-symbol ticks/minimums with public sources before evaluation. If unsupported,
   leave NOT RUN and register a different specification; do not silently change fees.

Dependencies: public fee/tick and passive-fill evidence; tested delayed-fill implementation;
board confirmation of inherited gates. First executable step: public fee/rule evidence capture,
then synthetic gap/stop/strict-through/expiry tests. No signed endpoints or secrets.
