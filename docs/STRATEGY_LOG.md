# Strategy log — every idea the lab has tested

One row per test. Net results are after Pionex-level costs (≈0.05% fee + slippage per side) unless
noted; all data is labelled proxy (Binance public archives) unless noted. Backtests are not proof of
future profit. Newest first. The quant-backtester appends here; the research-scout reads it to avoid
repeats.

## Live candidates (paper)

| Date | Strategy | Hold | Result | Status |
|---|---|---|---|---|
| 2026-10-13 | **CTA trend basket v1.1, defensive** (`swing/cta.py`): 10 coins, IN when 2 of 20/60/120-day returns > 0, size (40%/N)/30d vol, cap 100%, 2% band on drifted weights, daily at 00:00 UTC, measured Pionex spreads in costs | per coin while trending (median 3 d, mean 16 d, top 10% ≥ 48 d) | **In-sample** (rules written with the first results, informed by the BTC/ETH EMA50 tests). 2017-12→2026-10: 35.8%/yr, max DD 26%, Sharpe 1.37 (thirds 1.38/1.29/1.44) vs hold-all 45.6%/yr, DD 82%, Sharpe 0.88; since 2021 Sharpe 1.37 vs 0.98. 4× costs: 30.9%/yr, DD 31%, Sharpe 1.22. Turnover 15.6×/yr | **PASS**; red team (Opus): HOLDS WITH FIXES → fixes applied in v1.1 (v1 was 37.9%/yr, Sharpe 1.42). Paper book `var/swing_book/state.json`, 1000 USDT, from 2026-10-14 |
| 2026-10-13 | CTA basket at small capital (10 USDT minimum buy, allocation capped) | same | 10 coins @ 100 USDT: 16.6%/yr, DD 19%, Sharpe 1.30 but avg 11% invested (most positions < 10 USDT); @ 500+ USDT: unaffected. BTC+ETH only @ 100 USDT: 32.7%/yr, DD 33%, Sharpe 1.15, 35% invested | capital check → canary paper book `state_canary.json` (BTC+ETH, 100 USDT) |
| 2026-10-13 | CTA trend basket, growth (same signals, 1/N sizing) | same | v1.1: 68.4%/yr, DD 55%, Sharpe 1.26 (not the tested variant) | paper book `state_growth.json`, 1000 USDT (comparison) |

## Tested and not good enough

| Date | Strategy | Timeframe / hold | Result | Verdict |
|---|---|---|---|---|
| 2026-10-13 | Out-of-sample re-test (pre-registered 23:31 SAST, run once) of the two best 4h trend strategies, Keltner breakout and Supertrend: same grids, 5-part walk-forward per coin, max hold 60 bars, Pionex costs, 10 coins, never-used data 2019-01→2023-03 (Binance spot, `var/alpha/early_1h.db`) | 4h / up to 10 d | Keltner n=1091, +73 bps/trade, PF 1.26, win 40%, 5/10 coins positive (needed 7), bootstrap LB −14 bps at α 0.05/2. Supertrend n=1198, +88 bps, PF 1.30, win 33%, 7/10 positive, LB −23 bps. DOGE alone is 65% / 37% of the summed trade return. Report `var/reports/zoo_pooled_4h_early.json` | FAIL both (point estimates positive in both eras, but neither lower bound clears 0; Keltner also misses the 7-coin rule). Not evidence of profit |
| 2026-10-14 | 4h trend family pooled over 10 coins (Keltner, Supertrend, UT Bot, MACD+EMA200, EMA cross, Donchian, Heikin Ashi, PSAR), walk-forward per coin, max hold 10 days, data 2023-04→2026-10 | 4h / up to 10 d | Keltner +0.50%/trade n=1211 PF 1.30, 9/10 coins positive, bootstrap LB −7 bps; Supertrend +0.45% PF 1.23 9/10, LB −28 bps; others ≈ 0 or negative | FAIL (Keltner narrowly) → out-of-sample re-test on unused 2019-01→2023-03 data |
| 2026-10-14 | Order-book imbalance ±1/±5% + 4h reversal + 24h OI change, fixed z-score combo, trade top/bottom 5–10% | 4h | Factors real: BTC IC t 4.5–5.3, replicated on ETH t 2.2–3.8. Traded: ETH −0.04…−0.18%/trade even at maker fees | FAIL (real but too small) |
| 2026-10-14 | Same factors + all others, walk-forward ridge, extremes only | 4h / 24h | best: 24h long-only top 5%: +0.26%/trade, n=112, t≈1.1 | FAIL (not significant) |
| 2026-10-13 | Cross-sectional momentum, 10 coins, top 3 weekly (14/28/56 d) | 1 week | Sharpe 0.77–0.85 < hold-all 0.93 | FAIL |
| 2026-10-13 | Daily EMA50 filter on 8 unseen coins | days–weeks | better than hold on 4/8 coins (needed 6) | FAIL (vol-sized version cut drawdowns on 8/8) |
| 2026-10-13 | Daily EMA50 filter + vol sizing (BTC, ETH) | days–weeks | DD BTC 66→44%, ETH 61→42%, Sharpe ≥ plain | PASS (folded into the CTA basket) |
| 2026-10-13 | Daily EMA50 filter, long-only (BTC, ETH) | days–weeks | 2023-26 and out-of-sample 2017-23: higher Sharpe, lower DD than hold; long/short version lost | PASS (BTC/ETH only) |
| 2026-10-13 | Funding carry (long spot + short perp) | weeks | ~7%/yr on notional 2023-26, last third ~3.7% (≈2–3% on capital) | real but small |
| 2026-10-13 | Strategy zoo: 19 popular strategies (EMA cross ± VWAP, MACD+EMA200, RSI, RSI(2), Bollinger reversion/squeeze, Supertrend, UT Bot, PSAR, StochRSI, Donchian, Keltner, range+ADX, Heikin Ashi, VWAP reversion, volume fade, engulfing, NY opening range), long+short, 93 tests | 1m–4h, walk-forward | 1m–15m all ≈ −0.10…−0.13%/trade (gross ≈ 0); best 4h Keltner +0.55%/trade n=106, bootstrap LB −82 bps | FAIL |
| 2026-10-13 | Owner's TradingView "1-Min Fibonacci Scalping" (BOS + 0.618 retracement) + bug-fixed/improved versions | 1m–4h | gross 0…+0.1%/trade; 1h improved: +0.34% first half → −0.39% second half | FAIL (code kept private in var/fib) |
| 2026-10-13 | WL Oscillator (own Prime-style build) v1 signals, v2 ChartPrime tutorial method, ETH cross-check — 21 tests | 1h–12h | none pass; BTC 4h diamonds +0.95%/trade n=20 (too few) | FAIL (diamonds tracked forward) |
| 2026-10-13 | Owner's checklist as rules (EMA50 trend, AVWAPs, S/R room, Elliott filter, no CPI/FOMC) | 4h decisions, 1–3 d holds | 118 OOS trades, −0.19%/trade | FAIL |
| 2026-10-13 | Kronos-small (AAAI 2026 candlestick model), zero-shot, after its training period | 1h, 4h | running (var/kronos) | pending |
| 2026-10-01…12 | Lab research cycles (spot, long-only, ≤4h): volatility breakout, trend pullback, range reversion, relative strength, capitulation, Bollinger snapback, US-open breakout, funding settlement bounce, Elliott ABC continuation (5m/1h), OI flush reversal, OI confirmed breakout, crowded-short squeeze, funding extreme, session drift, deep pullback | 5m / 1h | all ≈ 0 gross vs ~0.16% cost; best Elliott 5m gross +0.12%/trade | REJECTED (lab registry var/research.db) |

## Being tracked forward (no backtest verdict possible)

| Since | What | Where |
|---|---|---|
| 2026-10-13 | YouTube BTC calls (More Crypto Online, Daily Entry, Chart Hackers) | `var/guidance/btc_calls.jsonl`, report `var/reports/btc_guidance.json` |
| 2026-10-13 | BTC/ETH daily EMA50 state | guidance report `trend` |
| 2026-10-13 | WL Oscillator BTC 4h diamonds | guidance report `oscillator` |
| 2026-10-14 | Live Binance spot order-book depth (±0.2/0.5/1%) | `var/orderbook/live.db` |
