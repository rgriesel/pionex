# Owner's finished grid bots: what separates winners from losers (CLO-46)

Source: `var/account.db` table `bots` (read-only), `pionex_lab/research/owner_bots.py`, report `var/reports/owner_bots_2026-10-17.json`.
Market context: hourly BTC_USDT klines (local, up to 2026-10-14; 27 of 41 bots have it, the latest 14 finished after the data ends).

## Sample
50 finished bots (48 futures, 2 spot), 41 with complete fields (39 futures grids, 2 spot). All BTC. All started 2026-09-11 .. 2026-10-14:
ONE five-week window, one market (33 of 41 started in a "sideways" CLO-45 regime, 6 bull, 2 low-vol). Bots overlap in time,
so they are not independent. 32 of 41 made money: +506 USDT total on small stakes (3 to 100 USDT; the 3 best gave 296).

## What the money came from
| | USDT |
|---|---|
| total | +506 |
| grid profit (completed buy/sell pairs) | +53 (10%) |
| float profit (position direction/mark) | +453 (90%) |

Long grids +259 (15 of 21 won), short grids +248 (17 of 18 won). The edge, if any, is **directional**, not the grid.

## Rank correlations with total return (Spearman, permutation p, 20,000 shuffles, two-sided)
n=41 unless noted. Treat p as descriptive: 11 features x 2 targets = 22 looks, p=0.05 is expected by chance about once.

| feature | rho | p |
|---|---|---|
| range width % | -0.07 | 0.68 |
| grids | 0.05 | 0.77 |
| leverage | 0.11 | 0.48 |
| investment | -0.01 | 0.98 |
| duration | 0.31 | 0.05 |
| range / (life vol) (n=27) | -0.31 | 0.12 |
| abs move over life (n=27) | 0.33 | 0.09 |
| entry trend alignment (n=27) | -0.01 | 0.96 |

Supported (n=27, exploratory): return vs direction-aligned move rho 0.51 (p 0.007), vs float 0.47 (p 0.014): bots win when
the market moves in their direction (trivially). Grid profit per day vs leverage rho 0.63 (mechanical), grid profit vs realised vol rho 0.40 (p 0.04).
Not supported: range width, grid count, leverage on total return, pair (single pair), entry-vs-trend at start.

## Honest read
No separating factor survives 22 looks. The owner's result is a five-week sample in a market that moved enough to reward a
directional position, 40x (17 bots) leverage included. It does not say the bots have an edge.

## Rules tested (pre-registered in `pionex_lab/research/owner_rules.py` before the run)
14-day windows, BTC 1h Binance PROXY 2023-01 -> 2026-10 (97 windows), band +-8%, 40 rows, stop 0.97 x bottom, costs as in the shadow grids.
| rule | result | verdict |
|---|---|---|
| R1 spot grid only when 14d/90d vol ratio >= 1 | 35 windows run, mean -0.23%/window (all: -0.60%), perm p 0.25, boot lower -124 bps; compounded gated -10% vs always -49% | FAIL |
| R2 futures grid 5x, long if 7d trend > 0 else short (liquidation modelled) | mean -5.1%/window (always long -5.1%, short -7.8%), perm p 0.25, 0 liquidations; compounded ~-100% | FAIL |
| R2 sensitivity 20x (not gated) | 47 of 97 liquidated, mean -33%/window | n/a |

The plain stop-loss grid loses on history in either form; the vol gate only loses less. Windows are 97 and non-overlapping,
the permutation threshold was 0.01 (trial count 168, level 0). Model limits: touch fills, a reflected path for shorts, flat funding charge, conservative liquidation price.
