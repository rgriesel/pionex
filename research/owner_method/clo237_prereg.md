# CLO-237 frozen test

PRE-REGISTERED 2026-11-07 11:46 SAST, before any historical evaluation.

CLO-237: one frozen owner-inspired long-only research test, never an exact
discretionary replay. Existing CLO-46/CLO-63 are different rules. Owner
calibration: saved 58-bot audit; ~+/-6.67% arithmetic band, 60 rows, 40x,
median hold ~9h, frequent early cash-out. No parameter selection permitted.
Every 8h UTC: prior CLOSED hourly close > EMA50 and > close 168h earlier;
enter next open, one isolated bot, margin min($50, half available equity),
total starting capital $100, zero topups, cash reserve cannot fund bot losses.
Grid levels +/-1/15, 60 rows; quantities rounded down to public contract step;
each row >=max($10, public min notional), minimum size enforced. No entry
below $2 capital. Initial upper rows held; financed linear inventory ledger.
Closed-bar exits execute next open: net flatten profit >=max($1,2% margin)
(capped $50), net loss >=25% margin, profitable six-bar stall, or 8h hold.
Range break closes next open. Gaps marked before exits. Liquidation checked
on inventory at every path node using adverse mark basis -10bp, assumed
maintenance 0.5% plus public liquidation fee; full isolated margin lost.
Both OHLC paths simulated, worse equity trough retained; no queue guarantee.
Fees 5bp/side, limit slip 2bp, market slip 5bp, half current observed spread
on every fill; funding debit 3bp notional/day. All costs stressed 2x/4x.
These are conservative assumptions, not verified historical mark/funding.
Neighbours fixed: leverage30, take-profit4%, hold12h, counted as 4 trials.
Controls: same-entry initial-inventory hold; unfiltered grid; 99 circular
signal shifts, descriptive random-entry replay only, no qualification claim.
Data: public Pionex PERP 60M, end 2026-11-07 08:00 UTC, max 10,000 bars;
no proxy substitution. Last third chronological holdout, first 168h warmup;
evaluation is retrospective and not globally untouched. No re-fitting.
PASS requires existing luck-1 T1..T9 thresholds with registry including
4 configurations, >=100 trades, mean rolling30 return >=100%, intrabar
DD <=35%, zero liquidation, bootstrap trade LB(alpha=.05/4)>0,
final-third net profit>0, and outperform same-entry initial hold.
T1 >=750 days; DSR, CSCV16, circular timing null10000, neighbours,
bootstrap20day/2000, all four regimes >=30days, cost stress and MC10000
exactly use research/luck.py. Hourly causal entry-notional timing diagnostic
is reported separately; it cannot certify the nonlinear grid timing gate.
Missing historical marks, exact bot mechanics, untouched OOS or forward
Pionex fills means no live qualification regardless of numeric results.
FAIL/INSUFFICIENT requires WHY/WHAT/NEXT; next variant is a NEW test.
