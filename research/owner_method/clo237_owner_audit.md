# CLO-237 owner-bot audit, 7 November 2026

Required command `py -m pionex_lab.runtime.owner_pnl 30`: net **283.72 USDT**,
fees **56.57**, 58 bots in window, 87 ever seen, 41 positive, 4 negative,
13 flat. Withdrawals/card transfers are not losses or deposits. The implied
external flow is -182.73 USDT; wallet change is not used as trading profit.
Only bots still returned by the capped API, plus previously archived records,
are available. Missing older/removed bots prevent a complete survivorship audit.
Do not extrapolate the 41/45 nonflat win rate to all historical bots.

The interrupted run's `var/reports/clo237_owner_audit_inputs.json` contains the
58 normalized detail records used below. This is descriptive calibration,
not an independent strategy test. The tiny coin-denominated record is excluded
from BTC comparisons rather than adding native coin quantities to USDT.
The existing required P&L command is used unchanged for the target benchmark.

For 44 closed records with BTC-sized initial prices, total net is 283.72155;
reported grid profit sums to 70.34407 USDT, about 24.8% of net. The residual
includes directional realization and fee/funding effects; it is not pure alpha.
Longs contribute 154.60 and shorts 129.12. The full 58-record audit is evenly
split 29 long / 29 short, including flat/cancelled records. Therefore a long-only
test cannot reproduce the owner's complete behavior.

Most BTC bots use a roughly +/-6.67% band and 60 rows (41/44); exceptions have
10, 44 and 200 rows. Median hold is 9.26 hours, far shorter than a 14-day grid
replay. 32/44 report leverage 40; several report 41–50, others 15/30/32.
Reported leverage differs from the `setLeverage` field, so the model fixes 40
as requested and makes no claim that actual inventory always equaled 40x margin.
24/44 invested exactly $50, while some exceed $100. The observed absolute
profit is not a demonstrated 100% return on $100, and no cash top-up identity
or complete marked equity path establishes a <=35% owner drawdown.

| Losing bot prefix | Side | Initial to closing price | Grid profit | Fees | Net USDT | Diagnosis |
|---|---|---|---:|---:|---:|---|
| 06dc5f87 | short | 80428 to 80679.3 | 0.0331 | 0.5010 | -1.9739 | Adverse direction; grid harvest too small |
| 34690b35 | short | 82008.4 to 82123.6 | 0.9078 | 1.0516 | -1.0355 | Adverse direction and fees exceed grid profit |
| 3f4078f6 | long | 82990 to 82366.5 | 3.5779 | 1.6377 | -3.8552 | Adverse direction despite positive grid ledger |
| 8753ec49 | long | 83218.2 to 83203.9 | 0 | 0.2496 | -0.2925 | Tiny adverse move plus fees, no grid cycles |

These are initial/closing trade prices, not complete execution VWAP or mark
paths. The long loss with a later average position entry below its closing
price illustrates why a snapshot's average entry cannot reconstruct all
previous realized fills. Actual realized fields, signed funding and fees
remain the P&L source; naive endpoint direction is only a diagnostic.

The owner exits before broad range boundaries and uses both directions.
The records show that behavior, but do not reveal an objectively causal
decision rule or prove that entry timing beat a matched control. Existing
owner_method confluence and market-read work is retained; missing historical
targets cannot be reconstructed from a later target snapshot. CLO-237 tests
one explicit trend/short-hold approximation with the same-entry inventory hold
and unfiltered-grid controls. It does not invent analyst signals or silently
reuse the already failed CLO-46/CLO-63 rules.

Public Pionex BTC_USDT_PERP symbol rules and 10,000 hourly candles were fetched
unsigned into `var/reports/clo237_pionex_inputs.json`. The public symbol rules
give a 0.0001 BTC size step, 0.1 USDT tick, minimum notional 1 USDT and
liquidation fee rate 0.0115. The model additionally preserves the firm's $10
minimum fill assumption. Maintenance 0.5%, adverse mark basis 10bp and funding
3bp/day are research assumptions; no historical mark/funding series was
substituted with trade candles. Contract minimum size does not certify the
exchange bot product's minimum investment or exact queue behavior.
