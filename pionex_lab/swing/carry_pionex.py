"""Funding carry on PIONEX's own data (CLO-61 / Q5). Research only; nothing here trades.

PRE-REGISTERED SAST 2026-10-18 08:55 (timestamp stamped before the Pionex-price run; funding history had been
read once for measurement only: 8h settlements, BTC/ETH back to 2023-01, mean about 7.5%/yr on notional).

Idea: the earlier test (carry.py, 2026-10-13) used Binance funding and prices (PROXY). Pionex publishes its
own funding history (/api/v1/market/fundingRates, no key), so re-measure the same structure on Pionex alone.

Rules (carry.py v1 unchanged, reused through carry.simulate): long spot + short perpetual, equal notional,
both legs at the 1h open; cost 5 bps fee + 2 bps slippage per leg per side (28 bps round trip; Pionex spot
taker 0.05% and futures taker 0.05%). Symbols BTC and ETH only. Rules "always" (verdict) and "gated"
(reported, not in the verdict).
Data: Pionex 1h klines for BTC_USDT, BTC_USDT_PERP, ETH_USDT, ETH_USDT_PERP (about 416 days is all Pionex
serves) and the Pionex funding settlements inside that window. Capital: short at 3x margin, capital =
1.33 x notional (carry.simulate "per_year_on_capital_3x").

PASS (all, for BOTH BTC and ETH, rule "always"):
  1. per_year_on_capital_3x >= 4.0%
  2. net result positive in the first and in the last third of the window (thirds from simulate)
  3. max drawdown of the marked-to-market position <= 1.0% of notional
  4. at least 330 days of common spot/perp 1h bars
FAIL: bars sufficient (4.) but any of 1-3 missing. INSUFFICIENT: fewer than 330 days of bars.
Also reported (no verdict): live Pionex funding across all perps now, live spot/perp spreads, the Pionex vs
Binance-proxy funding on the same dates. Run ONCE; a changed idea is a new test.
A backtest is not proof of profit; the structure also needs a futures short (outside the mandate).
"""
from __future__ import annotations

import json
import time

from . import carry

RULES = "pionex-funding-carry v1 (pre-registered SAST 2026-10-18)"
MIN_DAYS = 330
MIN_ANNUAL_3X = 0.04
MAX_DD = 0.01
SYMBOLS = ("BTC_USDT", "ETH_USDT")


def fetch_funding(client, symbol: str) -> list[tuple[int, float]]:
    """All settlements Pionex serves for a perpetual, oldest first."""
    out, end = {}, None
    while True:
        rates = client.get("/api/v1/market/fundingRates",
                           {"symbol": symbol, "limit": 500, "endTime": end}).data["rates"]
        new = 0
        for r in rates:
            t = int(r["fundingTime"])
            if t not in out:
                out[t] = float(r["fundingRate"])
                new += 1
        if not new or len(rates) < 500:
            break
        end = min(out) - 1
    return sorted(out.items())


def fetch_hourly(client, symbol: str, max_bars: int = 10_000) -> dict[int, tuple[float, float]]:
    """{open_time: (open, close)} of completed 1h bars, as far back as Pionex serves."""
    out, end = {}, None
    while len(out) < max_bars:
        bars, _ = client.klines(symbol, "60M", end_time=end, limit=500)
        new = {k.open_time: (float(k.open), float(k.close)) for k in bars if k.open_time not in out}
        if not new:
            break
        out.update(new)
        end = min(out) - 1
    out.pop(max(out), None)                                   # newest bar is still forming
    return out


def align(spot: dict, perp: dict) -> list[tuple]:
    return [(t, *spot[t], *perp[t]) for t in sorted(spot) if t in perp]


def verdict(per_symbol: dict) -> tuple[str, list[str]]:
    why = []
    for sym, r in per_symbol.items():
        days = r["days"]
        if days < MIN_DAYS:
            return "INSUFFICIENT", [f"{sym}: {days:.0f} days of bars < {MIN_DAYS}"]
        a = r["always"]
        if a["per_year_on_capital_3x"] < MIN_ANNUAL_3X:
            why.append(f"{sym}: {a['per_year_on_capital_3x']:.2%}/yr on 3x capital < {MIN_ANNUAL_3X:.0%}")
        if not (a["thirds"][0] > 0 and a["thirds"][2] > 0):
            why.append(f"{sym}: first or last third not positive {['%.4f' % x for x in a['thirds']]}")
        if a["max_drawdown"] > MAX_DD:
            why.append(f"{sym}: drawdown {a['max_drawdown']:.2%} > {MAX_DD:.0%}")
    return ("FAIL" if why else "PASS"), why


def live_snapshot(client) -> dict:
    """Live Pionex funding for every perp (latest settlement) and BTC/ETH spreads. Timestamped."""
    books = client.get("/api/v1/market/bookTickers").data["tickers"]
    out = {"read_ms": int(time.time() * 1000), "perps": len(books), "spreads_bps": {}}
    for sym in SYMBOLS:
        for s in (sym, sym + "_PERP"):
            b, _ = client.book_ticker(s)
            mid = float(b.bid + b.ask) / 2
            out["spreads_bps"][s] = (float(b.ask) - float(b.bid)) / mid * 1e4
    rows = []
    for b in books:
        try:
            r = client.get("/api/v1/market/fundingRates", {"symbol": b["symbol"], "limit": 1}).data["rates"]
            if r:
                rows.append((b["symbol"], float(r[0]["fundingRate"]), int(r[0]["fundingTime"])))
        except Exception:
            continue
    rows.sort(key=lambda x: -x[1])
    out["latest_rate_annualised_top10"] = [(s, round(r * 3 * 365.25, 4)) for s, r, _ in rows[:10]]
    out["latest_rate_annualised_median"] = sorted(r for _, r, _ in rows)[len(rows) // 2] * 3 * 365.25 if rows else None
    out["symbols_with_rate"] = len(rows)
    return out


def run(paths, client=None) -> dict:
    from ..exchange.pionex_public import PionexPublic
    client = client or PionexPublic()
    report = {"rules": RULES, "venue": "PIONEX spot + PERP klines and funding (public API)"}
    per = {}
    for sym in SYMBOLS:
        rows = align(fetch_hourly(client, sym), fetch_hourly(client, sym + "_PERP"))
        fund = fetch_funding(client, sym + "_PERP")
        t0, t1 = rows[0][0], rows[-1][0]
        per[sym] = {"hours": len(rows), "from": t0, "to": t1, "days": (t1 - t0) / 86_400_000,
                    "funding": carry.funding_stats(fund, t0), "funding_full_history": carry.funding_stats(fund, 0),
                    "always": carry.simulate(rows, fund, "always"), "gated": carry.simulate(rows, fund, "gated")}
    report.update(per)
    report["verdict"], report["reasons"] = verdict(per)
    report["live"] = live_snapshot(client)
    dst = paths.reports / "funding_carry_pionex_v1.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report
