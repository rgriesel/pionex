"""CTA-style trend basket: the way trend-following funds trade, on 10 Pionex-listed coins (research only).

Pre-registered 2026-10-14 01:00 SAST, before any result.
Universe: BTC ETH SOL XRP DOGE LINK ADA BNB AVAX LTC (Binance spot daily, PROXY); a coin joins once it
has 120 days of history. Decisions on the daily close, traded at the next 00:00 UTC open; spot,
long or cash only (shorting below trend lost on BTC/ETH earlier).
Signals:
  ema50       in while the close is above its 50-day EMA (partly seen before: breadth test)
  tsmom_vote  in while at least 2 of the 20-, 60- and 120-day returns are positive (new)
Sizing:
  equal       each in-coin gets 1/N of capital (N = coins available)
  vol         each in-coin gets (40% / N) / its 30-day annualised volatility, capped so the total
              stays <= 100% of capital (no leverage); only weight changes > 2% are traded
Costs: 5 bps fee + 2 bps slippage per side on traded weight. Benchmarks: equal-weight hold basket
(daily rebalanced) and BTC buy-and-hold.
Pass: tsmom_vote+vol beats the equal-weight hold basket on Sharpe AND max drawdown over the whole
period AND over 2021-01..now, and on Sharpe in >= 2 of 3 thirds of the whole period.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone

from ..strategies.indicators import ema

UNIVERSE = ("BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", "DOGE_USDT", "LINK_USDT", "ADA_USDT", "BNB_USDT", "AVAX_USDT", "LTC_USDT")
SIDE = (5 + 2) / 1e4
DAY = 86_400_000
RULES = "cta-basket v1 (pre-registered 2026-10-14 01:00 SAST)"


def load(paths):
    from ..data.store import MarketView
    view = MarketView(paths.proxy_market)
    data = {}
    for s in UNIVERSE:
        d = view.bars(s, "1D")
        c = list(d.c)
        e = ema(c, 50)
        rets = [0.0] + [c[i] / c[i - 1] - 1 for i in range(1, len(c))]
        rows = {}
        for i, t in enumerate(d.t):
            vol = NAN
            if i >= 30:
                xs = rets[i - 29:i + 1]
                m = sum(xs) / 30
                vol = math.sqrt(sum((x - m) ** 2 for x in xs) / 30 * 365.25)
            rows[t] = {"o": d.o[i], "c": c[i], "ema": e[i], "vol": vol, "age": i,
                       "r20": c[i] / c[i - 20] - 1 if i >= 20 else NAN, "r60": c[i] / c[i - 60] - 1 if i >= 60 else NAN,
                       "r120": c[i] / c[i - 120] - 1 if i >= 120 else NAN}
        data[s] = rows
    return data


NAN = float("nan")


def signal(row, rule):
    if rule == "ema50":
        return row["ema"] == row["ema"] and row["c"] > row["ema"]
    if rule == "tsmom_vote":
        votes = [row[k] > 0 for k in ("r20", "r60", "r120") if row[k] == row[k]]
        return len(votes) == 3 and sum(votes) >= 2
    return True                                                   # "hold"


def simulate(data, rule, sizing, start_ms=0, band=0.02, target=0.40):
    days = sorted(set().union(*[set(v) for v in data.values()]))
    w, out = {}, []
    for k in range(1, len(days) - 1):
        t, prev, nxt = days[k], days[k - 1], days[k + 1]
        if nxt - t != DAY or t - prev != DAY:
            continue
        avail = [s for s in UNIVERSE if prev in data[s] and t in data[s] and nxt in data[s] and data[s][prev]["age"] >= 120]
        if not avail:
            continue
        n = len(avail)
        new = {}
        for s in avail:
            row = data[s][prev]                                   # decided on yesterday's close
            if rule != "hold" and not signal(row, rule):
                continue
            if sizing == "vol" and row["vol"] == row["vol"] and row["vol"] > 0:
                new[s] = (target / n) / row["vol"]
            else:
                new[s] = 1.0 / n
        gross = sum(new.values())
        if gross > 1.0:
            new = {s: v / gross for s, v in new.items()}
        traded = 0.0
        for s in set(new) | set(w):
            a, b = w.get(s, 0.0), new.get(s, 0.0)
            if abs(b - a) > band or b == 0.0 or a == 0.0:
                traded += abs(b - a)
                w[s] = b
        w = {s: v for s, v in w.items() if v > 0 and s in avail}
        r = sum(v * (data[s][nxt]["o"] / data[s][t]["o"] - 1) for s, v in w.items()) - traded * SIDE
        if t >= start_ms:
            out.append((t, r, sum(w.values())))
    return out


def stats(series):
    xs = [r for _, r, _ in series]
    eq, peak, mdd = 1.0, 1.0, 0.0
    for r in xs:
        eq *= 1 + r
        peak = max(peak, eq)
        mdd = max(mdd, 1 - eq / peak)
    m = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))

    def sh(p):
        mm = sum(p) / len(p)
        s = math.sqrt(sum((x - mm) ** 2 for x in p) / len(p))
        return mm / s * math.sqrt(365.25) if s else 0.0
    k3 = len(xs) // 3
    return {"total": eq - 1, "cagr": eq ** (365.25 / len(xs)) - 1, "max_drawdown": mdd,
            "sharpe": m / sd * math.sqrt(365.25) if sd else None,
            "sharpe_thirds": [sh(xs[:k3]), sh(xs[k3:2 * k3]), sh(xs[2 * k3:])],
            "avg_exposure": sum(e for _, _, e in series) / len(series), "days": len(xs),
            "from": datetime.fromtimestamp(series[0][0] / 1000, timezone.utc).date().isoformat()}


def run(paths):
    data = load(paths)
    s21 = int(datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    rep = {"rules": RULES, "venue": "PROXY: Binance spot daily klines, not Pionex"}
    variants = [("ew_hold", "hold", "equal"), ("ema50_equal", "ema50", "equal"), ("ema50_vol", "ema50", "vol"),
                ("tsmom_equal", "tsmom_vote", "equal"), ("tsmom_vol", "tsmom_vote", "vol")]
    for label, start in (("all", 0), ("since_2021", s21)):
        rep[label] = {name: stats(simulate(data, rule, sz, start)) for name, rule, sz in variants}
        btc = {"BTC_USDT": data["BTC_USDT"]}
        days = sorted(btc["BTC_USDT"])
        series = [(t, btc["BTC_USDT"][n]["o"] / btc["BTC_USDT"][t]["o"] - 1, 1.0) for t, n in zip(days, days[1:])
                  if n - t == DAY and t >= max(start, days[120])]
        rep[label]["btc_hold"] = stats(series)
    a, b = rep["all"], rep["since_2021"]
    rep["passes"] = (a["tsmom_vol"]["sharpe"] > a["ew_hold"]["sharpe"] and a["tsmom_vol"]["max_drawdown"] < a["ew_hold"]["max_drawdown"]
                     and b["tsmom_vol"]["sharpe"] > b["ew_hold"]["sharpe"] and b["tsmom_vol"]["max_drawdown"] < b["ew_hold"]["max_drawdown"]
                     and sum(x > y for x, y in zip(a["tsmom_vol"]["sharpe_thirds"], a["ew_hold"]["sharpe_thirds"])) >= 2)
    dst = paths.reports / "cta_basket_v1.json"
    dst.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return rep
