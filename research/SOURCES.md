# Research sources for the Scout - curated 2026-10-14

Quality over quantity. Each line says why the source earns a place. "Checked" means I opened it or called it on
2026-10-14 (search result, fetch or API call); "not re-checked" means it comes from memory or an older note, so confirm
before building on it. Evidence rule for everything below: a source is an idea generator, never proof. Prefer sources that
state costs, a holdout and a data window; discount anything that reports a Sharpe above 2 with no code.

## 1. Read first (the six that pay for themselves)

1. **Concretum Group** - https://concretumgroup.com/ and https://concretumgroup.substack.com/ (checked). Home of Zarattini
   et al.'s crypto trend work and short, rule-level notes; the closest thing to a public, replicable crypto CTA.
2. **Quantpedia blog and screener** - https://quantpedia.com/ (checked). Every crypto note gives the exact rule, data and a
   hypothetical-results caveat; its BTC seasonality and "at MAX" pieces are the most replicated retail-level ideas, though
   they usually omit costs.
3. **Papers With Backtest** - https://paperswithbacktest.com/ (checked). Searchable paper-to-strategy summaries with dates;
   good for finding recent (2026) rule definitions fast. Treat summaries as pointers to the paper.
4. **arXiv q-fin** - https://arxiv.org/list/q-fin.TR/recent , https://arxiv.org/list/q-fin.ST/recent ,
   https://arxiv.org/list/q-fin.PM/recent (list URL form not re-checked, search hits checked). Free, fast, and full of
   crypto papers; quality is uneven, so check authors and whether a holdout and costs exist.
5. **Glassnode "The Week On-chain" / BTC Market Pulse** - https://research.glassnode.com/ (checked, week 42 of 2026 live).
   Free weekly read of on-chain profitability, realised cap, ETF and options positioning; use for regime context and for
   which metrics exist, not for rules.
6. **Deribit Insights, weekly derivatives analytics** - https://insights.deribit.com/ (checked, week 40 of 2026 live).
   The free source for options skew, term structure and DVOL context; the only place the 25-delta risk-reversal narrative
   is published regularly.

## 2. Academic and institutional paper feeds

- **SSRN** - https://papers.ssrn.com/ (search "cryptocurrency", "bitcoin", "perpetual"); many pages return 403 to
  automated fetch, so open in a browser. Source of Zarattini et al., Griffin and Shams, Liu and Tsyvinski.
- **NBER** - https://www.nber.org/ (Liu-Tsyvinski w24877, Liu-Tsyvinski-Wu w25882, Moreira-Muir w22208). Full PDFs, free.
- **BIS working papers** - https://www.bis.org/wpapers/ (checked via WP 1087 "Crypto carry"). Rigorous crypto
  market-structure work (carry, stablecoins, leverage) with no sales agenda.
- **NY Fed staff reports and Liberty Street** - https://www.newyorkfed.org/research (checked via SR 1052). Best source
  for "does BTC react to macro news" with intraday event studies.
- **University of Vaasa open archive (OSUVA)** - https://osuva.uwasa.fi/ (checked). Klaus Grobys and co-authors publish open
  access crypto momentum, volatility-management, on-chain-cycle and survivorship studies.
- **University of St. Gallen "alexandria"** - https://alexandria.unisg.ch/ (checked via the survivorship-bias study). Open
  repository for Stockl's work on survivorship and delisting bias.
- **SFI (Swiss Finance Institute) research papers** - https://www.sfi.ch/ (not re-checked). Venue of "Catching Crypto Trends".
- **CXO Advisory** - https://www.cxoadvisory.com/ (checked). Plain-English summaries of academic crypto and momentum papers,
  useful to triage before reading the PDF.
- **Alpha Architect** - https://alphaarchitect.com/ (checked). Careful academic-to-practice write-ups on factors, trend
  following and backtest hygiene.

## 3. Practitioner research with usable rules

- **Delphic Alpha ("The Replicator")** - https://delphicalpha.substack.com/ (checked). Replicates published strategies
  such as the Donchian ensemble; paywall on some posts.
- **Financial Noob** - https://financialnoob.substack.com/ (checked). Short pandas-driven crypto studies (momentum vs mean
  reversion by horizon) with the caveats stated.
- **Harbourfront Quant** - https://harbourfrontquant.substack.com/ (checked). Compact trend-following and risk-premia
  comparisons on Bitcoin.
- **Ecoinometrics** - https://ecoinometrics.substack.com/ (checked). Econometric treatment of BTC returns vs ETF flows,
  macro and on-chain; partly paid.
- **K33 Research** - https://k33.com/research (checked, H1 2026 round-up live). Funding, basis and positioning notes with
  specific event counts; it is a commercial desk with a stated lean, so read for data.
- **ParaFi Signals** - https://parafi.com/signals/ (checked, August 2026 session analysis). Hourly-data studies of when
  BTC moves, with stated definitions.
- **Capriole (Charles Edwards)** - https://capriole.com/ (checked). Origin of hash ribbons and miner-cycle metrics; author-published,
  so treat claims as hypotheses.
- **Kaiko Research** - https://research.kaiko.com/ and **Coin Metrics State of the Network** - https://coinmetrics.io/ (not
  re-checked). Market microstructure, liquidity and on-chain research with documented methods.
- **Galaxy Research** - https://www.galaxy.com/insights/research/ (not re-checked). Institutional-grade market notes.

## 4. Method and skepticism (read once, apply forever)

- **Bailey and Lopez de Prado, "The Deflated Sharpe Ratio"** - https://papers.ssrn.com/abstract=2460551 (checked). The
  standard correction for selection bias and non-normal returns; use it whenever more than one variant was tried.
- **Harvey, Liu, Zhu, "... and the Cross-Section of Expected Returns"** - https://doi.org/10.1093/rfs/hhv059 (checked).
  Why t above 3 is the bar for a new factor; the origin of the lab's Bonferroni habit.
- **Hurst, Ooi, Pedersen, "A Century of Evidence on Trend-Following Investing"** - https://www.aqr.com/Insights/Research/Journal-Article/A-Century-of-Evidence-on-Trend-Following-Investing (checked).
  The best single case for the family the lab's survivor belongs to, and for diversifying it across assets.
- **Cederburg et al., JFE 2020** - https://doi.org/10.1016/j.jfineco.2020.04.015 (cited in the lab's idea cards). The
  critique of volatility-managed portfolios; relevant after the correlation cap and DVOL cap both failed.
- **Baquero, arXiv 2606.00071** - https://arxiv.org/abs/2606.00071 (checked). A 2026 survey of Bitcoin prediction studies and
  their evaluation flaws; a checklist for scoring any new paper.
- **Stockl (2022) and Grobys-Sandretto-Aijo (2026)** on survivorship (see the St. Gallen and OSUVA entries in section 2).
  The reason the lab's universe needs a point-in-time test.
- **Quantopian lecture series** (YouTube, archived) - covers p-hacking, overfitting and walk-forward in one place;
  equity examples, same logic (not re-checked).

## 5. GitHub: engines, analytics, strategy collections, data tools

Stars and last push from the GitHub API on 2026-10-14 (checked).

| Repo | Why it is useful | Stars / last push / licence |
|---|---|---|
| `freqtrade/freqtrade` | Crypto bot with backtesting and hyperopt (it also ships look-ahead-bias analysis tooling; not re-verified); the reference for how a retail engine handles fees and slippage | 55k / today / GPL-3 |
| `nautechsystems/nautilus_trader` | Event-driven, deterministic engine in Rust/Python; the model for realistic fills and a backtest-to-live path | 30k / today / LGPL-3 |
| `polakowo/vectorbt` | Fast vectorised research on many parameter sets; use only with deflated-Sharpe discipline because grids are cheap | 9.4k / today / non-standard licence, check |
| `kernc/backtesting.py` | Minimal single-asset backtester, good for a second-opinion replication of a rule | 9k / 2026-08 / AGPL-3 |
| `jesse-ai/jesse` | Python crypto backtesting with multi-timeframe support and a strategy library | 8.6k / 2026-10-12 / MIT |
| `ccxt/ccxt` | Uniform REST client for 100+ exchanges' public market data (funding, OI, klines) | 44k / today / MIT |
| `bmoscon/cryptofeed` | WebSocket feed handler for recording trades, books and liquidations yourself | 2.9k / 2026-10-13 / non-standard licence |
| `binance/binance-public-data` | Documents the data.binance.vision archive (klines, funding, premium index, metrics) the lab already uses | README read; stars not fetched |
| `pionex-official/pionex-open-api` | Official OpenAPI spec for Pionex endpoints (via the pionex-api skill) | not re-checked |
| `ranaroussi/quantstats` | Tear sheets: drawdowns, rolling Sharpe, monthly returns; cheap sanity plots | 7.7k / 2026-09 / Apache-2 |
| `skfolio/skfolio` | Scikit-learn style portfolio optimisation with portfolio-level cross-validation (walk-forward and purged variants; not re-verified) | 2.5k / today / BSD-3 |
| `stefan-jansen/alphalens-reloaded` | Information-coefficient and quantile analysis of factors; the lab's `factors.py` does the same by hand | 671 / today / Apache-2 |
| `pst-group/pysystemtrade` | Rob Carver's production-style trend system: forecast scaling, vol targeting, costs; best open reference for CTA design | 3.5k / 2026-10-08 / GPL-3 |
| `stefan-jansen/machine-learning-for-trading` | 3rd-edition code for factor research and honest validation | 21k / 2026-10-13 / MIT |
| `paperswithbacktest/awesome-systematic-trading` | Curated index of libraries, papers, strategies | 14.7k / 2026-09-28 / no licence |
| `wilsonfreitas/awesome-quant` | Broad index of quant libraries and resources | 30k / 2026-10-14 / no licence |
| `freqtrade/freqtrade-strategies` | Idea source only: many strategies, almost none with cost-aware out-of-sample evidence | 5.5k / 2026-09-08 / GPL-3 |

## 6. Free data APIs (exact URLs)

All unsigned and read-only. "Checked" = called or HEAD-requested on 2026-10-14.

| Data | URL | Notes |
|---|---|---|
| Binance klines, funding, premium index, OI/long-short "metrics" archive | `https://data.binance.vision/data/spot/monthly/klines/{SYMBOL}/{interval}/{SYMBOL}-{interval}-{YYYY-MM}.zip` ; `.../futures/um/monthly/premiumIndexKlines/BTCUSDT/1d/...` ; `.../futures/um/daily/metrics/BTCUSDT/...` | Checked (HTTP 200). Keeps delisted pairs (LUNAUSDT, FTTUSDT, EOSUSDT). A `liquidationSnapshot` path I tried returned 404. |
| Binance USD-M premium index (live) | `https://fapi.binance.com/fapi/v1/premiumIndexKlines?symbol=BTCUSDT&interval=1d` | Checked: returns OHLC of the premium rate. |
| Deribit DVOL and options | `https://www.deribit.com/api/v2/public/get_volatility_index_data?currency=BTC&start_timestamp=...&end_timestamp=...&resolution=1D` ; chain snapshot `.../public/get_book_summary_by_currency?currency=BTC&kind=option` | DVOL checked (starts 2021-03-24). Chain endpoint documented, not called today. No history of skew: record daily. |
| FRED macro (VIX, Nasdaq, dollar index, 10y) | `https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS` (also `NASDAQCOM`, `DTWEXBGS`, `DGS10`) | Checked: CSV through 2026-10-13. Posts next morning. |
| Stablecoin supply | `https://stablecoins.llama.fi/stablecoincharts/all` | Checked: daily from 2017-11-29, `totalCirculatingUSD`. |
| Bitcoin hash rate, difficulty | `https://api.blockchain.info/charts/hash-rate?timespan=all&format=json` ; `https://mempool.space/api/v1/mining/hashrate/1y` | Both checked. |
| Coinbase BTC-USD candles (premium vs Binance) | `https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=86400` | Checked: about 300+ candles per call, order time/low/high/open/close/volume. |
| Pionex spot symbols, klines, spreads | `https://api.pionex.com/api/v1/common/symbols?type=SPOT` ; `.../market/klines` ; `.../market/bookTickers?type=SPOT` | Checked today: 413 spot symbols, 324 enabled USDT pairs; PAXG_USDT and XAUT_USDT enabled. 1D history about 10,000 bars. Use the pionex-api skill's limits. |
| Coin Metrics community (MVRV, realised cap, active addresses) | docs say `https://api.coinmetrics.io/v4` with no key, 10 requests per 6 s, CC BY-NC | My probes returned 400/403; the tier is being trimmed. Check the current docs before relying on it. |
| BGeometrics on-chain (MVRV, NUPL, SOPR) | `https://bitcoin-data.com/v1/...` | Free tier: 8 requests an hour, 15 a day, last 4 years only, latest 7 days withheld for MVRV/SOPR/NUPL since September 2026. |
| Spot ETF flows | `https://farside.co.uk/btc/` | HTML table, provisional by its own warning; scrape politely and archive each snapshot. |
| Hyperliquid funding and candles | POST `https://api.hyperliquid.xyz/info` (`fundingHistory`, `candleSnapshot`) | Per docs, not called today; the S3 archive holds only L2 snapshots and asset contexts. |
| Tardis.dev | free first-of-month CSV per exchange, no key | Only a sample; full history is paid. |
| Fear and Greed | `https://api.alternative.me/fng/?limit=0` | Lab already stores it; derived from price and volatility, so not independent information. |
| CFTC Commitments of Traders (CME Bitcoin futures) | `https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm` | Weekly (Tuesday positions, Friday release); no predictive study found; leveraged-fund shorts are often basis trades. Not re-checked. |

## 7. YouTube and podcasts (lowest yield; use for ideas, then check the numbers)

- **Top Traders Unplugged** (podcast and video, toptradersunplugged.com; an episode with Rob Carver on crypto trend appeared in
  search) - the best long-form conversations on trend following, risk and why costs matter. Not re-checked for 2026.
- **K33 "Ahead of the Curve"** - https://podcast.k33.com/episodes (checked). Weekly crypto market-structure discussion tied to
  the K33 data.
- **Deribit "Crypto Options Unplugged"** - https://insights.deribit.com/crypto-options-unplugged/ (checked, episode 111). Options
  desk viewpoints on skew and vol regimes.
- **QuantInsti** (YouTube) - structured algo and backtesting education; named in a 2026 channel guide (search result). Beginner
  to intermediate.
- **Hudson and Thames, Better System Trader, Part Time Larry** - from memory, not verified in this sweep; check recent uploads
  before subscribing. Part Time Larry is practical Python/Binance API tutorials; Better System Trader interviews systematic
  traders.
- **Benjamin Cowen (Into The Cryptoverse)** - checked as a large channel; cycle, dominance and risk-model views. Good for what
  the retail crowd believes (halving, dominance); the lab's evidence rules say do not trade it.
- Pipe any video through the lab's `youtube-transcriber` skill and extract the rule before judging. The owner's three BTC-call
  channels are already tracked forward in `var/guidance`.

## 8. Do not spend scout time here

- TradingView "popular strategies" without costs, and Binance Square or social posts quoting win rates.
- Headline "analyst says" stories (CoinDesk/Cointelegraph/BeInCrypto) as evidence; use them only to find the underlying paper or
  dataset.
- arXiv or SSRN papers claiming Sharpe above 2 on 6h or 1h crypto data without code (example: arXiv 2602.11708).
- Strategy marketplaces and paid-course channels; Freqtrade community strategies as evidence (as an idea list they are fine).
