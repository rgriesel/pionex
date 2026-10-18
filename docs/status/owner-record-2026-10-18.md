# Owner's own Pionex record (read-only, measured 2026-10-18)

Source: Pionex account reader (var/account.db) and read-only trade/fills; Pionex is the source of truth.
- Spot BTC_USDT manual fills, last 30 days: 2 tiny fills (buy 0.000165 BTC on 09-20, sell 0.000164 BTC on 09-28; ~USD 13). Manual BTC trading is not where the money is made.
- Account equity (all wallets, grid bots included): 151.99 USDT on 09-30 -> 230.99 USDT on 10-18 = +79.00 USDT (+52%) in 18.4 days
  (pace: about +129 USDT per 30 days). Includes unseparated deposits/withdrawals: a +45.6 jump on 10-13 may be a deposit; if so,
  the trading profit is nearer +33 USDT (about +54 per 30 days). Honest range: +54 to +129 USDT per 30 days on ~150 USDT.
- Risk taken to get it: equity ranged 58.80 .. 241.34 USDT, maximum drawdown 72.2% (leveraged futures grids, up to 40x). One bad leg
  from ruin.
- Bots: 65 distinct grid bots seen, sum of reported grid profit 58.76 USDT (futures grids dominate; 2 running BTC.PERP grids now).
- Not visible to the read-only key: manual futures fills (the fills endpoint rejects perp symbols), so manual futures P&L is inside the equity curve only.

## Firm target derived from this (board decision, 2026-10-18)
- RETURN: match the owner: >= USD 100 profit per 30 days on USD 100 capital (the owner's pace is USD 54-129 per 30 days on larger capital).
- RISK: beat the owner: maximum drawdown <= 35% (owner: 72%), enforced by the live gate/executor, with stop-loss on every order.
- The goal is the same return at about half the drawdown, with luck-proofing, because the owner's record is one lucky-looking, high-risk path.
