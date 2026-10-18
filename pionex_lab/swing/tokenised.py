"""Q6 (issue CLO-62): tokenised stock / index / gold trend sleeve on CTA basket v1.1 (research only: no order path).

PRE-REGISTERED 2026-10-18 10:53 SAST (machine clock; commit 7d310ec, the first draft said 11:05 by mistake), before the test was run (nothing below changes after a result;
a changed idea is a new test). Idea card: research/ideas/2026-10-18-tokenised-trend-sleeve.md. Not previously tested
(docs/STRATEGY_LOG.md checked; the gold-only sleeve C3 failed at 4x costs and is a different test). Status: PROXY data
(Yahoo chart API daily bars of the underlying, not the Pionex token); not proof of profit.

HYPOTHESIS: trends in US stocks, an index and gold are weakly correlated with the ten-coin crypto basket, so adding them
as extra coins to v1.1, rules unchanged, lifts risk-adjusted return.

ASSETS (5 sleeve coins; Pionex spot symbol <- proxy): QQQX_USDT <- QQQ, SPYX_USDT <- SPY, TSLAX_USDT <- TSLA,
NVDAX_USDT <- NVDA, PAXG_USDT <- GLD. Dividend-adjusted prices. Pionex token history starts mid-2025, too short to test
a trend rule, hence the proxy.
RULE: v1.1 in cta.simulate with the 10 crypto coins plus the 5 sleeve coins (15): tsmom_vote (2 of the 20/60/120
CALENDAR-day returns > 0), vol sizing (target/N)/vol30, 100% gross cap, 2% band, long or cash, fills at the open.
Per-coin risk budget unchanged: target 0.60 with N = 15 gives 4% a coin as in v1.1 (0.40/10). Single parameter set.
Adaptations forced by equity calendars (fixed now): the series is forward-filled onto calendar days (weekends and
holidays: price flat, which tokens do not do, a known proxy error); vol30 = std of the last 30 TRADING-day returns times
sqrt(252); every sleeve coin's features are lagged one extra day, i.e. the row for date t holds features from the
close of day t-1 and open o_t = adjusted close of day t-1, so a decision on the close of t-2 fills at the close of t-1
(never at the decision price; conservative against after-hours trading by tokens).
COSTS: 5 bps fee + 2 bps slippage per side + half the Pionex spread (bps, one bookTicker snapshot 2026-10-18, rounded
to 0.1): QQQX 0.1, SPYX 0.1, TSLAX 0.3, NVDAX 0.5, PAXG 0.0. 4x run multiplies all costs by 4. Spot, no funding.
Median 30-day Pionex dollar volume (QQQX 35k, SPYX 35k, NVDAX 117k, TSLAX 176k, PAXG 716k) is reported; it limits capacity,
not this test.
WINDOW: the control's own v1.1 window (first decision day of cta.simulate on the 10 coins) to the last day on which all
15 series have a bar (trim). Basket and control run on exactly these days.
CONTROL: v1.1 as is (10 coins, target 0.40, measured costs) on the same days.
REGRESSION CHECK first: full-window v1.1 must reproduce CAGR 35.8% / max DD 26.3% / Sharpe 1.37, else VOID.
PROXY VALIDITY: for each sleeve coin, Pearson r between non-overlapping 5-calendar-day returns of the Pionex daily close
and the proxy close over the overlap must be >= 0.9, else INSUFFICIENT (the proxy does not represent the token).

GATES (all five must hold at 1x costs and again at 4x costs; same as C3, sleeve = the 5 added coins):
  1. Sharpe of the 15-coin basket > the control's.
  2. Max drawdown not worse than the control's by more than 1 percentage point.
  3. Sharpe higher than the control's in at least 2 of the 3 equal thirds (cta.stats thirds).
  4. Paired circular block bootstrap (overlays: 10-day blocks, 20,000 resamples, seed 20261014) lower bound (q = 0.025)
     of mean(daily return, basket - control) >= -10% of the control's mean daily return.
  5. Correlation of the sleeve's daily contribution (sum over the 5 coins of weight x open-to-open return, from the
     cta.simulate trace of the 15-coin run, before costs, interval t0 matched to trace day t0 + 1 day) with the control's
     daily net return below 0.4.
VERDICT: INSUFFICIENT if the sleeve has fewer than 8 trend episodes in total (runs of decision days with a coin's vote IN,
merged when separated by fewer than 7 OUT days) or the proxy-validity check fails; else PASS if all gates hold at 1x and
4x; else FAIL. On PASS the CEO sends it to the Red Team.
REPORTED, not gating: CAGR, exposure, turnover, sleeve-only run (5 coins, target 0.20), 2021-on and before-2021 splits,
bootstrap of the Sharpe difference, episodes per coin, Pionex spreads and volumes.
"""
from __future__ import annotations

import json
import math
import time
import urllib.request
from datetime import datetime, timezone

from . import cta, gold, overlays
from .cta import DAY, SIDE

NAN = float("nan")
PROXY = {"QQQX_USDT": "QQQ", "SPYX_USDT": "SPY", "TSLAX_USDT": "TSLA", "NVDAX_USDT": "NVDA", "PAXG_USDT": "GLD"}
SLEEVE = tuple(PROXY)
SPREAD_BPS = {"QQQX_USDT": 0.1, "SPYX_USDT": 0.1, "TSLAX_USDT": 0.3, "NVDAX_USDT": 0.5, "PAXG_USDT": 0.0}
COINS_15 = cta.UNIVERSE + SLEEVE
RULE, SIZING = "tsmom_vote", "vol"
TARGET_15 = 0.60
TARGET_SLEEVE_ONLY = 0.20
MIN_EPISODES = 8
EPISODE_GAP = 7
MIN_PROXY_CORR = 0.9
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{}?period1=1262304000&period2=1792000000&interval=1d"
PIONEX = "https://api.pionex.com/api/v1/market/klines?symbol={}&interval=1D&limit=500"


def costs(mult=1.0):
    c = dict(cta.COST)
    c.update({s: SIDE + SPREAD_BPS[s] / 2 / 1e4 for s in SLEEVE})
    return {s: mult * v for s, v in c.items()}


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def fetch_yahoo(ticker):
    """[(day ms UTC, adjusted open, adjusted close)] for trading days."""
    r = _get(YAHOO.format(ticker))["chart"]["result"][0]
    q, adj = r["indicators"]["quote"][0], r["indicators"]["adjclose"][0]["adjclose"]
    out = []
    for t, o, c, a in zip(r["timestamp"], q["open"], q["close"], adj):
        if None in (o, c, a) or c <= 0:
            continue
        out.append(((t // 86400) * 86_400_000, o * a / c, a))
    return out


def fetch_pionex_closes(symbol):
    k = _get(PIONEX.format(symbol))["data"]["klines"]
    return {int(x["time"]): float(x["close"]) for x in k}


def calendar_rows(bars, end_ms=None):
    """Calendar-day rows for cta.simulate from trading-day bars [(day ms, adj open, adj close)]: price forward-filled,
    features from the close of the previous day, open = previous day's close (see the module docstring)."""
    closes = {t: c for t, _, c in bars}
    d0, d1 = bars[0][0], (end_ms if end_ms is not None else bars[-1][0])
    days = list(range(d0, d1 + 1, DAY))
    C, trading, last = [], [], None
    for t in days:
        if t in closes:
            last = closes[t]
        C.append(last)
        trading.append(t in closes)
    tr_rets, feat = [], []                                        # tr_rets: trading-day returns up to day i
    prev = None
    for i in range(len(days)):
        if trading[i]:
            if prev is not None:
                tr_rets.append(C[i] / prev - 1)
            prev = C[i]
        vol = NAN
        if len(tr_rets) >= 30:
            xs = tr_rets[-30:]
            m = sum(xs) / 30
            vol = math.sqrt(sum((x - m) ** 2 for x in xs) / 30 * 252)
        feat.append({"vol": vol, "r20": C[i] / C[i - 20] - 1 if i >= 20 else NAN,
                     "r60": C[i] / C[i - 60] - 1 if i >= 60 else NAN,
                     "r120": C[i] / C[i - 120] - 1 if i >= 120 else NAN})
    rows = {}
    for i in range(1, len(days)):
        rows[days[i]] = dict(feat[i - 1], o=C[i - 1], c=C[i - 1], ema=NAN, age=i - 1)
    return rows


def load_sleeve(end_ms=None):
    return {s: calendar_rows(fetch_yahoo(p), end_ms) for s, p in PROXY.items()}


def trim(data):
    end = min(max(rows) for rows in data.values())
    return {s: {t: r for t, r in rows.items() if t <= end} for s, rows in data.items()}


def proxy_validity(bars_by_coin, pionex_by_coin, step=5):
    """Pearson r of non-overlapping `step`-calendar-day returns, Pionex daily close vs proxy close, on the overlap."""
    out = {}
    for s in SLEEVE:
        closes = {t: c for t, _, c in bars_by_coin[s]}
        last, cal = None, {}
        for t in range(bars_by_coin[s][0][0], bars_by_coin[s][-1][0] + 1, DAY):
            last = closes.get(t, last)
            cal[t] = last
        days = sorted(t for t in pionex_by_coin[s] if t in cal)
        a, b = [], []
        for i in range(0, len(days) - step, step):
            t0, t1 = days[i], days[i + step]
            if t1 - t0 != step * DAY:
                continue
            a.append(pionex_by_coin[s][t1] / pionex_by_coin[s][t0] - 1)
            b.append(cal[t1] / cal[t0] - 1)
        out[s] = {"corr": gold.corr(a, b) if len(a) > 10 else None, "n": len(a), "first": days[0] if days else None}
    return out


def sleeve_contrib(trace, days):
    total = [0.0] * len(days)
    for s in SLEEVE:
        total = [x + y for x, y in zip(total, gold.sleeve_series(trace, days, s))]
    return total


def in_days(data, days, coin):
    out = []
    for t in days:
        row = data[coin].get(t - DAY)
        if row is not None and row["age"] >= 120 and cta.signal(row, RULE):
            out.append(t)
    return out


def _sims(data, start, mult):
    c = costs(mult)
    trace = []
    basket = cta.simulate(data, RULE, SIZING, start, coins=COINS_15, cost=c, target=TARGET_15, trace=trace)
    control = cta.simulate(data, RULE, SIZING, start, coins=cta.UNIVERSE, cost=c, target=0.40)
    assert [x[0] for x in basket] == [x[0] for x in control], "basket and control cover different days"
    return basket, control, trace


def evaluate(data, start, mult=1.0):
    basket, control, trace = _sims(data, start, mult)
    days = [x[0] for x in basket]
    r = gold.corr(sleeve_contrib(trace, days), [x[1] for x in control])
    eps = {s: overlays.episodes(in_days(data, days, s), EPISODE_GAP) for s in SLEEVE}
    out = gold.decide(basket, control, r, sum(eps.values()))
    out["episodes_by_coin"] = eps
    out["window_start"] = datetime.fromtimestamp(days[0] / 1000, timezone.utc).date().isoformat()
    return out, basket, control


def split(basket, control, cut_ms):
    res = {}
    for name, sel in (("before_2021", lambda t: t < cut_ms), ("2021_on", lambda t: t >= cut_ms)):
        parts = [[x for x in s if sel(x[0])] for s in (basket, control)]
        if all(len(p) > 30 for p in parts):
            res[name] = dict(zip(("basket_15", "control_v11"), map(cta.stats, parts)))
    return res


def snapshot_book(n=5, gap=1.0):
    """Public bookTickers, n snapshots: spread in bps and 30-day median dollar volume per sleeve coin (reported only)."""
    sp = {s: [] for s in SLEEVE}
    for i in range(n):
        for t in _get("https://api.pionex.com/api/v1/market/bookTickers?type=SPOT")["data"]["tickers"]:
            if t["symbol"] in sp:
                b, a = float(t["bidPrice"]), float(t["askPrice"])
                sp[t["symbol"]].append((a - b) / ((a + b) / 2) * 1e4)
        time.sleep(gap)
    vol = {}
    for s in SLEEVE:
        k = _get(PIONEX.format(s).replace("limit=500", "limit=30"))["data"]["klines"]
        dv = sorted(float(x["volume"]) * float(x["close"]) for x in k)
        vol[s] = dv[len(dv) // 2]
    return {"spread_bps_samples": sp, "median_dollar_volume_30d": vol}


def run(paths, write=True):
    crypto = cta.load(paths, cta.UNIVERSE)
    bars = {s: fetch_yahoo(p) for s, p in PROXY.items()}
    end = min([max(rows) for rows in crypto.values()] + [b[-1][0] for b in bars.values()])
    data = trim({**crypto, **{s: calendar_rows(b, end) for s, b in bars.items()}})
    reg = cta.stats(cta.simulate(crypto, RULE, SIZING))
    rep = {"preregistered": "see the module docstring (pionex_lab/swing/tokenised.py)",
           "status": "backtest on PROXY data (Yahoo underlying daily bars); not proof of profit; red team on a PASS",
           "step1_regression": {"stats": reg, "ok": round(reg["cagr"], 3) == 0.358 and round(reg["max_drawdown"], 3) == 0.263
                                and round(reg["sharpe"], 2) == 1.37}}
    if not rep["step1_regression"]["ok"]:
        rep["verdict"] = "VOID (regression check failed)"
    else:
        validity = proxy_validity(bars, {s: fetch_pionex_closes(s) for s in SLEEVE})
        rep["proxy_validity"] = validity
        rep["book_snapshot"] = snapshot_book()
        ctrl_full = cta.simulate(data, RULE, SIZING, coins=cta.UNIVERSE, cost=costs(1.0), target=0.40)
        start = ctrl_full[0][0]
        x1, basket, control = evaluate(data, start, 1.0)
        x4, _, _ = evaluate(data, start, 4.0)
        x1["subperiods"] = split(basket, control, datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
        x1["sleeve_only_target_0.20"] = cta.stats(cta.simulate(data, RULE, SIZING, start, coins=SLEEVE,
                                                                  cost=costs(1.0), target=TARGET_SLEEVE_ONLY))
        rep["window_1x"], rep["window_4x"] = x1, x4
        valid = all(v["corr"] is not None and v["corr"] >= MIN_PROXY_CORR for v in validity.values())
        if x1["episodes"] < MIN_EPISODES or not valid:
            rep["verdict"] = "INSUFFICIENT"
        else:
            rep["verdict"] = "PASS" if x1["all_hold"] and x4["all_hold"] else "FAIL"
    if write:
        (paths.reports / "tokenised_q6.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    return rep
