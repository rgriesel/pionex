# Owner method -> testable rules (v1, 2026-10-25, from CLO-127 comment)
Inputs the owner uses: SRchannel (TradingView S/R), VWAP anchored from swing low, VWAP anchored from swing high,
Elliott wave (confirmation only), Fibonacci retracements, EMA50/EMA200 daily. Analysts: charthackers, dailyentry, more crypto online.
Core rule: CONFLUENCE. A level where >=2 of {SR zone, anchored VWAP, fib 0.5/0.618, EMA50/200} sit within a tolerance is a high-probability level.

Pre-registration (rules fixed BEFORE running; no re-tuning after):
- Level set L: for BTC/ETH daily+4h: anchored VWAP from last confirmed swing high/low (fractal n=5), EMA50/200, fib 0.5/0.618 of last swing,
  SR zones = clusters of >=3 pivot touches (our own implementation of SRchannel; exact SRchannel params to be confirmed by the owner).
- Confluence = >=2 distinct level types within 0.5*ATR(14) of each other.
- R1 (fade short): price touches a resistance confluence from below -> short (or short-side grid) with target = next support confluence, stop = 1 ATR beyond zone.
- R2 (fade long): mirror at support confluence.
- R3 control: same entries at non-confluence random levels (must beat R1/R2, else confluence adds nothing).
- Metrics: after-fee (0.05% side + slippage) expectancy per trade, hit rate, avg win/loss, break-through rate (how often the level fails), n trades >= 100 per rule.
- Pass gate: standard firm gate (after-cost positive, beats R3, out-of-sample half, DSR). Elliott is NOT coded (not objectively definable); recorded as discretionary.
- Note: owner's small-take-profit style (0.02-20 USD) means win-rate and cost per round trip matter most.
