"""Funding carry (cash-and-carry) on BTC and ETH: long spot + short perpetual, collecting funding.

Research only, pre-registered 2026-10-13 before any result. This is the structure Pionex sells as its
Spot-Futures Arbitrage bot. It is outside the lab mandate (it needs a futures short), so nothing here
trades; it measures what the carry would have paid, including the spot/perp price gap (basis).

Data (labelled PROXY, not Pionex): Binance spot 1h klines, Binance USD-M perpetual 1h klines and
settled funding rates, from the proxy window start (2023-04) to now. Pionex publishes no funding
history in its public API.

Position: equal notional long spot and short perp, both legs entered and exited at the 1h open.
P&L per unit of notional = spot return - perp return + funding received by the short at every
settlement held through - costs. Costs: 5 bps fee + 2 bps slippage per leg per side (28 bps a round trip).
Rules:
  always   carry from the first common bar to the last
  gated    after each settlement, enter when the mean of the last 3 settled rates > 0.01% (per 8h)
           and exit when it is below 0; executed at the open of the settlement hour (the position
           entered then misses that settlement; the one exited then has received it)
Reported: net return per unit of notional and per year; on capital with the short at 1x margin
(capital = 2 x notional) and at 3x (capital = 1.33 x notional); by thirds of the period; worst
drawdown of the marked-to-market position; time in the trade; funding, basis and cost parts.
"""
from __future__ import annotations

import json

RULES = "funding-carry v1 (pre-registered 2026-10-13)"
LEG_COST_BPS = 5.0 + 2.0                 # per leg per side
ENTER_MEAN, EXIT_MEAN = 0.0001, 0.0
YEAR_MS = 365.25 * 86_400_000


def align(spot, perp) -> list[tuple]:
    """[(t, spot_open, spot_close, perp_open, perp_close)] on hours present in both."""
    p = {t: (o, c) for t, o, c in zip(perp.t, perp.o, perp.c)}
    return [(t, o, c, *p[t]) for t, o, c in zip(spot.t, spot.o, spot.c) if t in p]


def simulate(rows: list[tuple], funding: list[tuple], rule: str) -> dict:
    fund = [(t, r) for t, r in funding if rows and rows[0][0] < t <= rows[-1][0]]
    fi, recent = 0, []
    cost = 4 * LEG_COST_BPS / 1e4
    closed = funding_got = basis_got = costs = 0.0
    held_hours, trips = 0, 0
    pos = None                                   # (entry spot, entry perp, entry t, funding so far)
    curve, peak, worst = [], 0.0, 0.0
    span = rows[-1][0] - rows[0][0] if rows else 1

    def third(t):
        return min(2, int(3 * (t - rows[0][0]) / span))

    def close_at(t, so, po):
        nonlocal closed, basis_got, costs, pos, trips
        es, ep, et, fg = pos
        basis = (so / es - 1) - (po / ep - 1)
        pnl = basis + fg - cost
        closed += pnl
        basis_got += basis
        costs += cost
        trips += 1
        pos = None

    for t, so, sc, po, pc in rows:
        while fi < len(fund) and fund[fi][0] <= t:   # settlements up to this hour's open
            ft, rate = fund[fi]
            if pos and pos[2] < ft:
                pos = (pos[0], pos[1], pos[2], pos[3] + rate)
                funding_got += rate
            recent = (recent + [rate])[-3:]
            fi += 1
        want = True if rule == "always" else (
            (pos is not None and not (len(recent) == 3 and sum(recent) / 3 < EXIT_MEAN))
            or (pos is None and len(recent) == 3 and sum(recent) / 3 > ENTER_MEAN))
        if pos and not want:
            close_at(t, so, po)
        elif not pos and want:
            pos = (so, po, t, 0.0)
        if pos:
            held_hours += 1
        mtm = closed + ((sc / pos[0] - 1) - (pc / pos[1] - 1) + pos[3] - cost if pos else 0.0)
        curve.append(mtm)
        peak = max(peak, mtm)
        worst = max(worst, peak - mtm)
    if pos:
        t, so, sc, po, pc = rows[-1]
        close_at(t, sc, pc)
    ends = {}                                          # thirds from the marked-to-market curve
    for k, (t, *_) in enumerate(rows):
        ends[third(t)] = k
    thirds = [curve[ends[k]] - (curve[ends[k - 1]] if k else 0.0) if k in ends else 0.0 for k in range(3)]
    years = span / YEAR_MS
    return {"rule": rule, "net_per_notional": closed, "per_year_on_notional": closed / years if years else None,
            "per_year_on_capital_1x": closed / years / 2 if years else None,
            "per_year_on_capital_3x": closed / years / (1 + 1 / 3) if years else None,
            "thirds": thirds, "max_drawdown": worst, "time_in": held_hours / len(rows) if rows else 0.0,
            "round_trips": trips, "funding": funding_got, "basis": basis_got, "costs": costs, "years": years}


def funding_stats(funding: list[tuple], start_ms: int) -> dict:
    rates = [r for t, r in funding if t >= start_ms]
    if not rates:
        return {}
    k = len(rates) // 3
    parts = [rates[:k], rates[k:2 * k], rates[2 * k:]]
    return {"settlements": len(rates), "mean_rate": sum(rates) / len(rates),
            "annualised": sum(rates) / len(rates) * 3 * 365.25,
            "negative_share": sum(r < 0 for r in rates) / len(rates),
            "annualised_by_third": [sum(p) / len(p) * 3 * 365.25 for p in parts]}


def run(paths) -> dict:
    from datetime import date
    from ..data.proxy import funding_series, window_start_ms
    from ..data.store import MarketView
    view = MarketView(paths.proxy_market)
    start = window_start_ms(date.today())
    report = {"rules": RULES, "venue": "PROXY: Binance spot + USD-M perpetual klines and funding, not Pionex"}
    for sym in ("BTC_USDT", "ETH_USDT"):
        rows = align(view.bars(sym, "60M", start_ms=start), view.bars(sym + "_PERP", "60M", start_ms=start))
        fund = funding_series(view.conn, sym)
        report[sym] = {"hours": len(rows), "from": rows[0][0], "to": rows[-1][0],
                       "funding": funding_stats(fund, rows[0][0]),
                       "always": simulate(rows, fund, "always"), "gated": simulate(rows, fund, "gated")}
    dst = paths.reports / "funding_carry_v1.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report
