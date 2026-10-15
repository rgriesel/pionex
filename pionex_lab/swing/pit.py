"""C2 Gate 0: point-in-time, survivorship-free universe test of CTA basket v1.1 (research only: no order path).

PRE-REGISTERED 2026-10-15 06:25 SAST (machine clock), before any result below was produced. Nothing changes after a
result; a changed idea is a new test. Issue CLO-2; spec research/edge_candidates_2026-10-14.md section C2; the lead
(board) confirmed the [proposed] gates as written (2026-10-14 23:15 SAST). Status: backtest on PROXY data (Binance spot
daily klines, USDT pairs, delisted pairs kept); v1.1 is itself in-sample. Not proof of profit.

QUESTION: had v1.1 been run on whatever was liquid at the time, including coins that later died, how much of the 1.37
Sharpe remains?

DATA: var/alpha/pit_1d.db (NEW database; proxy_market.db untouched), table bars(symbol, t ms, o, h, l, c, vol, qvol),
built on 2026-10-14 by the previous run of this issue from data.binance.vision monthly 1d zips (28,000 zips, 748 USDT
pairs, 2017-08-17 .. 2026-09-30, timestamps normalised to ms). The fetch script was not kept; the database is the
artifact. Last month in the data is 2026-09, so "latest" = 2026-09-30.
  Segments: a symbol whose bars have a gap of more than 7 days is split into separate coins (BASE_USDT, BASE_USDT#2 ...),
  because a reused ticker (old/new LUNA, FTT after its halt) is a different asset. Gaps of 7 days or less stay in one coin.
  Excluded before ranking: stablecoins and fiat (USDC BUSD TUSD USDP DAI FDUSD USDS USDE USD1 UST BFUSD XUSD SUSD RLUSD
  FRAX PAX BKRW KGST AEUR EUR EURI GBP AUD, and any coin whose 5th..95th percentile close is inside 0.97..1.03), wrapped /
  staked tokens (WBTC WBETH BETH BNSOL), gold tokens (PAXG XAUT: not crypto, belong to C3), leveraged tokens (a name
  that is a listed base plus UP/DOWN/BULL/BEAR, and BULL, BEAR), and tokenised equities/ETFs (base ends in "B" and
  its first bar is on or after 2025-06-01).

UNIVERSE RULE (primary top 10, reported top 20): on the first UTC day of each month M rank coins by the median daily
quote volume (USDT) over the 90 days M-90d .. M-1d; a coin is eligible when it has at least 120 bars before M and at
least 80 bars inside that 90-day window; ties by name. The top N are the month's universe. Implemented as the optional
`universe(t)` hook on cta.simulate (default None = v1.1 exactly): inside the month only universe coins are decidable
and N (the 1/N and 40%/N sizing) counts universe coins that also pass v1.1's own availability test (a bar today and
yesterday, 120 bars of history). A held coin that leaves the set gets target 0 and is closed at the next open. A held
coin whose bars end keeps its last mark in the base run; in the stress run (`haircut=0.5`) it loses 50% on the first
day after its last bar. Everything else is v1.1: tsmom_vote signal (2 of the 20/60/120-day returns > 0), vol sizing
(40%/N per coin / 30-day vol), 100% gross cap, 2% band on drifted weights, decisions on yesterday's close, fills at the
next 00:00 UTC open. Costs: cta.COST for the ten v1.1 coins; every other coin pays cta.SIDE (7 bps) plus half of an
assumed 10 bps spread (12 bps per side). No Pionex spread was measured for the others (most no longer trade or are not
listed on Pionex); that is stated, not hidden. 4x costs multiplies every per-coin cost by 4.

WINDOW: 2018-01-01 .. 2026-09-30 decision days. The first month with a non-empty universe is 2018-01 (no coin has 120
bars before 2017-12-01), so the spec's "2017-12" start is 2018-01-01 here. All compared series are cut to the common
decision days. fixed-10 (the v1.1 coin list on the same data) is also reported on its own full window from 2017-12-16.

STEP 1 (regression check, the run is void if it fails): cta.simulate on proxy_market.db, tsmom_vol "all", must give
CAGR 35.8%, max DD 26.3%, Sharpe 1.37 (rounded) and turnover 15.6x, through the modified simulate with the new hooks
at their defaults.

SERIES (run once each): PIT-10 v1.1 (primary); PIT-10 hold-all (equal weight, no signal, 2% band); fixed-10 v1.1 on
pit_1d.db; PIT-20 v1.1; PIT-10 v1.1 at 4x costs; PIT-10 v1.1 with the 50% haircut.

GATES (all must hold, as confirmed by the lead; v1.1 PASS only if every one is true, else FAIL):
  1. Sharpe(PIT-10 v1.1) >= 1.0 over the window.
  2. Max drawdown of PIT-10 v1.1 <= 35%.
  3. Sharpe(PIT-10 v1.1) > Sharpe(PIT-10 hold-all) over the whole window AND in at least 2 of the 3 equal thirds
     (cta.stats thirds).
  4. Sharpe(PIT-10 v1.1 at 4x costs) >= 0.85.
  5. Sharpe(PIT-10 v1.1 with the 50% haircut) >= 0.85.
REPORTED, not gating: survivorship delta = Sharpe(fixed-10) - Sharpe(PIT-10) with the paired circular block bootstrap
(overlays.paired_block_bootstrap: 10-day blocks, 20,000 resamples, seed 20261014; the 2.5% / 97.5% quantiles are the
two-sided 95% interval); CAGR, drawdown, thirds, exposure, turnover, since-2021 and per-year Sharpe; the universes
(top-10 on each 1 January, months that LUNA, FTT, EOS were in the top 10 / top 20, top-10 members whose bars later
ended); PIT-20 against PIT-10. Top-20 is adopted only if its Sharpe >= the top-10's AND the added coins' measured Pionex
spreads are <= 10 bps; the spreads are measured only if the first part holds, and are not part of this run. The
episodes rule does not apply (a nine-year full-period backtest, not an event overlay). A FAIL does not kill the trend
family; it means the paper book's expectations (the 1.37) must be cut before anyone sizes it.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
import statistics
from bisect import bisect_left
from datetime import datetime, timezone

from . import cta
from .cta import DAY
from .overlays import _sharpe, paired_block_bootstrap
from ..strategies.indicators import ema

# ---- fixed parameters (nothing here is tuned after a result) ---------------------------------------
RANK_DAYS, MIN_HISTORY, MIN_WINDOW_BARS = 90, 120, 80
TOP, TOP_WIDE = 10, 20
GAP_SPLIT_DAYS = 7
DEFAULT_SPREAD_BPS = 10.0
HAIRCUT = 0.5
RULE, SIZING = "tsmom_vote", "vol"
SHARPE_MIN, MAXDD_MAX, SHARPE_MIN_4X, SHARPE_MIN_STRESS = 1.0, 0.35, 0.85, 0.85
STABLE = {"USDC", "BUSD", "TUSD", "USDP", "DAI", "FDUSD", "USDS", "USDE", "USD1", "UST", "BFUSD", "XUSD", "SUSD", "RLUSD",
          "FRAX", "PAX", "BKRW", "KGST", "AEUR", "EUR", "EURI", "GBP", "AUD"}
WRAPPED = {"WBTC", "WBETH", "BETH", "BNSOL"}
GOLD = {"PAXG", "XAUT"}
LEVERAGED_SUFFIX = re.compile(r"^(.+?)(UP|DOWN|BULL|BEAR)$")
EQUITY_FROM = int(datetime(2025, 6, 1, tzinfo=timezone.utc).timestamp() * 1000)
START = int(datetime(2018, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
NAN = float("nan")


def _ms(y, m, d=1):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)


def _iso(t):
    return datetime.fromtimestamp(t / 1000, timezone.utc).date().isoformat()


def cost_map(names, mult=1.0):
    """Per-coin cost per side: cta.COST for the ten v1.1 coins, SIDE + half of 10 bps for the rest."""
    default = cta.SIDE + DEFAULT_SPREAD_BPS / 2 / 1e4
    return {s: mult * cta.COST.get(s.split("#")[0], default) for s in names}


def excluded(base, first_t, bases):
    if base in STABLE or base in WRAPPED or base in GOLD or base in ("BULL", "BEAR"):
        return True
    m = LEVERAGED_SUFFIX.match(base)
    if m and m.group(1) in bases:
        return True
    return base.endswith("B") and first_t >= EQUITY_FROM


def _pegged(closes):
    xs = sorted(closes)
    return xs[int(0.05 * (len(xs) - 1))] >= 0.97 and xs[int(0.95 * (len(xs) - 1))] <= 1.03


def load_series(db_path):
    """{name: {"t","o","c","q"}} after exclusions and gap splitting. Names look like BTC_USDT, LUNA_USDT#2."""
    con = sqlite3.connect(str(db_path))
    raw = {}
    for s, t, o, c, q in con.execute("SELECT symbol, t, o, c, qvol FROM bars ORDER BY symbol, t"):
        r = raw.setdefault(s, ([], [], [], []))
        r[0].append(t); r[1].append(o); r[2].append(c); r[3].append(q)
    con.close()
    bases = {s[:-4] for s in raw if s.endswith("USDT")}
    out = {}
    for s, (t, o, c, q) in raw.items():
        if not s.endswith("USDT") or excluded(s[:-4], t[0], bases):
            continue
        cuts = [0] + [i for i in range(1, len(t)) if t[i] - t[i - 1] > GAP_SPLIT_DAYS * DAY] + [len(t)]
        for k, (a, b) in enumerate(zip(cuts, cuts[1:])):
            if b - a < 2 or _pegged(c[a:b]):
                continue
            out[f"{s[:-4]}_USDT" + ("" if k == 0 else f"#{k + 1}")] = {"t": t[a:b], "o": o[a:b], "c": c[a:b], "q": q[a:b]}
    return out


def months(first_t, last_t):
    y, m = datetime.fromtimestamp(first_t / 1000, timezone.utc).year, datetime.fromtimestamp(first_t / 1000, timezone.utc).month
    while _ms(y, m) <= last_t:
        yield _ms(y, m)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def rank_universe(series, top):
    """{month start ms: [coins]} point in time: only bars before the month start are read."""
    first = min(s["t"][0] for s in series.values())
    last = max(s["t"][-1] for s in series.values())
    out = {}
    for M in months(first, last):
        cand = []
        for name, s in series.items():
            t = s["t"]
            hi = bisect_left(t, M)                                # bars strictly before M
            lo = bisect_left(t, M - RANK_DAYS * DAY)
            if hi >= MIN_HISTORY and hi - lo >= MIN_WINDOW_BARS:
                cand.append((-statistics.median(s["q"][lo:hi]), name))
        cand.sort()
        out[M] = [n for _, n in cand[:top]]
    return out


def universe_fn(sets):
    keys = sorted(sets)

    def f(t):
        d = datetime.fromtimestamp(t / 1000, timezone.utc)
        return set(sets.get(_ms(d.year, d.month), ()))
    f.keys = keys
    return f


def rows_of(s):
    """cta.load() row format from one coin's arrays (same formulas)."""
    c, o, t = s["c"], s["o"], s["t"]
    e = ema(c, 50)
    rets = [0.0] + [c[i] / c[i - 1] - 1 for i in range(1, len(c))]
    rows = {}
    for i, ti in enumerate(t):
        vol = NAN
        if i >= 30:
            xs = rets[i - 29:i + 1]
            m = sum(xs) / 30
            vol = math.sqrt(sum((x - m) ** 2 for x in xs) / 30 * 365.25)
        rows[ti] = {"o": o[i], "c": c[i], "ema": e[i], "vol": vol, "age": i,
                    "r20": c[i] / c[i - 20] - 1 if i >= 20 else NAN, "r60": c[i] / c[i - 60] - 1 if i >= 60 else NAN,
                    "r120": c[i] / c[i - 120] - 1 if i >= 120 else NAN}
    return rows


def align(*series):
    """Cut daily-return series to the days all of them have (same order of days)."""
    days = set.intersection(*[{x[0] for x in s} for s in series])
    return [[x for x in s if x[0] in days] for s in series]


def _yearly(a):
    ys = {}
    for x in a:
        ys.setdefault(datetime.fromtimestamp(x[0] / 1000, timezone.utc).year, []).append(x[1])
    return {y: _sharpe(v) for y, v in sorted(ys.items()) if len(v) > 20}


def evaluate(series, sets10, sets20, proxy_data=None):
    """Run the six series once and apply the gates. `proxy_data` = cta.load() for the regression step."""
    rep = {}
    if proxy_data is not None:
        reg = cta.stats(cta.simulate(proxy_data, RULE, SIZING))
        rep["step1_regression"] = {"stats": reg, "ok": round(reg["cagr"], 3) == 0.358 and round(reg["max_drawdown"], 3) == 0.263
                                   and round(reg["sharpe"], 2) == 1.37 and round(reg["turnover_per_year"], 1) == 15.6}
        if not rep["step1_regression"]["ok"]:
            rep["verdict"] = "VOID (regression check failed)"
            return rep
    fixed_names = [s for s in cta.UNIVERSE if s in series]
    need = set(fixed_names)
    for sets in (sets10, sets20):
        for v in sets.values():
            need.update(v)
    data = {n: rows_of(series[n]) for n in need}
    names = sorted(need)
    u10, u20 = universe_fn(sets10), universe_fn(sets20)
    c1, c4 = cost_map(names), cost_map(names, 4.0)

    def sim(rule, sizing, uni, cost, coins, haircut=0.0, start=START):
        return cta.simulate(data, rule, sizing, start, coins=coins, cost=cost, universe=uni, haircut=haircut)
    fixed_full = sim(RULE, SIZING, None, None, tuple(fixed_names), start=0)
    fixed = sim(RULE, SIZING, None, None, tuple(fixed_names))
    pit10 = sim(RULE, SIZING, u10, c1, names)
    hold10 = sim("hold", "equal", u10, c1, names)
    pit20 = sim(RULE, SIZING, u20, c1, names)
    pit10_4x = sim(RULE, SIZING, u10, c4, names)
    stress = sim(RULE, SIZING, u10, c1, names, haircut=HAIRCUT)
    fixed_hold = sim("hold", "equal", None, None, tuple(fixed_names))
    fixed, pit10, hold10, pit20, pit10_4x, stress, fixed_hold = align(fixed, pit10, hold10, pit20, pit10_4x, stress, fixed_hold)
    st = {k: cta.stats(v) for k, v in (("fixed10_v11", fixed), ("pit10_v11", pit10), ("pit10_hold", hold10), ("pit20_v11", pit20),
                                       ("pit10_v11_4x_costs", pit10_4x), ("pit10_v11_haircut50", stress), ("fixed10_hold", fixed_hold))}
    st["fixed10_v11_full_window"] = cta.stats(fixed_full)
    boot = paired_block_bootstrap([x[1] for x in fixed], [x[1] for x in pit10])
    p, h = st["pit10_v11"], st["pit10_hold"]
    gates = {"1_sharpe_at_least_1.0": p["sharpe"] >= SHARPE_MIN,
             "2_max_dd_at_most_35pct": p["max_drawdown"] <= MAXDD_MAX,
             "3_beats_pit_hold_all_whole_and_2_of_3_thirds": p["sharpe"] > h["sharpe"]
             and sum(a > b for a, b in zip(p["sharpe_thirds"], h["sharpe_thirds"])) >= 2,
             "4_sharpe_at_4x_costs_at_least_0.85": st["pit10_v11_4x_costs"]["sharpe"] >= SHARPE_MIN_4X,
             "5_sharpe_with_haircut_at_least_0.85": st["pit10_v11_haircut50"]["sharpe"] >= SHARPE_MIN_STRESS}
    s21 = [i for i, x in enumerate(pit10) if x[0] >= _ms(2021, 1)]
    since = lambda a: cta.stats(a[s21[0]:]) if s21 else None
    last_t = max(max(series[n]["t"]) for n in series)
    jan = {}
    for M in sorted(sets10):
        if datetime.fromtimestamp(M / 1000, timezone.utc).month == 1:
            jan[_iso(M)] = [n.replace("_USDT", "") for n in sets10[M]]

    def months_in(coin, sets):
        return [_iso(M)[:7] for M in sorted(sets) if any(n.split("#")[0] == coin + "_USDT" for n in sets[M])]
    ever10 = sorted({n for v in sets10.values() for n in v})
    rep.update({
        "window": {"from": _iso(pit10[0][0]), "to": _iso(pit10[-1][0]), "days": len(pit10), "data_last_bar": _iso(last_t)},
        "series": st, "gates": gates,
        "survivorship_delta": {"sharpe_fixed10_minus_pit10": st["fixed10_v11"]["sharpe"] - p["sharpe"],
                               "bootstrap_sharpe_diff_fixed_minus_pit": boot["sharpe_diff"],
                               "bootstrap_mean_daily_diff": boot["mean_diff"]},
        "since_2021": {"pit10_v11": since(pit10), "pit10_hold": since(hold10), "fixed10_v11": since(fixed)},
        "per_year_sharpe": {"pit10_v11": _yearly(pit10), "pit10_hold": _yearly(hold10), "fixed10_v11": _yearly(fixed)},
        "top20_vs_top10": {"pit20_sharpe": st["pit20_v11"]["sharpe"], "pit10_sharpe": p["sharpe"],
                           "first_condition_met": st["pit20_v11"]["sharpe"] >= p["sharpe"],
                           "adopt": False, "note": "adoption also needs the added coins' measured Pionex spreads <= 10 bps; not measured in this run"},
        "universe": {"top10_each_january": jan, "distinct_coins_ever_top10": len(ever10),
                     "top10_members_whose_bars_ended_before_data_end": [n for n in ever10 if series[n]["t"][-1] < last_t - 30 * DAY],
                     "months_in_top10": {c: months_in(c, sets10) for c in ("LUNA", "FTT", "EOS")},
                     "months_in_top20": {c: months_in(c, sets20) for c in ("LUNA", "FTT", "EOS")}}})
    rep["verdict"] = "PASS" if all(gates.values()) else "FAIL"
    return rep


def run(paths, db=None, write=True):
    db = db or paths.root / "alpha" / "pit_1d.db"
    series = load_series(db)
    rep = {"preregistered": "see the module docstring (pionex_lab/swing/pit.py)",
           "venue": "PROXY: Binance spot daily klines incl. delisted pairs, not Pionex",
           "status": "backtest; v1.1 is itself in-sample; not proof of profit; red team pending on a PASS",
           "coins_after_exclusions": len(series)}
    rep.update(evaluate(series, rank_universe(series, TOP), rank_universe(series, TOP_WIDE), cta.load(paths)))
    if write:
        (paths.reports / "pit_universe_c2.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return rep
