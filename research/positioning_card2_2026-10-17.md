# Card 2 step 1: top-trader vs crowd positioning divergence (CLO-29), 2026-10-17

Verdict: **FAIL** (pre-registered in `pionex_lab/swing/positioning.py`, run once). PROXY data; not evidence of profit.

| coin | n days | n_eff | partial IC | t | Spearman | half 1 IC | half 2 IC |
|---|---|---|---|---|---|---|---|
| BTC | 593 | 85 | +0.085 | 0.77 | +0.050 | +0.174 | +0.023 |
| ETH | 593 | 85 | +0.117 | 1.07 | +0.062 | +0.184 | −0.003 |

Gate: IC>0 and t>=2 on both coins, same sign in both halves. Not met. Step 2 not run.
Caveat: raw history is 3.5y (so not INSUFFICIENT), but one under-filled day (2024-02-16) voids the strict 365-day z window
until 2025-02-20, so the tested sample is 1.6y. The positive sign is consistent with the hypothesis but untested at power;
a re-test with a gap-tolerant z or longer archive history (Binance metrics from 2021) would be a new pre-registered idea.
Costs: n/a for step 1 (no trades). Raw report: `var/reports/positioning_card2.json`.
