# CLO-237: owner benchmark and risk lessons

Owner direction, 2026-11-07 21:22 UTC: do not copy the method. Finish the cheap
benchmark, extract risk lessons, then stop this line of work and hand off to
the existing own-edge programme. This supersedes the proposed CLO-237-v2 /
CLO-244 continuation as the NEXT action for CLO-237. No additional performance
test was run, no new trial reserved, and the original FAIL remains unchanged.

| Human benchmark, saved 2026-11-07 audit | Evidence |
|---|---:|
| Reported 30-day bot net P&L | +283.72 USDT |
| Fees, already deducted in net | 56.57 USDT |
| Bots in window | 58: 41 positive, 4 negative, 13 flat |
| Closed BTC records with comparable prices | 44 |
| Grid profit in those records | 70.34 USDT |
| Long / short net | +154.60 / +129.12 USDT |
| Median bot lifetime | 9.26 hours |
| Worst recorded losing bot | -3.86 USDT |
| Fixed-$100 percentage return | Not established: variable stakes, overlap and top-ups |
| Trading maximum drawdown | Not established from these endpoint bot records |

Source: required `py -m pionex_lab.runtime.owner_pnl 30` refreshed on this run,
confirming the saved `research/owner_method/clo237_owner_audit.md`, and its normalized
records, `var/reports/clo237_owner_audit_inputs.json`. Only the capped API's
listed bots and previously archived records are covered; older/removed bots
are missing. This is a descriptive historical benchmark, not proof of an edge.
The four recorded losing bots total -7.16 USDT. Closeout summary:
`var/reports/clo237_benchmark_closeout_2026-11-07.json`.
Net follows the existing reporter: realized profit minus absolute fees plus
signed funding. It is not the change in wallet equity. Withdrawals and Card
transfers are external flows, not trading losses or profit.

The older owner-record note's 72.2% drawdown is an **unadjusted wallet-balance
drawdown**, not a verified trading drawdown: transfers and withdrawals change
that curve. Do not use it as the human's trading-risk denominator or claim the
firm halves it. The failed model's 71.35% intrabar drawdown is simulated and
belongs to that model only. Endpoint bot losses miss intrabot adverse marks
and simultaneous exposure. A closed-P&L staircase would miss the same risk;
publishing it as maximum trading drawdown would be misleading. A marked
inventory history and cash-flow reconciliation would be needed for that
number; collecting or reconstructing them is outside this cheap closeout.

Risk lessons for independent research:

- Early exits: short observed lifetimes and four small realized losses support
  recording explicit time, profit and loss exits in future independent tests.
  They do not identify a causal discretionary exit rule or show that earlier
  exits improve returns; no counterfactual exit replay was performed here.
- Size: 24 of 44 comparable bots invested $50; some exceeded $100, and most
  reported 40x leverage. A small margin is not a small loss budget. Record
  aggregate concurrent exposure, gap/liquidation loss and fees before entry;
  do not infer safe capital from the per-bot stake or observed worst loss.
- Direction and cost: the four losing bots had adverse endpoint moves; fees
  exceeded grid profit in several. Positive grid cycles do not guarantee
  positive net P&L. The 70.34 grid-profit subtotal is not additive to 283.72
  net, and its residual is not independently measured alpha.

WHY the completed model failed: adverse inventory, liquidation and costs
overwhelmed grid cycles; this was not a near-miss. WHAT would change the
research conclusion: an independently specified signal producing positive
after-cost evidence under the unchanged gates. NEXT: the existing CEO-led
own-edge programme, with a new hypothesis registered before evaluation.
Do not implement or run the owner-derived v2 from this issue. Its registration
is retained as an unrun historical record, not an active assignment. This
later owner instruction replaces the earlier required owner-derived variant.

Documentation-only closeout. No code, trading authority, settings, gates,
mandate or order path changed. No PASS/Red Team handoff. No new strategy-log
test row or duplicate trial count. The earlier test validation stands.
