# CLO-60: frozen single-test registration

Registered 2026-10-18 09:10:16 UTC, before loading any BTC OHLC values for this test.
One rule set, no search. Research only; Binance spot is PROXY for Pionex and for CME levels.
Metadata inspected: hourly coverage 2019-01 onward; firm trials weight 246 before this test.

Question: does a >=1% weekend down-gap earn positive net BTC spot trade expectancy and
beat unconditional weekly buying by >=0.3 percentage points per trade? Owner/CEO uses
the answer to retire or review this candidate. No trading or eligibility changes.

## Calendar and frozen execution

Use 2019-01-01 through 2026-05-28 only. CME actually launched 24/7 crypto trading
2026-05-29, so the old regular weekend-closure hypothesis has no current deployment case.
Legacy hours: Friday 16:00 America/Chicago close, Sunday 17:00 Chicago reopen, DST-aware.
Use spot close of the hour ending Friday 16:00 as target. Observe the complete first
Sunday reopen hour (ending 18:00 Chicago); if its close / Friday level - 1 <= -0.01,
buy at the next hourly open (18:00 Chicago). This resolves the card's fixed-UTC sketch
using verified CME hours; it is an hourly spot proxy, not measured CME gaps.
Holiday-specific historical exceptions are unavailable: ordinary calendar proxy only.

Hold >=4h and <=120h. At each hourly close after at least 4h, exit at next open if
close >= Friday level or close <= 95% of entry, otherwise exit at 120h open.
The -5% stop is a closed-bar trigger, not a guaranteed loss cap; there is no exit in
the first 4h. This explicit resolution preserves the issue's strict minimum hold and
closed-bar/next-open evidence standard. No intrabar target-fill assumptions.
One position per week; complete continuous hourly data required from Friday reference
through 120h exit; skip and count incomplete weeks. All prices finite, positive, valid OHLC.

Costs: cta.COST[BTC_USDT] = 0.0007 per side (5bp fee + 2bp slip + measured
rounded-zero BTC spread), charged multiplicatively: exit*(1-c)/(entry*(1+c))-1.
Also 2x and 4x all-in cost stress. Historical spread/slippage uncertain.
100 USDT research notional exceeds 10 USDT minimum; returns per notional, no leverage.
Comparator buys EVERY eligible Sunday at the identical entry and sells at 120h, same costs.
Also report matched selected-week 120h control; it is a diagnostic, not a new test.

## Evaluation (no fitted parameters)

2019-01..2023-03 contextual era; 2023-04..2026-05 final chronological evaluation era.
All windows end before next era starts (120h purge); no fitting or optimization.
The latter era is newly evaluated for this hypothesis but has been used by other lab tests:
do not call it globally untouched. Fresh Pionex forward proof would still be required.
Report full and final-era counts, mean, win rate, profit factor, compounded trade-equity
drawdown (closed trades only, not intratrade), min/max holding, yearly concentration,
and mean without best trade. Three chronological calendar thirds are diagnostics.

Bootstrap complete weekly opportunity rows in circular moving blocks of 8 weeks,
50,000 draws, seed 60018. Each draw computes selected sum / selected count and
unconditional mean; this preserves no-trade weeks and clustering. Report one-sided
95% lower bounds and firm-count-adjusted bounds at alpha=0.05/N, N >=247 (fresh
registry weight including this trial at run time). Report centered bootstrap p and
Bonferroni p. The adjusted extreme quantile has limited Monte Carlo precision.

Historical PASS requires ALL: >=30 full and final-era events; positive full and final
mean with adjusted bootstrap lower bounds >0; full/final advantage vs unconditional
>=0.003 per trade; final PF >=1.2; positive final mean at 2x AND 4x costs; nonnegative
final mean excluding best trade. Otherwise FAIL (sample shortage explicitly INSUFFICIENT).
Current applicability independently FAILS because the original weekend closure ended.
No sensitivity searches or full promotion luck-suite for a rejected/obsolete candidate.

Sources checked 2026-10-18:
- https://www.cmegroup.com/trading/files/bitcoin-futures-bitcoin-infographic-consensus.pdf
- https://investor.cmegroup.com/news-releases/news-release-details/cme-group-announces-launch-247-cryptocurrency-futures-and
- https://www.cmegroup.com/markets/cryptocurrencies/bitcoin/bitcoin/specs

Artifacts: research/cme_gap_clo60.py, var/reports/cme_gap_clo60.json,
var/reports/cme_gap_clo60_trades.csv; append outcome to docs/STRATEGY_LOG.md and trial registry.
Run once with exclusive output creation; no rerun for a different outcome.
