# Edge candidates - deep sweep, 2026-10-14 (research scout)

Scope: evidence-backed crypto/BTC edges a small Pionex account could exploit with holds of 4 hours to weeks, using
free data. Checked against `docs/STRATEGY_LOG.md` (about 25 tested ideas) and `research/ideas/2026-10-14.md` (scout
cards 1-5; cards 1 and 2 have since been tested and failed, cards 3-5 are still open).

What this file is not: it contains no backtest result. I ran no code and read no return series from `var/`, on purpose,
so the quant's pre-registered tests stay clean. Every number below is a published claim or a secondary summary, labelled
as such. Nothing here is evidence of profitability. I could not read the full text of several key papers (SSRN returned
403; some PDFs were abstracts only), so where I rely on a secondary summary it says so.

Prior scale (1-5): my rough chance that the rule as published, tested once, out of time, with Pionex costs
(0.05% fee + about 0.02% slippage per side, so about 0.14% per round trip, plus half the measured spread), passes the
lab's gates. 1 = under 10%, 2 = 10-25%, 3 = 25-45%, 4 = 45-65%, 5 = over 65%. Priors are judgement, not statistics.

## 1. Bottom line

1. Only one family has independent, cost-aware, multi-researcher support at multi-day holds: long-only trend/time-series
   momentum with volatility sizing. The lab's survivor (CTA v1.1) is in that family. Zarattini-Pagani-Barbon (SFI 25-80)
   report a Sharpe of 1.56 for BTC net of about 10 bps one-way (secondary summaries; I could not read the paper), close to
   the lab's in-sample 1.37. Han-Kang-Ryu find time-series
   momentum strong and cross-sectional momentum weak, which matches the lab's own results (basket trend works, weekly
   relative-strength failed).
2. Everything else is either already tested and dead in this lab (short holds, DVOL, correlation cap, order-book
   factors), a slow state variable with 3-8 independent episodes (halving, MVRV, stablecoins, funding flips), or not
   testable with free history (liquidations, options skew, exchange flows). No non-trend idea in this sweep has a prior
   above 2.5.
3. The biggest risk to the one survivor is not a missing signal but its universe: ten coins chosen in 2026 from today's
   survivors. Two independent studies (Stockl 2022; Grobys-Sandretto-Aijo 2026) show survivorship materially inflates
   crypto backtests. Binance's public archive still holds delisted pairs (LUNA, FTT, EOS files return HTTP 200), so a
   point-in-time test is free. That test (C2) should run before any new sleeve is trusted.
4. Hour-of-day, weekday and other calendar anomalies fail on cost arithmetic or on replication. The popular
   "buy 21:00, sell 23:00 UTC" rule would have to earn about 0.14% per day to break even; its own source reports about
   0.09% per day gross (40.6% a year), with no costs modelled.
5. Free, high-value non-alpha items: the 73% idle cash can earn a yield (Pionex advertises 5% APY on a card-account
   flexible balance; promotional and unverified, see section 7), and several datasets should start being recorded now
   because they cannot be bought back later (section 8).

## 2. Ranked shortlist

| Rank | ID | Candidate | Hold | Evidence grade | Already in log? | Free data | Prior |
|---|---|---|---|---|---|---|---|
| 1 | C1 | Donchian-ensemble trend with continuous exposure (Zarattini et al. 2025) | days-months | B: full-sample, net of 10 bps, survivorship-free universe claimed, no clean OOS | Related only (4h Donchian failed; daily vote passed) | Binance daily klines (have) | 3.5 |
| 2 | C2 | Point-in-time, survivorship-free universe for the trend basket (validation plus breadth) | as v1.1 | A- on the bias itself (two studies); the test is a replication check | No | data.binance.vision incl. delisted pairs | 3 |
| 3 | C3 | Gold-token (PAXG/XAUT) trend sleeve for idle cash | days-months | B: multi-asset trend literature (Hurst-Ooi-Pedersen, 1880-2016); nothing crypto-specific | No | Binance PAXGUSDT daily; Pionex lists both (checked today) | 2.5 |
| 4 | C4 | Perp-premium/funding crowding gate (carry predicts crashes) | weeks | B-: BIS WP, full-sample | Funding extreme at 5m/1h rejected; as basket gate untested | Binance premiumIndexKlines + funding (have funding) | 2 |
| 5 | C5 | Stablecoin-supply growth gate (scout card 4) | weeks-months | C+: event studies, one in-sample 2026 paper, contested | Card 4 untested; 4h IC about 0 | DefiLlama (have, 2017-) | 2 |
| 6 | D3 | 25-delta risk-reversal / term-structure signal | weeks | C+: one dissertation, in-sample, weakening since 2024 | No | No free history: record forward | 2 |
| 7 | D2 | Variance-risk-premium idle-cash sleeve (scout card 3) | 14 d | C | Card 3 untested | DVOL (have) + klines | 2 |
| 8 | F1 | Negative-funding "capitulation" long (K33) | 90 d | D: practitioner, n=7 | No | Funding (have, 2019-09 on) | 2 |
| 9 | M1 | Extreme-drop reversal, daily bars | 1-10 d | C: abstracts only, no significant payoff gap | Intraday capitulation rejected | Klines | 1.5-2 |
| 10 | A4 | CTREND-style cross-sectional trend score (Fieberg et al. JFQA 2025) | weekly | A- (peer reviewed, survives costs) but long-short, ML | Cross-sectional weekly momentum failed | Klines (many coins) | 2 |
| 11 | E1 | MVRV-Z / NUPL / CVDD cycle rules (Grobys et al.) | months | C: 3 cycles | No | BGeometrics free = last 4 years only | 1.5 |
| 12 | I1 | VIX / Nasdaq / DXY risk gate (scout card 5) | weeks | C- | Card 5 untested | FRED (have fetcher) | 1.5 |
| 13 | B3 | Turn-of-month (last day + first 3 days) | 4 d | C: 3-4 papers, inconsistent by sub-period | No | Klines | 1.5 |
| 14 | B4 | "Monday Asia open" (Concretum 2026) | 24 h weekly | D: figure only, no rule | No | Klines 1h | 1.5 |
| 15 | I3 | FOMC/CPI drift | hours-days | D: NY Fed finds BTC orthogonal to macro news | CPI/FOMC filter failed inside the owner's checklist | Klines + calendars | 1 |
| 16 | B1 | 21:00-23:00 UTC seasonality (Quantpedia) | 2 h | C, no costs, one venue | Session drift rejected at 5m/1h | Klines 1h | 1 |
| 17 | G1 | Liquidation-cascade rebound | hours-days | D | OI flush reversal rejected | No free history | 1 |
| 18 | G2 | Spot ETF flows | days | C: levels, 2.75 years | No | Farside (HTML scrape) | 1 |
| 19 | H1 | Halving / 4-year cycle | months | D: n=4 | No | n/a | 1 |
| 20 | K1 | BTC dominance / altseason rotation | weeks | D: anecdotes | No | CoinMetrics/CoinGecko | 1 |
| 21 | I2 | Global M2 / liquidity lead | 10-12 weeks | D: in-sample dashboards | No | FRED | 1 |

Ranks 6-21 are ordered by prior, then by how cheaply they can be tested.

## 3. Gate 0 and the top five: pre-registered test specs

Common rules for all five (copy the style of `pionex_lab/swing/overlays.py`):

- Freeze the rule, parameters, window, seeds and pass criteria in the module docstring with a timestamp BEFORE the run;
  run once; log PASS/FAIL/INSUFFICIENT either way.
- Data is PROXY (Binance) unless stated; decisions on the previous daily close; fills at the next 00:00 UTC open; costs =
  `cta.COST` (7 bps per side plus half the measured Pionex spread; 10 bps spread assumed for coins not in `cta.SPREAD_BPS`);
  also report 4x costs.
- New behaviour goes in as optional hooks whose default reproduces v1.1 byte for byte; the first step of every run is to
  re-derive v1.1 (tsmom_vol "all": CAGR 35.8%, max DD 26.3%, Sharpe 1.37) as a regression check.
- Reuse `overlays.paired_block_bootstrap` (10-day blocks, 20,000 resamples, one-sided lower bound), `overlays.episodes`,
  `cta.stats` thirds, and the uniform-exposure control from `overlays._control`. Alpha 0.05 split over the tests run that
  night.
- Thresholds marked [proposed] are mine; the lead should confirm them before the run, not after.
- Verdict INSUFFICIENT (not PASS) when fewer than 3 distinct episodes or fewer than about 25 independent events exist.

### C1. Donchian-ensemble trend, continuous exposure (prior 3.5)

Published rule (secondary summaries; the quant must replace this paragraph with the paper's exact definitions and cite the
page before running):
- Source: Zarattini, Pagani, Barbon, "Catching Crypto Trends", SFI Research Paper 25-80, SSRN 5209907
  (https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5209907; Concretum summary
  https://concretumgroup.com/catching-crypto-trends-a-tactical-approach-for-bitcoin-and-altcoins/).
- An ensemble of nine Donchian-channel trend models with different lookbacks (short end 5, 10, 20 days; my recollection of
  the grid is 5, 10, 20, 30, 60, 90, 150, 250, 360 - verify), long/flat on closes with a ratcheting mid-line stop, sized by
  volatility (25% target, leverage cap 200% in the paper; we cannot lever), applied to BTC and to a rotating top-20 liquid
  coin portfolio.
- Claimed: BTC from January 2015, net CAGR 30%, vol 17%, Sharpe 1.56, max DD 19%; ETH Sharpe 1.51; BNB 1.06 (via a GitHub
  reading note, https://github.com/alfred1123/Quant_Strategies/pull/61, which also lists internal inconsistencies in the
  paper's MAR and Sortino tables). Top-20 rotation: Sharpe above 1.5 and 10.8% annual alpha versus BTC, after fees;
  survivorship-free dataset since 2015 (abstract). Costs about 10 bps one way (secondary).
- Independent support for the same family: Quantpedia "at MAX" (buy BTC at a 10-50 day high), published 2022 and revisited
  with a true holdout, 2022-02 to 2024-08, where MAX stayed effective and the mean-reversion twin (MIN) failed
  (https://vvv.quantpedia.com/?p=35597; no costs).
- Skeptic flags: full-sample numbers, no walk-forward; every result sits inside the 2015-2025 BTC super-cycle; the
  leverage cap and vol target are not usable on Pionex spot; the lab's v1.1 is already in this family, so a pass is
  evidence the family is robust to signal design, NOT a new independent edge. Expect high correlation with v1.1.

Test spec:
- Question: does a published, un-tuned, wider-lookback ensemble with fractional exposure match v1.1's risk-adjusted return
  with lower turnover and better cost robustness on the same 10 coins and days?
- Implementation: add an optional `weights(t, avail, data)` hook (or a new rule name) to `cta.simulate`; default None keeps
  v1.1. Per coin and day d = yesterday: for each lookback L <= the coin's age, channel state long if close[d] exceeds the
  max close of the previous L days, stays long until close[d] falls below the ratcheted mid-line; f = share of eligible
  channels that are long; target weight = f x (0.40/N)/vol30 (same as v1.1), 100% gross cap, 2% band, same costs. No
  lookback or parameter is tuned.
- Window: all v1.1 decision days (2017-12-16 to latest); primary comparison on identical days; since-2021 reported.
- Gates [proposed]: (1) `cta.run` pass rule (beats equal-weight hold on Sharpe AND max drawdown, whole period and since 2021,
  Sharpe higher in 2 of 3 thirds); (2) non-inferiority: Sharpe >= v1.1 minus 0.15 AND the bootstrap lower bound of the daily
  Sharpe difference vs v1.1 >= -0.40; (3) at 4x costs Sharpe >= v1.1's 4x Sharpe minus 0.10; (4) turnover per year <= 1.25x
  v1.1's 15.6x; (5) no single coin contributes more than 35% of total log return (DOGE alone drove most of the summed
  trade return in the 4h out-of-sample re-test).
- Reported, not gating: 50/50 blend with v1.1; correlation of daily returns with v1.1 (if above 0.95 it is the same bet,
  adopt only for lower turnover); Jan-Oct 2026 behaviour of both; the same run on the C2 universe once C2 exists (a
  confirmation, not a second chance).
- Falsified if gate 1 or 2 fails, or if all the Sharpe comes from 2020-21.

### C2. Point-in-time, survivorship-free universe (Gate 0; prior 3 that v1.1 survives it)

Why: the v1.1 universe (BTC ETH SOL XRP DOGE LINK ADA BNB AVAX LTC) is today's large survivors. Stockl (2022, 3,904 coins,
2014-2021) estimates annualised survivorship bias of 0.93% for value-weighted and 62.19% for equal-weighted crypto
portfolios; Grobys, Sandretto and Aijo (Finance Research Letters, 2026, "On survivor cryptocurrency momentum") find
momentum is not evident in nine coins that survived the top 100 from 2017 to 2024, and profitable only after trimming
(https://osuva.uwasa.fi/handle/11111/20040; both via abstracts). A long/flat trend filter exits losers, which blunts the
bias, but gap risk (LUNA, FTT) and winners such as SOL and AVAX entering after 2020 are real. Large-cap value-style bias
should be near the 0.9% end; the point of the test is to measure it for our rule rather than argue.

Test spec:
- Question: if v1.1 had been run on whatever was liquid at the time, including coins that later died, how much of the 1.37
  Sharpe remains?
- Data: monthly 1d kline zips from data.binance.vision (spot, USDT pairs). HEAD requests on 2026-10-14 returned 200 for
  LUNAUSDT 2022-04, FTTUSDT 2022-10 and EOSUSDT 2019-06, so delisted pairs are kept. The symbol list comes from the S3
  listing described in the binance-public-data README (https://github.com/binance/binance-public-data; verify the listing
  endpoint). Exclude stablecoins, wrapped tokens, leveraged tokens (UP/DOWN/BULL/BEAR) and fiat pairs.
- Universe rule: on the first UTC day of each month rank pairs by trailing 90-day median quote volume; hold the top 10
  (primary) for the month, top 20 reported (this is the Zarattini rotation); needs 120 days of history as in `cta`.
  Implement as an optional `universe(t)` hook on `cta.simulate`. A coin that leaves the set is closed at the next open; a held
  coin whose bars end keeps its last mark in the base run, and takes a 50% haircut at its last bar in a stress run.
- Costs: `cta.COST`; 10 bps spread assumption for coins without a measured Pionex spread (read-only
  `book_ticker` on those that still trade, via the pionex-api skill).
- Gates [proposed]: v1.1 on the PIT top-10 has Sharpe >= 1.0 over 2017-12 to latest AND max DD <= 35% AND Sharpe above the
  PIT hold-all basket's in the whole period and in 2 of 3 thirds AND >= 0.85 at 4x costs AND the stress run keeps Sharpe >=
  0.85. Always report the survivorship delta = Sharpe(fixed-10) minus Sharpe(PIT-10) with a paired bootstrap interval.
- Adoption of top-20: only if its Sharpe >= the top-10's and the added coins' measured Pionex spreads are <= 10 bps.
- A FAIL here does not kill the trend family; it means the live paper book's expectations (and the 1.37) must be cut
  before anyone sizes it.

### C3. Gold-token trend sleeve for idle cash (prior 2.5)

- Source: Hurst, Ooi, Pedersen, "A Century of Evidence on Trend-Following Investing", JPM 2017, 67 markets 1880-2016
  (https://www.aqr.com/Insights/Research/Journal-Article/A-Century-of-Evidence-on-Trend-Following-Investing). Not
  crypto-specific. A 2026 Quantpedia dual-momentum note (IBIT vs GLD, weekly, 8-week lookback chosen in-sample, Sharpe 1.64,
  max DD -43.9%, no costs; https://quantpedia.com/dual-momentum-allocation-between-physical-gold-and-bitcoin-digital-gold/)
  is a warning about lookback picking, not evidence.
- Rationale: v1.1 averages 27% invested, so 73% of NAV is idle. A second, low-correlation trend asset uses that cash
  with the same machinery. Checked 2026-10-14 via the public symbols endpoint: PAXG_USDT and XAUT_USDT are enabled on
  Pionex spot (324 enabled USDT pairs in total). Liquidity and spread are unmeasured.
- Skeptic flags: about 6 years of data (PAXG on Binance starts about late 2020, verify) with gold in one regime; one asset,
  so the test has low power; tokenized-gold premium/discount and issuer risk; Pionex min notional 10 USDT applies.
- Test spec: add PAXG_USDT as an 11th coin in `cta.simulate` with the per-coin risk budget unchanged
  (`target = 0.44`, so (target/N) stays 4%), same tsmom_vote, vol30 sizing, band, 100% gross cap and costs
  (measured Pionex spread for PAXG first). Control: v1.1 as is (target 0.40) on the same days (from PAXG's first day with
  120 days of history). Gates [proposed]: Sharpe higher; max DD not worse by more than 1 point; Sharpe higher in 2 of 3
  thirds; paired bootstrap lower bound of the daily return difference vs the control >= -10% of the control's mean (the
  `overlays` tolerance); PAXG sleeve return correlation with v1.1 below 0.4; same at 4x costs. Report PAXG buy-and-hold as
  the comparator (a gold bull market flatters any long-biased rule). INSUFFICIENT if fewer than 3 PAXG trend episodes
  (runs of IN days separated by 7+ OUT days).

### C4. Perp-premium / funding crowding gate (prior 2)

- Source: Schmeling, Schrimpf, Todorov, "Crypto carry", BIS Working Paper 1087, April 2023
  (https://www.bis.org/publ/work1087.pdf; CEPR DP 20719): futures-spot carry averages above 10% a year and peaks at
  40-60%, is driven by smaller trend-chasing leveraged buyers plus scarce arbitrage capital, and high carry predicts
  crypto price crashes. He, Manela, Ross, von Wachter, "Fundamentals of Perpetual Futures" (arXiv 2212.06888) show perp
  deviations from no-arbitrage prices are large but shrinking over time. I saw abstracts and summaries only.
- Skeptic flags: crowded leverage is highest inside healthy uptrends, so a gate cuts exposure when trend profits are
  large (the same trap that sank the DVOL cap: spikes were followed by rebounds). Two de-risking overlays have already
  failed here. Carry has also compressed since 2021 (lab: funding carry about 3.7% on notional in the last third).
  Crash prediction is a tail claim; the number of independent crashes is small.
- Test spec: scale hook on `cta.simulate`. Signal: 7-day mean of the Binance USDT-M BTCUSDT daily premium-index close
  (`https://fapi.binance.com/fapi/v1/premiumIndexKlines?symbol=BTCUSDT&interval=1d`, confirmed live today; history from the
  perp's 2019-09 launch, verify at fetch) using days up to yesterday; its percentile versus the trailing 365 days (excluding
  today); factor 0.5 when the percentile is 90 or higher, else 1. One parameter set, no sensitivity run. Window from the
  first day with 365 values to latest. Add `prem_7d` and its percentile to `factors.build` for the IC screen at 24h/72h and
  for the left-tail check (probability that the next 30-day basket return is below -15%, trigger days vs others).
- Gates: the same as `overlays.evaluate_card2` (Sharpe higher, DD cut >= 3 points, 2 of 3 thirds, bootstrap vs
  the uniform-exposure control, >= 3 episodes, v1.1 forward 7d/30d return lower after trigger days, placebo median, ex-worst
  stretch) plus left-tail frequency higher after trigger days. Fails like DVOL if the forward-return gate fails.

### C5. Stablecoin-supply growth gate (prior 2; likely INSUFFICIENT)

- Source: Ante, Fiedler, Strehle event study of 565 issuances (issuance follows downturns, positive abnormal returns around
  it; https://www.blockchainresearchlab.org/2020/06/24/how-do-stablecoin-issuances-affect-cryptocurrency-markets/);
  Griffin and Shams (JF 2020, Tether; contested, with critiques by Kruger and LongHash and no independent replication found);
  Chi, Chu, Hao (arXiv 2411.06327): USDT net inflows to exchanges positively predict BTC/ETH at 1-6h, 2017-2023, needing
  labelled exchange addresses we do not have; Jones, Matsui, Knottenbelt 2026 (arXiv 2603.23480, in-sample).
- Skeptic flags: causality can run backwards (issuance follows price); the signal is slow, so there may be only 2-4
  contraction episodes (2022-23 for sure, others unknown until counted); the lab's 4h screen found IC about 0 with the wrong sign in 2022.
- Test spec: scale hook. DefiLlama `https://stablecoins.llama.fi/stablecoincharts/all` (total pegged USD, daily since
  2017-11-29, confirmed live; already stored as `stables`). Rule as card 4: factor 0.5 when the total today-1 is at or below
  its value 30 days earlier; day D used from D+1. Window 2018-01 to latest. Same gates as C4, plus an anti-redundancy
  check: conditional on days when the basket is more than 50% invested, forward 30-day basket return must be lower in
  contraction than in growth months, and the gate must still help after removing days where the basket's own trend vote is
  already out. INSUFFICIENT with fewer than 3 contraction episodes (then track forward only).

## 4. Full catalogue by topic

Format: rule as published | hold | evidence | replicated? | free data | in log? | prior. "Grade" shorthand: A peer
reviewed and cost-aware; B working paper or serious practitioner with costs; C practitioner backtest, no costs or in-sample;
D claims.

### 4.1 Trend and momentum

- **Donchian ensemble** - see C1. B, prior 3.5.
- **Quantpedia "at MAX"** (Padyskak and Vojtko, 2022; revisit 2024): buy BTC when it reaches its x-day maximum, x = 10..50.
  Hold not stated in the text (returns measured over x days). 2015-11 to 2022-02 in-sample plus a holdout 2022-02 to
  2024-08: MAX held up, MIN (buy at a x-day low) did badly. Combined MAX/MIN reported 98% a year return, 48% vol in the
  original, no costs. Gemini data. Lab: daily Donchian-type trend is the survivor family; 4h Donchian failed. Prior 3
  (as a component of C1, not stand-alone).
  https://quantpedia.com/trend-following-and-mean-reversion-in-bitcoin/
- **Time-series momentum, daily/weekly** (Liu and Tsyvinski, RFS 2021, https://www.nber.org/papers/w24877): significant
  intrinsic momentum for BTC, XRP, ETH (weaker for ETH). Han, Kang, Ryu: time-series momentum strong, cross-sectional weak,
  and frictions such as costs and daily fluctuations leave many "significant" portfolios unprofitable (abstract only;
  https://acfr.aut.ac.nz/__data/assets/pdf_file/0009/918729/Time_Series_and_Cross_Sectional_Momentum_in_the_Cryptocurrency_Market_with_IA.pdf).
  Replicated across authors. In log: yes (survivor). 
- **CTREND trend factor** (Fieberg, Liedtke, Poddig, Walker, Zaremba, JFQA, published online July 2025): machine-learning
  aggregation of price and volume indicators across horizons, over 3,000 coins; says it survives costs and persists in big,
  liquid coins; long-short. Complex (elastic net over about two dozen indicators), many researcher degrees of freedom; a
  long-only top-bucket version is unreported in what I saw. Prior 2. https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/trend-factor-for-the-cross-section-of-cryptocurrency-returns/4C1509ACBA33D5DCAF0AC24379148178
- **Cross-sectional momentum / factor momentum**: Liu, Tsyvinski, Wu (market, size, momentum; long-short, 2014-2018
  small-cap sample); Fieberg et al. "Cryptocurrency factor momentum" (Quant. Finance 2023). Weak in liquid coins and after
  costs (Han et al.); Grobys et al. (FMPM 2025, weekly, top-30, 2016-2023) find severe momentum crashes that volatility
  management mitigates (https://link.springer.com/article/10.1007/s11408-025-00474-9). Lab test failed (Sharpe 0.77-0.85
  below hold-all 0.93). Prior 1.5.
- **Vol management**: Moreira and Muir (NBER 22208) vs Cederburg et al. (JFE 2020, real-time failure). Lab already sizes
  by 30-day vol; the correlation cap and DVOL cap both failed. No new test.
- **Dual momentum BTC vs gold** (Quantpedia, 2026): see C3 warning. Prior 1.5 stand-alone.
- **MACD with a daily filter** (Quantpedia 2026, Gemini 2018-12 to 2025-11): Sharpe 0.80-1.07, annual return 4.6-6.6%; no
  costs or holdout. Not worth a test.
- **Red flags to ignore**: Bui and Nguyen, arXiv 2602.11708 (AdaptiveTrend, 6h bars, 70/30 long-short, claimed OOS Sharpe
  2.41, max DD -12.7%, 2022-2024; unknown authors, no code seen, Sharpe far above any peer-reviewed number). arXiv
  2606.00060 (walk-forward XGBoost, claimed Sharpe above 1 but roughly half of folds have positive Sharpe: fragile).
  arXiv 2602.10785 (double OOS EMA: the in-sample winner underperformed unseen data). Baquero, arXiv 2606.00071, surveys
  the field: no peer-reviewed study shows robust superiority over the naive baseline at short-to-medium horizons across
  regimes; daily predictability may not survive costs.

### 4.2 Seasonality

- **21:00-23:00 UTC** (Quantpedia, Padysak and Vojtko; "Overnight Seasonality in Bitcoin"; Gemini, 2015-10 to 2023-06):
  buy at 21:00 UTC, sell at 23:00 UTC. Reported 33% a year (to 2022-02) then 40.6% a year, max DD -22.7%, Calmar 1.79;
  a high-volatility-day filter gives 37.3%, DD -18.9%. No costs, no holdout, one venue, "rough period" in 2022-2023, and
  a strategy page that disagrees with the article on the entry hour. Cost arithmetic: 365 round trips x 0.14% = about 51%
  a year, more than the 40.6% gross. Hold 2 h is below the lab's 4 h floor. Replicated only by the same authors. Lab:
  session drift rejected at 5m/1h. Prior 1. Do not test.
  https://quantpedia.com/the-seasonality-of-bitcoin/
- **Day-of-week / Monday**: Caporale and Plastun (2013-2017, Monday higher for BTC); Baur, Cahill, Godfrey, Liu (15 million
  observations, seven exchanges): time-varying, no persistent pattern, markets efficient; Yaya 2024 non-significant;
  CoinGecko's 2013-2026 note: weekday and weekend means nearly equal. Prior 1.
- **Turn of the month**: Kumar (Managerial Finance 2022, BTC/ETH/LTC 2015-2021) positive; Vasileiou 2023 says exploitable;
  a 2013-2022 GARCH study finds it inconsistent across sub-periods. Window definitions vary (last day plus first three).
  About 12 trades a year makes costs small (1.7% a year), so it is a cheap lottery ticket: one definition, run once, fine to
  skip. Prior 1.5.
- **"Monday Asia open"** (Concretum, 2026): the authors' long-short intraday trend ensemble earns most of its return from
  about 19:00 New York time Sunday for roughly 24 hours, stronger after mid-2020; gross-of-fees Sharpe about 1.6; no
  rule, no costs. Prior 1.5. https://concretumgroup.com/seasonality-in-bitcoin-intraday-trend-trading/
- **Session decomposition after the ETFs** (ParaFi, August 2026; Blockworks 2023; Cointelegraph 2024): moves of 10% or more
  in a week still mostly occur outside NYSE hours (Asia in 51 of 85 weeks since 2021), US share of variance up from about
  24% to 33% after January 2024. Descriptive and regime-dependent; no rule. Prior 1.
  https://parafi.com/signals/bitcoin-biggest-moves-market-hours
- **Halving and month-of-year ("Uptober")**: see H1; Baur et al. find no persistent monthly pattern.

### 4.3 Funding, basis, carry, perp-spot premium

- **Cash-and-carry** (BIS WP 1087; He et al.): long spot, short perp. Lab 2023-26: about 7% a year on notional, last third
  about 3.7% (2-3% on capital), "real but small". Needs a futures short, outside the spot mandate. Prior 2 as a yield.
- **Carry as a crash predictor**: C4.
- **Negative-funding "capitulation" long** (K33 Research, 2024 reports covered by The Block): after the 30-day average
  funding rate turns negative, average 90-day BTC return 79% (median 55%) across seven episodes since 2018, with no costs
  or drawdown. In-sample, n=7, and the headline average is dominated by 2019-20 and 2022-23 rebounds. Lab's funding data
  (2019-09 on) holds about the same handful. Test is underpowered by construction: track forward as an event study, do
  not pre-register as a trading rule. Prior 2. https://www.theblock.co/post/315831/perp-signal-bitcoin-bottom-bullish-year-end-k33
- **Perp-spot deviation arbitrage** (He et al.): large Sharpe even at top-tier Binance costs per the authors, but a
  derivatives, margin and execution business with shrinking deviations. Prior 1.5 for a small account.
- **Coinbase premium and Kimchi premium**: no peer-reviewed predictive test found. CryptoQuant/CryptoSlate (2025): zero
  crossings followed by +1.7% (7d) and +6.2% (30d) over one year of events; level correlation with forward return -0.06.
  Lab has a `cb_1h` fetcher but no stored rows. Prior 1.5.

### 4.4 Options-implied

- **DVOL spike cap**: tested, FAIL (CAGR 20.4% vs 23.1%, no drawdown help).
- **Variance risk premium (VRP)**: Bollerslev, Tauchen, Zhou RFS 2009 (S&P 500); Alexander and Imeraj, J. Alternative
  Investments 2021 (Bitcoin VIX construction); Almeida, Grith, Miftachov, Wang, arXiv 2410.15195: premia depend on the
  volatility regime, with a negative relation between return premium and BVRP across regimes. No paper found that tests
  VRP as a return predictor with an out-of-sample design. Scout card 3 (deploy idle cash after high VRP, 14-day hold).
  Prior 2.
- **25-delta risk reversal**: Neo (SMU PhD dissertation, 2026): daily Deribit April 2021 to December 2025, 1,723
  observations; RR coefficient significant at 1% in a 13-variable regression, strongest in 30-180 day tenors, t from 1.91
  to 3.73 with controls; deterioration after the January 2024 ETF approval; in-sample, not peer reviewed
  (https://ink.library.smu.edu.sg/etd_coll/887). Deribit Insights and Anchorage describe skew and term structure but test
  nothing. Free history does not exist (Deribit expired-instrument OHLC and Tardis first-of-month samples only), so record
  the chain daily from now (section 8). Prior 2.
- **Selling premium** (short strangles etc.): not available on Pionex.

### 4.5 On-chain (free data only)

- **MVRV Z-score, NUPL, CVDD as cycle rules** (Grobys, Nasman, Sandretto, University of Vaasa): rules tested over three
  cycles against buy-and-hold and Monte Carlo random entries; the evidence is three tops and three bottoms.
  https://osuva.uwasa.fi/items/48a4f9df-03ca-4b96-9072-07b462b14dfa/full. Free history is the problem: BGeometrics' free
  tier gives the last 4 years and since September 2026 withholds the latest 7 days for MVRV, SOPR, NUPL; Coin Metrics'
  community tier is being trimmed and my probes returned 400/403. These variables also mostly restate "price far above
  or below its long average", which the trend vote already uses. Prior 1.5.
- **Exchange netflows** (Chi, Chu, Hao): hourly horizon, 2017-2023; needs exchange-address labels (paid). Not testable.
- **Stablecoin supply**: C5.
- **Hash ribbons** (Capriole): self-published, about one event a year, no independent test found. Free hash rate exists
  (blockchain.com, mempool.space). Prior 1.

### 4.6 ETF flows

Mazur and Polyzos (J. Alternative Investments 2025): flows predict price levels but also respond to price; Guliyev and
Ahmadova (2025): cointegration only at the 10% level; FalconX Granger p=0.004 (industry); Citi: flows explain about 46% of
variance (sell-side). History is January 2024 on (2.75 years), one regime, and flows are largely contemporaneous with price.
Farside's table is provisional by its own warning. Prior 1.

### 4.7 Liquidation cascades and open interest

Two 2026 arXiv preprints (2607.27070, 2608.03616) describe cascades (open interest falls about 25% across them) and report
that early-warning signals are event-specific and do not hold out of sample; nothing I found tests rebound returns. Free
history: Binance's `liquidationSnapshot` archive path returned 404 on a 2023 date; Bybit publishes a live stream only;
Tardis gives first-of-month samples. The lab already rejected OI flush reversal at 5m/1h and holds daily OI in
`proxy_market.db` `metrics`. Prior 1.

### 4.8 Halving and cycle effects

Four halvings, each in a different macro regime; skeptical reviews (Scenarica "The Broken Clock", LuxAlgo, others) note
multiple-testing and survivorship in cycle charts, and press commentary says 2025 was the first post-halving year to close
down. Not testable as a rule. Prior 1.

### 4.9 Cross-asset and macro

- **Equity stress (VIX), Nasdaq, DXY gates**: IMF (Adrian et al., 2022): BTC-S&P correlation about 0.01 (2017-19) to 0.36
  (2020-21). Liu and Tsyvinski (2021) found crypto unrelated to stock and macro factors early on. Benigno and Rosa (NY Fed
  Staff Report 1052, 2023): intraday, Bitcoin is orthogonal to monetary and macro news. Scout card 5; VIX CSV confirmed live
  (fredgraph.csv?id=VIXCLS). Prior 1.5.
- **Global M2 / liquidity lead of about 10-12 weeks**: dashboards (NewHedge, TradingView) and a vendor hub reporting
  correlation about 0.5 at a 1-2 month lag (2022-2026) with an unstable lag; no out-of-sample test seen. Prior 1.
- **FOMC / CPI drift**: equity pre-FOMC drift is documented (Lucca-Moench) but weakening; I found no crypto study of drift;
  intraday work finds BTC unresponsive to the direction of surprises and volatility effects instead. Prior 1.

### 4.10 Mean reversion after extreme moves (daily bars)

Corbet and Katsiampa (2018): negative returns revert faster and more strongly than positive ones. A 2026 IJFMR paper on
BTC 2014 to July 2026 (3%, 5%, 7% shocks; 1, 3, 5 days) finds reversal frequency above 50% after extreme drops but no
statistically significant payoff asymmetry (abstract only). Quantpedia's MIN rule failed out of sample (2022-2024). Zaremba et
al. (IRFA 2021, 3,600 coins): the last day's return reverses in illiquid coins but the largest, most tradable coins show
daily momentum; a later working paper says weekly reversal exists only in small, illiquid coins. So the reversal edge sits in
coins we cannot trade at size and the liquid ones trend. Prior 1.5-2.

### 4.11 BTC dominance and rotation

Only trader commentary (thresholds of 45% to 71% contradict each other; three episodes in 2021-22). A measurable target
exists (Altcoin Season Index: share of the top 50 beating BTC over 90 days) but no out-of-sample study. Prior 1.

### 4.12 Cross-sectional anomalies for a long-only account

MAX/lottery: both signs reported (a 2025 intraday study of the top 100 finds the classic negative; another finds "MAX
momentum"); IVOL is subsumed by MAX; weekly reversal is a small-coin effect; momentum lives in large liquid coins; Stockl
shows size premia are overstated by survivorship. Long-short evidence rarely carries to a long-only top bucket. Prior 1.5.

### 4.13 Other

- **Attention** (Liu and Tsyvinski): Google search volume for "Bitcoin" predicts weekly returns, and the "Bitcoin hack"/"Bitcoin"
  ratio predicts lower returns. Free via the unofficial pytrends; Google rescales and revises data per query window, so
  look-ahead is easy. Wikipedia counts are bot-contaminated (scout note). Prior 1.5.
- **Rebalancing premium** (Quantpedia illustration on synthetic data; a 2020 book chapter finds equal weight beats cap weight
  monthly): real in range-bound, uncorrelated assets, negative in strong trends; the lab's cross-sectional results suggest
  trends dominate. Prior 1.5.
- **Grid/range bots** (Pionex's core product): no rigorous study found; user back-tests show positive gross grid profit with
  negative total equity in downtrends. The lab's range-reversion tests were about 0 gross. Prior 1.
- **Token unlocks**: studies of 236 and 16,000 events show pre-event drift in thin-float, early-stage tokens and no
  significant effect for established liquid tokens, so it does not apply to our ten majors. Prior 1.
- **Vendor/promotional**: Grayscale "The Trend is Your Friend" (BTC/cash, 2012-2023, 126% a year, Sharpe 1.9; I could not
  fetch the rule), Global X BTRN ETF materials. Same family as C1; not independent evidence.

## 5. What the sweep says about the existing survivor (v1.1)

- It is in-sample by the log's own account (rules written alongside the first results), so every number is a fit until the
  paper book accrues 60 days.
- Convergent evidence for the family: Zarattini et al. (Sharpe 1.56, BTC, net of 10 bps), the Quantpedia holdout for "at
  MAX", Hurst et al. across 67 markets, Han et al. (time-series strong, cross-sectional weak). Convergent does not mean
  independent: all crypto samples share the same 2015-2025 BTC history.
- Universe risk (C2) is the single most useful open check. Costs are not the issue: v1.1's Sharpe only drops from 1.37 to
  1.22 at 4x costs.
- Market-state note, no view on direction: Glassnode's weekly notes put BTC near the low $80ks after a fall toward $60k in
  June 2026, so the live paper book starts in a regime unlike most of the backtest. January-October 2026 in the proxy data
  is the nearest thing to a recent holdout; the quant can report v1.1 and C1 there as a diagnostic.

## 6. Do-not-test list (arithmetic or data kills them)

- 21-23 UTC and any other hour-of-day long: breakeven needs about 0.14% per round trip; the source reports about 0.09% a day.
- Liquidation-cascade, exchange-flow and skew backtests: no free history. Record, then test in a year.
- Halving, M2-lead, dominance thresholds: too few independent observations to reject anything.
- ML price forecasters (the lab's Kronos run, arXiv 2606.00060): fragile across folds, edge below costs.
- Short holds under 4 hours: already established in the log.

## 7. Free improvements that are not alpha

- **Yield on idle USDT.** A trade-press item says Pionex introduced "Card Flexible Earn" at 5% APY with daily accrual, needing
  Level 2 KYC and at least 100 USDT in the main account (https://tradersunion.com/news/brokers-news/show/2661436-pionex-launches-card-flexible-earn/).
  It is described as a promotional card feature; I did not find a standard Pionex Earn rate and the skill's rules forbid
  touching earn endpoints. If the rate and terms are real, 5% on the 73% idle share would add roughly 3.6 points a year,
  more than any gate here, with counterparty and withdrawal risk. Paper-only mandate: this is an owner decision, not a
  research test.
- **Fees.** Pionex spot is 0.05% maker and taker per several secondary sources; the lab's `verified_fee_source` is still
  null. Confirm on the fee page in a browser.

## 8. Start recording now (cannot be bought back)

| Series | Why | Free source |
|---|---|---|
| Deribit BTC and ETH option chain snapshot, daily 00:00 UTC (ATM IV by expiry, 25-delta RR and butterfly at about 7, 30, 90 days) | skew and term structure; no free history exists | `public/get_book_summary_by_currency?currency=BTC&kind=option` |
| Coinbase BTC-USD vs Binance BTCUSDT daily close | premium, no stored rows yet | `api.exchange.coinbase.com/products/BTC-USD/candles` |
| Binance premiumIndexKlines, all 10 basket coins plus PAXG | cross-section of perp premium | `fapi.binance.com/fapi/v1/premiumIndexKlines` |
| Farside ETF flow table, daily | revisions are not kept by the site | `farside.co.uk/btc/` |
| Binance and Bybit liquidation streams | liquidation history is unavailable | public WebSocket (self-recorded) |
| Pionex bookTicker spreads for every candidate coin | the cost model's spread table is from one day | `api.pionex.com/api/v1/market/bookTickers?type=SPOT` |

## 9. Suggested order for the quant

1. C2 (point-in-time universe) - it resets expectations for everything else.
2. C1 (Donchian ensemble), on the fixed 10 coins and then, as confirmation, on the C2 universe.
3. C3 (gold token) - cheap once PAXG data is fetched and its spread measured.
4. C4 and C5 only if the lead wants more overlays, knowing two overlays have failed and C5 will probably be INSUFFICIENT.
5. Do not spend a night on any item in section 6.

## 10. Reference links used (grouped; each was seen in search results or fetched on 2026-10-14)

- Zarattini, Pagani, Barbon: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5209907 ; Concretum summary and GitHub notes above.
- Han, Kang, Ryu; Liu and Tsyvinski https://www.nber.org/papers/w24877 ; Liu, Tsyvinski, Wu https://www.nber.org/papers/w25882 ;
  Fieberg et al. (CTREND, JFQA) and "Cryptocurrency factor momentum" https://open.icm.edu.pl/handle/123456789/25542 ;
  Grobys et al. https://link.springer.com/article/10.1007/s11408-025-00474-9 ; Grobys, Sandretto, Aijo (survivors)
  https://osuva.uwasa.fi/handle/11111/20040 ; Stockl (survivorship) via https://alexandria.unisg.ch ;
  Zaremba et al. https://ideas.repec.org/a/eee/finana/v78y2021ics1057521921002349.html .
- Schmeling, Schrimpf, Todorov https://www.bis.org/publ/work1087.pdf ; He, Manela, Ross, von Wachter https://arxiv.org/abs/2212.06888 .
- Almeida et al. https://arxiv.org/abs/2410.15195 ; Alexander and Imeraj https://sro.sussex.ac.uk/id/eprint/91094/ ;
  Neo (SMU) https://ink.library.smu.edu.sg/etd_coll/887 .
- Chi, Chu, Hao https://arxiv.org/abs/2411.06327 ; Benigno and Rosa https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr1052.pdf ;
  Baquero https://arxiv.org/abs/2606.00071 .
- Quantpedia: https://quantpedia.com/the-seasonality-of-bitcoin/ , https://quantpedia.com/are-there-any-simple-calendar-effects-in-bitcoin-market/ ,
  https://quantpedia.com/trend-following-and-mean-reversion-in-bitcoin/ , https://quantpedia.com/how-to-design-a-simple-multi-timeframe-trend-strategy-on-bitcoin/ .
- Hurst, Ooi, Pedersen https://www.aqr.com/Insights/Research/Journal-Article/A-Century-of-Evidence-on-Trend-Following-Investing ;
  Bailey and Lopez de Prado (Deflated Sharpe Ratio) https://papers.ssrn.com/abstract=2460551 .
