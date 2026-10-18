# Idea card: tokenised stock / index / gold trend sleeve (CLO-62, plan row 4)

Written 2026-10-18 10:55 SAST by Quant B, before any test. Research only.

**Idea.** Pionex lists tokenised US stocks and gold as spot (QQQX, SPYX, TSLAX, NVDAX, PAXG) and perps. Their trends should be
close to uncorrelated with the ten-coin crypto basket. Add them to CTA v1.1 as extra coins with the rules unchanged
(2-of-3 return vote 20/60/120, vol-30 sizing at 4% risk budget per coin, 2% band, 100% gross cap, long or cash).

**Why it might work.** Multi-asset trend literature (Hurst-Ooi-Pedersen) finds trend works across equity indices and
commodities. Gold alone (C3, CLO-4) gave +0.10 Sharpe at 1x costs and failed only at 4x costs.

**Data check (2026-10-18, public endpoints, read only).**
- Pionex daily history is short: QQQX from 2025-07-11 (465 bars), SPYX/TSLAX/NVDAX from 2025-07-02 (474), PAXG from 2025-06-06.
  Too short to test a trend rule, so the signal history is the underlying: Yahoo chart API daily (QQQ, SPY, TSLA, NVDA, GLD),
  2010 onward. Stooq CSV now needs JavaScript and Yahoo `download` returns 401; the chart API works. Label: PROXY.
- Spread (one bookTicker snapshot): NVDAX 0.47 bps, TSLAX 0.28, QQQX 0.14, SPYX 0.13, PAXG 0.02.
- Thin volume: median daily dollar volume over 30 days QQQX $35k, SPYX $35k, NVDAX $117k, TSLAX $176k, PAXG $716k.
  Fine for a $100 canary, nothing more.

**Skeptic flags.** Proxy is the underlying, not the token (weekend/after-hours behaviour, issuer risk, token premium).
2010-2026 is one long US equity bull market, which flatters any long-biased rule. QQQ/SPY are near duplicates. The window
mixes crypto (365-day) and equity calendars. 4% risk budget on low-vol stocks gives about 20% weights.

**Test.** `pionex_lab/swing/tokenised.py`: pre-registered, one run, gates as in C3 at 1x and 4x costs.
