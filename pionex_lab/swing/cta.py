"""CTA-style trend basket: the way trend-following funds trade, on 10 Pionex-listed coins (research only).

Status: IN-SAMPLE. v1 rules were written 2026-10-13 ~23:00 SAST in the same session as the first
results (an earlier docstring said "pre-registered 01:00 SAST"; that was wrong), and they were informed
by the earlier BTC/ETH EMA50 + vol-sizing tests and the EMA50 breadth test. Treat the numbers as an
in-sample backtest, not an out-of-sample confirmation; the forward paper book is the real test.
v1.1 (2026-10-13, red-team fixes, no rule or parameter changes): weights drift with prices between
rebalances and the band applies to the drifted weights; gross is re-capped at 100% after the band;
a coin is tradable without peeking at tomorrow's bar (a held coin with no bar is marked at its last
price); per-coin costs from measured Pionex spreads; optional 10 USDT minimum buy at a given capital.
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
Costs: 5 bps fee + 2 bps slippage per side on traded weight (v1.1: plus half the measured Pionex
spread per coin). Benchmarks: equal-weight hold basket (same 2% band) and BTC buy-and-hold.
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
# Pionex bid/ask spread in bps, measured 2026-10-13 (5 bookTicker samples per coin); half is paid per side.
SPREAD_BPS = {"BTC_USDT": 0.0, "ETH_USDT": 0.0, "SOL_USDT": 0.9, "XRP_USDT": 0.7, "DOGE_USDT": 1.2,
              "LINK_USDT": 7.7, "ADA_USDT": 4.2, "BNB_USDT": 0.1, "AVAX_USDT": 9.7, "LTC_USDT": 1.6}
COST = {s: SIDE + SPREAD_BPS[s] / 2 / 1e4 for s in UNIVERSE}
MIN_BUY_USDT = 10.0                                               # Pionex minimum buy, all 10 coins
DAY = 86_400_000
RULES = "cta-basket v1.1 (in-sample; v1 rules of 2026-10-13 ~23:00 SAST + red-team bookkeeping fixes)"


def load(paths, symbols=UNIVERSE):
    from ..data.store import MarketView
    view = MarketView(paths.proxy_market)
    data = {}
    for s in symbols:
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
    if rule == "donchian":                                        # swing/donchian.py: row["dc"] = share of channels long
        return row.get("dc", 0.0) > 0
    return True                                                   # "hold"


def drift(w: dict, rets: dict) -> tuple[dict, float]:
    """Let held weights move with prices: returns (drifted weights, portfolio return). Cash earns 0."""
    port = sum(v * rets.get(s, 0.0) for s, v in w.items())
    return {s: v * (1 + rets.get(s, 0.0)) / (1 + port) for s, v in w.items()}, port


def rebalance(w: dict, tgt: dict, tradable, band=0.02, equity=None, min_buy=MIN_BUY_USDT, cost=None):
    """Move drifted weights toward targets. A coin trades when its change exceeds the band or the
    position opens/closes; only coins with a price today can trade; with `equity` (USDT) a buy below
    `min_buy` is skipped (sells are allowed). Gross is then re-capped at 100% by scaling the tradable
    positions down. Returns (new weights, cost as a fraction of equity, traded weight)."""
    cost = COST if cost is None else cost
    new, traded, paid = dict(w), 0.0, 0.0
    for s in set(tgt) | set(w):
        a, b = w.get(s, 0.0), tgt.get(s, 0.0)
        if s not in tradable or b == a or not (abs(b - a) > band or a == 0.0 or b == 0.0):
            continue
        if equity is not None and b > a and (b - a) * equity < min_buy:
            continue
        traded += abs(b - a)
        paid += abs(b - a) * cost.get(s, SIDE)
        new[s] = b
    new = {s: v for s, v in new.items() if v > 1e-12}
    excess = sum(new.values()) - 1.0
    free = sum(v for s, v in new.items() if s in tradable)
    if excess > 1e-12 and free > 0:
        f = max(0.0, (free - excess) / free)
        for s in [s for s in new if s in tradable]:
            traded += new[s] * (1 - f)
            paid += new[s] * (1 - f) * cost.get(s, SIDE)
            new[s] *= f
    return new, paid, traded


def simulate(data, rule, sizing, start_ms=0, band=0.02, target=0.40, capital=None, cost=None, coins=UNIVERSE,
             scale=None, trace=None, universe=None, haircut=0.0, order_trace=None):
    """Daily loop at each 00:00 UTC open: book held coins' open-to-open returns since their last mark,
    drift the weights, decide targets on yesterday's close, rebalance. Returns
    [(interval start, net return, gross exposure, traded weight)]. `capital` (USDT) turns on the
    minimum-buy rule with the allocation never above `capital` (gains swept, losses kept);
    None = unconstrained (fractional) as in v1.
    `scale` (research hook, default None = v1.1 exactly): a function (t, targets, data) -> factor in
    [0, 1], called on every decision day once the targets (after the 100% gross cap) are known and before
    the band/rebalance. All target weights are multiplied by the factor, so it can only cut exposure,
    never add leverage, and it cannot change signals or lookbacks. The function gets a copy of the targets
    and must use only data up to yesterday's close (keys < t); see swing/overlays.py. A factor outside
    [0, 1] (or NaN) raises ValueError instead of being clamped silently. It may also return a dict
    {coin: factor} (coins not listed keep 1), same bounds (swing/btc_gate.py).
    `trace` (research hook, default None): a list that receives (interval start, {coin: weight * return})
    for each booked day (before costs), for per-coin attribution. Rule "donchian" multiplies each target
    by row["dc"] (the share of long channels, swing/donchian.py); other rules are untouched.
    `universe` (research hook, default None = v1.1 exactly): a function t -> set of coins allowed that day (swing/pit.py,
    point-in-time top-N by liquidity); only those coins are decidable and count in N, so a held coin that drops out
    gets target 0 and is closed at the next open. `haircut` (research hook, default 0 = a held coin whose bars end keeps
    its last mark): the share of a held coin's value lost on the first day after its last bar (stress run)."""
    days = sorted(set().union(*[set(data[s]) for s in coins]))
    w, mark, out, eq, pend = {}, {}, [], 1.0, None
    last = {s: max(data[s]) for s in coins if data[s]} if haircut else {}
    dead = set()
    for t in days:
        rets = {}
        for s in w:
            if t in data[s]:                                      # a held coin without a bar keeps its mark
                rets[s] = data[s][t]["o"] / mark[s] - 1
                mark[s] = data[s][t]["o"]
            elif haircut and s not in dead and t > last[s]:       # bars ended while held: one-off loss
                rets[s] = -haircut
                dead.add(s)
        if trace is not None and w:
            trace.append((t, {s: v * rets.get(s, 0.0) for s, v in w.items()}))
        w, port = drift(w, rets)
        if pend:
            t0, paid, gross, traded = pend
            r = (1 - paid) * (1 + port) - 1
            eq *= 1 + r
            if t0 >= start_ms:
                out.append((t0, r, gross, traded))
            pend = None
        allowed = None if universe is None else universe(t)
        avail = [s for s in coins if (allowed is None or s in allowed) and t in data[s] and t - DAY in data[s]
                 and data[s][t - DAY]["age"] >= 120]
        if not avail:
            if w:                                                 # nothing decidable today: keep holding
                pend = (t, 0.0, sum(w.values()), 0.0)
            continue
        n = len(avail)
        new = {}
        for s in avail:
            row = data[s][t - DAY]                                # decided on yesterday's close
            if rule != "hold" and not signal(row, rule):
                continue
            if sizing == "vol" and row["vol"] == row["vol"] and row["vol"] > 0:
                new[s] = (target / n) / row["vol"]
            else:
                new[s] = 1.0 / n
            if rule == "donchian":
                new[s] *= row["dc"]
        gross = sum(new.values())
        if gross > 1.0:
            new = {s: v / gross for s, v in new.items()}
        if scale is not None:
            f = scale(t, dict(new), data)
            fs = f.values() if isinstance(f, dict) else (f,)       # a dict = per-coin factors (missing coin = 1)
            for x in fs:
                if not (0.0 <= x <= 1.0 + 1e-9):                  # also rejects NaN
                    raise ValueError(f"scale() must return a factor in [0, 1], got {f!r} on {t}")
            if new and isinstance(f, dict):
                new = {s: v * f.get(s, 1.0) for s, v in new.items()}
            elif new and f < 1.0:
                new = {s: v * f for s, v in new.items()}
        tradable = {s for s in coins if t in data[s]}
        usdt = None if capital is None else capital * min(eq, 1.0)  # allocation capped at `capital` (owner's cap)
        before = dict(w) if order_trace is not None else None
        w, paid, traded = rebalance(w, new, tradable, band, usdt, cost=cost)
        if order_trace is not None:
            order_trace.append({"t": t, "before": before, "after": dict(w), "equity": usdt})
        for s in w:
            if s in tradable:
                mark[s] = data[s][t]["o"]
        pend = (t, paid, sum(w.values()), traded)
    return out


def stats(series):
    xs = [x[1] for x in series]
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
            "avg_exposure": sum(x[2] for x in series) / len(series), "days": len(xs),
            "turnover_per_year": sum(x[3] for x in series if len(x) > 3) * 365.25 / len(xs),
            "from": datetime.fromtimestamp(series[0][0] / 1000, timezone.utc).date().isoformat()}


def run(paths):
    data = load(paths)
    s21 = int(datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    rep = {"rules": RULES, "venue": "PROXY: Binance spot daily klines, not Pionex",
           "status": "in-sample backtest (rules informed by earlier BTC/ETH tests); not proof of future profit"}
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
    # Capital checks (not part of the pass test): the 10 USDT minimum buy at the sizes we would run.
    rep["capital"] = {f"tsmom_vol_{c}usdt": stats(simulate(data, "tsmom_vote", "vol", capital=c)) for c in (100, 500, 1000)}
    rep["capital"]["tsmom_equal_1000usdt"] = stats(simulate(data, "tsmom_vote", "equal", capital=1000))
    rep["capital"]["btc_eth_vol_100usdt"] = stats(simulate(data, "tsmom_vote", "vol", capital=100, coins=("BTC_USDT", "ETH_USDT")))
    rep["capital"]["tsmom_vol_4x_costs"] = stats(simulate(data, "tsmom_vote", "vol", cost={s: 4 * v for s, v in COST.items()}))
    dst = paths.reports / "cta_basket_v1_1.json"
    dst.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return rep
