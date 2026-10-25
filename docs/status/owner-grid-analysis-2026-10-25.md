# Owner's finished grid bots: who made money, how much is market direction (CLO-128, 2026-10-25)

Read-only. Source: `var/account.db` table `bots` (latest snapshot per bot; the API key is never read), hourly BTC klines
(`var/market.db`, `var/proxy_market.db`, up to ~2026-10-20). No orders, no network, no secrets. Code: `pionex_lab/research/owner_grid_attrib.py`;
per-bot table: `var/reports/owner_grid_attrib_2026-10-25.json`. Descriptive only, not a pass/fail test, not proof of an edge.

## Sample
56 finished bots (54 futures, 2 spot), all BTC, started 2026-09-11 .. 2026-10-25: one 6-week window, one market. Grids 10-200 (60 typical),
range 13% of price for almost all, leverage 15-100x (44 of 54 futures at 20x or more; 40x most common). Median life 7 hours (0.3 day), longest 6.8 days.
Direction: 28 long, 26 short futures grids. 31 bots finished while hourly data exists, so market-split numbers use those 31.

## Data warning: the earlier "+450" is inflated
CLO-46 measured profit as final margin minus *initial* investment. The owner topped up 5 bots mid-life (e.g. 11.5 started, 142.3 actually held),
so those "returns" (+140 on 11.5) are not real. Better measure: `totalRealizedProfit`.
| measure | USDT | note |
|---|---|---|
| final minus initial investment | +450 | overstated by top-ups; do not quote |
| final margin minus actual invested | +311 | still includes unrealised mark |
| **realized profit (54 bots with the field)** | **+232** | 46 of 54 positive; biggest single bot +17 |
| grid profit (completed buy/sell pairs) | +65.5 | 28% of realized |
| fees (sign ambiguous in the data) | 53.7 | not netted here |
One bot shows -123 (invested 123, quote investment 0, realized 0): looks like an unfunded or transferred record, not a trading loss; excluded from the story.
Cross-check against the wallet (CLO-127): wallet +145 over the period vs realized +232. They cannot be reconciled without the deposit/withdrawal log.

## Who made and lost money
- Winners: 46 of 54 bots realized a profit, but typically 1-2 USDT; median realized +1.7. The top 5 bots make 72 USDT (31% of the total).
- Losers: few and small (worst real one -9 realized, -11 total). Liquidation flags were not checked per bot.
- Long 28 bots / short 26 bots both profitable; spot (2 bots) ~0.
- Leverage 20x+ bots made most of the money because they hold more notional per stake, not because the pairing is better; leverage has no clear link to return per CLO-46 (rho 0.11).

## How much is market direction (31 bots with market data, futures grids)
BTC moved little over any single bot's life (a few percent at most), so the split is read by whether the move went the bot's way.
| bots | n | realized | of which grid pairs | won |
|---|---|---|---|---|
| market moved WITH the bot's direction | 20 | +92 | +24 | 19 of 20 |
| market moved AGAINST it | 11 | +24 | +24.5 | 7 of 11 |
| all | 31 | +116 | +48.5 | |
Reading: grid-pair profit is the same (~24) in both groups; the entire gap (+68) comes from direction. When the market went the wrong way the bots
still roughly kept the grid profit (small stops/short life), when right they added ~+68 of position profit. So about 40% of realized profit in this
subset (48.5 of 116) is the grid itself, ~60% is position/direction, and grid profit is paid by volatility not by direction.
A plain "leveraged position in the bot's direction" model gives +74 for the same 31 bots (+200 aligned, -126 against); bots earned more than that model
on the against group because grids do not hold a full position and bots were closed fast (median 7 hours), so this model is a poor fit and is not used for the headline.

## Why this does not transfer to the firm
- One 6-week window, one pair, bots overlap in time: effectively one sample of the market. 
- The short life (7 h) means the owner is choosing entry and exit manually: the edge, if any, is his timing (a discretionary directional call), not the grid parameters. CLO-46 found no parameter (range, grids, leverage) that separates winners.
- The firm's tests of fixed rules on 3.5 years of BTC (R1, R2, perp long grid CLO-63) lose on average: -2 to -5% per 14-day window with stops.
- Risk shown by the same account: equity range 58.8 to ~300 and up to 100x leverage; the results are survivable only because losers were closed quickly.

## Open questions for the owner (exact answer needs them)
1. Deposit/withdrawal dates and amounts (to reconcile the +145 wallet change with +232 realized).
2. Were the 5 top-up bots topped up on purpose (adding margin to winners)?
3. Why does the 123 USDT 15x short record show zero invested? (transfer, or a failed start?)
