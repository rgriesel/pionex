"""Is a Prime-style oscillator worth paying for? Pre-registered tests of the WL Oscillator on BTC.

v2 (run_v2, pre-registered 2026-10-13 after v1 failed): ChartPrime's own tutorial method instead of
fixed-time exits. Signals: a momentum dot (ribbon twist beyond ob) in the direction of the latest trend
arrow, or a diamond (momentum dot + divergence within 6 bars). Stop beyond the last 5 bars' extreme;
half off at 1.5R and the stop moved to entry; the rest at 3R, or at the close after 30 bars. Exits
walked on 1h bars, stop first. Timeframes 1h, 4h, 12h. Same costs and gates as v1, with the bootstrap
alpha divided by every test run on this oscillator (v1 + v2).
Amendment (same day, before seeing any arrow_dot result): trend_pullback never fired (n=0 on all
timeframes; an oversold dot almost never meets a still-bullish trend arrow), so arrow_dot was added:
trend arrow and same-side momentum dot within 6 bars. It counts as 3 more tests (19 in total).

v1:

Pre-registered 2026-10-13, before any result. Default settings only (WaveTrend 10/21, ob 53, pivots 5,
MFI 14, VWAP 50); nothing is fitted, so the whole 3.5 years is out of sample for these rules.
The WL Oscillator is our own build from the paid tool's public description, not ChartPrime's code,
so a result here judges this family of oscillator, not their exact script.

Signals, decided at a completed bar's close, entered at the next bar's open, exited at the close
`HOLD` bars later (no stop or target), one position at a time:
  reversal    reversal dot: long on a bullish one, short on a bearish one
  divergence  divergence mark, same sides
  fair_value  first bar of a fair-value extreme (close beyond 2 sd of rolling VWAP): long below, short above
  power       rank reaching >= 6 of 7 bullish (long) or <= 1 (short) from outside that state
  confluence  reversal dot with a same-side divergence or fair-value extreme within the last 6 bars
Timeframes: BTC 1h (hold 12 bars = 12h) and 4h (hold 12 bars = 48h) from the Binance proxy archive.
Costs: Pionex futures taker 0.05% a side + 2 bps slippage a side + funding (Binance history).
Pass needs all of: >= 100 trades, mean net > 0, profit factor >= 1.1, block-bootstrap lower bound
> 0 at alpha 0.05 / 10 tests (Bonferroni), and net positive in at least 2 of 3 equal time thirds.
Also reported: each signal's gross return minus BTC's plain drift over the same holding time.
"""
from __future__ import annotations

import bisect
import json

from ..data.store import resample
from ..research import metrics
from ..waves.oscillator import calc

RULES = "wl-oscillator v1 (pre-registered 2026-10-13)"
SIGNALS = ("reversal", "divergence", "fair_value", "power", "confluence")
HOLD = 12
FEE_BPS, SLIP_BPS = 5.0, 2.0
TESTS = len(SIGNALS) * 2


def signals(r: dict, i: int) -> dict:
    """Side (+1/-1) of each signal at bar i, or 0."""
    rev, div, fair, bull = r["rev"], r["div"], r["fair"], r["bull"]
    out = {"reversal": rev[i], "divergence": div[i],
           "fair_value": fair[i] if i and fair[i] != fair[i - 1] else 0, "power": 0, "confluence": 0}
    if i and bull[i] == bull[i] and bull[i - 1] == bull[i - 1]:
        if bull[i] >= 6 > bull[i - 1]:
            out["power"] = 1
        elif bull[i] <= 1 < bull[i - 1]:
            out["power"] = -1
    s = rev[i]
    if s and any(div[j] == s or fair[j] == s for j in range(max(0, i - 5), i + 1)):
        out["confluence"] = s
    return out


def simulate(b, r, name, funding=(), hold=HOLD):
    ft = [t for t, _ in funding]
    fc = [0.0]
    for _, x in funding:
        fc.append(fc[-1] + x)
    fee = (FEE_BPS + SLIP_BPS) / 1e4
    step = b.t[1] - b.t[0]
    trades, i = [], 1
    while i < len(b) - hold:
        s = signals(r, i)[name]
        if not s:
            i += 1
            continue
        k, x = i + 1, i + hold                         # enter next open, exit close `hold` bars after the signal
        t0, t1 = b.t[k], b.t[x] + step
        gross = s * (b.c[x] / b.o[k] - 1)
        fund = (fc[bisect.bisect_right(ft, t1)] - fc[bisect.bisect_right(ft, t0)]) * s
        trades.append({"entry_time": t0, "exit_time": t1, "side": "LONG" if s > 0 else "SHORT",
                       "gross_bps": gross * 1e4, "net_bps": (gross - 2 * fee - fund) * 1e4})
        i = x + 1
    return trades


def evaluate(b, r, funding=(), hold=HOLD) -> dict:
    drift = [b.c[i + hold - 1] / b.o[i] - 1 for i in range(1, len(b) - hold)]
    base = sum(drift) / len(drift) * 1e4 if drift else 0.0      # plain long drift per hold, gross bps
    third = (b.t[-1] - b.t[0]) / 3
    out = {}
    for name in SIGNALS:
        tr = simulate(b, r, name, funding, hold)
        net = metrics.summarize(tr)
        lower = metrics.block_bootstrap_lower(tr, 0.05 / TESTS) if tr else None
        thirds = [sum(t["net_bps"] for t in tr if b.t[0] + k * third <= t["entry_time"] < b.t[0] + (k + 1) * third)
                  for k in range(3)]
        gates = {"min_trades": net["n"] >= 100, "positive_mean": (net["expectancy_bps"] or 0) > 0,
                 "profit_factor": (net["profit_factor"] or 0) >= 1.1,
                 "bootstrap_lower_bound": lower is not None and lower > 0,
                 "thirds": sum(v > 0 for v in thirds) >= 2}
        excess = (sum(t["gross_bps"] - (base if t["side"] == "LONG" else -base) for t in tr) / len(tr)) if tr else None
        out[name] = {"status": "PASS" if all(gates.values()) else "FAIL",
                     "failed": [k for k, v in gates.items() if not v], "net": net,
                     "gross_bps": metrics.summarize(tr, "gross_bps")["expectancy_bps"],
                     "excess_vs_drift_bps": excess, "bootstrap_lower_bps": lower, "thirds_bps": thirds,
                     "by_side": {s: metrics.summarize([t for t in tr if t["side"] == s]) for s in ("LONG", "SHORT")}}
    return {"drift_long_gross_bps": base, "signals": out}


RULES_V2 = "wl-oscillator v2, ChartPrime's own trade method (pre-registered 2026-10-13, after v1 failed)"
SIGNALS_V2 = ("trend_pullback", "diamond", "arrow_dot")
TESTS_ALL = TESTS + len(SIGNALS_V2) * 3          # every test run on this oscillator counts (v1 + v2)


def signal_v2(r: dict, i: int, state: int) -> dict:
    """ChartPrime's tutorial method: trend arrow, then a momentum dot / ribbon twist the same way; or a
    diamond (momentum dot + divergence). `state` is the side of the latest trend arrow at bar i.
    arrow_dot (added after trend_pullback never fired, n=0): a trend arrow and a same-side momentum dot
    within 6 bars of each other, marked when the second of the two prints."""
    rev, tr = r["rev"], r["trend"]
    s, recent = rev[i], range(max(0, i - 5), i + 1)
    ad = 0
    for side in (1, -1):
        if (rev[i] == side and any(tr[q] == side for q in recent)) or (tr[i] == side and any(rev[q] == side for q in recent)):
            ad = side
            break
    return {"trend_pullback": s if s and s == state else 0, "diamond": r["diamond"][i], "arrow_dot": ad}


def simulate_v2(b, b1, r, name, funding=(), lookback=5, tp1=1.5, tp2=3.0, max_bars=30):
    """Enter at the next bar's open; stop beyond the last `lookback` bars' extreme; half off at tp1 x risk
    with the stop then moved to entry; the rest at tp2 x risk or after `max_bars` signal bars. Exits are
    walked on 1h bars, stop first when a stop and a target share an hour. Costs as in v1, per half."""
    ft = [t for t, _ in funding]
    fc = [0.0]
    for _, x in funding:
        fc.append(fc[-1] + x)
    fee = (FEE_BPS + SLIP_BPS) / 1e4
    step = b.t[1] - b.t[0]
    idx1 = {t: k for k, t in enumerate(b1.t)}
    states, cur = [], 0
    for x in r["trend"]:                               # side of the latest trend arrow at each bar
        cur = x or cur
        states.append(cur)
    trades, i = [], 1
    while i < len(b) - 1:
        s = signal_v2(r, i, states[i])[name]
        k = idx1.get(b.t[i + 1]) if s else None
        if not s or k is None or i < lookback:
            i += 1
            continue
        entry = b1.o[k]
        stop = min(b.l[i - lookback + 1:i + 1]) if s > 0 else max(b.h[i - lookback + 1:i + 1])
        risk = s * (entry - stop)
        if risk <= 0:
            i += 1
            continue
        t1, t2 = entry + s * tp1 * risk, entry + s * tp2 * risk
        end_t = b.t[i + 1] + max_bars * step
        parts, cur_stop, m = [], stop, k
        while m < len(b1.t) and b1.t[m] < end_t and len(parts) < 2:
            lo, hi = b1.l[m], b1.h[m]
            if (lo <= cur_stop) if s > 0 else (hi >= cur_stop):
                parts += [(cur_stop, m)] * (2 - len(parts))
                break
            if not parts and ((hi >= t1) if s > 0 else (lo <= t1)):
                parts.append((t1, m))
                cur_stop = entry
                if (hi >= t2) if s > 0 else (lo <= t2):
                    parts.append((t2, m))
            elif parts and ((hi >= t2) if s > 0 else (lo <= t2)):
                parts.append((t2, m))
            m += 1
        if len(parts) < 2:
            last = min(m, len(b1.t)) - 1
            parts += [(b1.c[last], last)] * (2 - len(parts))
        t0, t_exit = b1.t[k], b1.t[parts[-1][1]] + 3_600_000
        gross = sum(s * (px / entry - 1) for px, _ in parts) / 2
        fund = (fc[bisect.bisect_right(ft, t_exit)] - fc[bisect.bisect_right(ft, t0)]) * s
        trades.append({"entry_time": t0, "exit_time": t_exit, "side": "LONG" if s > 0 else "SHORT",
                       "gross_bps": gross * 1e4, "net_bps": (gross - 2 * fee - fund) * 1e4,
                       "r_multiple": gross / (risk / entry)})
        i = max(i + 1, next((q for q in range(i + 1, len(b)) if b.t[q] >= t_exit), len(b)))
    return trades


def evaluate_v2(b, b1, r, funding=()) -> dict:
    third = (b.t[-1] - b.t[0]) / 3
    out = {}
    for name in SIGNALS_V2:
        tr = simulate_v2(b, b1, r, name, funding)
        net = metrics.summarize(tr)
        lower = metrics.block_bootstrap_lower(tr, 0.05 / TESTS_ALL) if len(tr) > 1 else None
        thirds = [sum(t["net_bps"] for t in tr if b.t[0] + k * third <= t["entry_time"] < b.t[0] + (k + 1) * third)
                  for k in range(3)]
        gates = {"min_trades": net["n"] >= 100, "positive_mean": (net["expectancy_bps"] or 0) > 0,
                 "profit_factor": (net["profit_factor"] or 0) >= 1.1,
                 "bootstrap_lower_bound": lower is not None and lower > 0,
                 "thirds": sum(v > 0 for v in thirds) >= 2}
        failed = [k for k, v in gates.items() if not v]
        out[name] = {"status": "PASS" if not failed else "INSUFFICIENT_DATA" if failed == ["min_trades"] else "FAIL",
                     "failed": failed, "net": net, "gross_bps": metrics.summarize(tr, "gross_bps")["expectancy_bps"],
                     "avg_r": sum(t["r_multiple"] for t in tr) / len(tr) if tr else None,
                     "bootstrap_lower_bps": lower, "thirds_bps": thirds,
                     "by_side": {s: metrics.summarize([t for t in tr if t["side"] == s]) for s in ("LONG", "SHORT")}}
    return {"signals": out}


def run_v2(paths, cfg) -> dict:
    from ..cli import _universe_bars
    from ..data.proxy import funding_series
    from ..data.store import MarketView
    u, _ = _universe_bars(paths, cfg, "1h", "proxy")
    b1 = u["BTC_USDT"][0]
    fund = funding_series(MarketView(paths.proxy_market).conn, "BTC_USDT")
    report = {"rules": RULES_V2, "data": {"bars_1h": len(b1), "from": b1.t[0], "to": b1.t[-1]}}
    for label, b in (("1h", b1), ("4h", resample(b1, "4H")), ("12h", resample(b1, "12H"))):
        r = calc(list(b.o), list(b.h), list(b.l), list(b.c), list(b.v))
        report[label] = evaluate_v2(b, b1, r, fund)
    dst = paths.reports / "wl_oscillator_v2.json"
    dst.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    return report


def run_crosscheck(paths, cfg) -> dict:
    """Cross-check (pre-registered 2026-10-13 after v2): the only positive v2 results were diamonds on BTC
    4h (20 trades) and 12h (8), too few to judge. Same rules, unchanged, on ETH 4h and 12h (2 more tests,
    21 in total). The proxy archive holds only BTC and ETH."""
    from ..cli import _universe_bars
    from ..data.proxy import funding_series
    from ..data.store import MarketView
    u, _ = _universe_bars(paths, cfg, "1h", "proxy")
    b1 = u["ETH_USDT"][0]
    fund = funding_series(MarketView(paths.proxy_market).conn, "ETH_USDT")
    report = {"rules": "wl-oscillator diamond cross-check on ETH (pre-registered 2026-10-13)", "tests_total": TESTS_ALL + 2}
    for label, b in (("4h", resample(b1, "4H")), ("12h", resample(b1, "12H"))):
        r = calc(list(b.o), list(b.h), list(b.l), list(b.c), list(b.v))
        tr = simulate_v2(b, b1, r, "diamond", fund)
        report[label] = {"net": metrics.summarize(tr), "gross_bps": metrics.summarize(tr, "gross_bps")["expectancy_bps"],
                         "avg_r": sum(t["r_multiple"] for t in tr) / len(tr) if tr else None,
                         "bootstrap_lower_bps": metrics.block_bootstrap_lower(tr, 0.05 / (TESTS_ALL + 2)) if len(tr) > 1 else None}
    dst = paths.reports / "wl_oscillator_eth_crosscheck.json"
    dst.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    return report


def run(paths, cfg) -> dict:
    from ..cli import _universe_bars
    from ..data.proxy import funding_series
    from ..data.store import MarketView
    u, _ = _universe_bars(paths, cfg, "1h", "proxy")
    b1 = u["BTC_USDT"][0]
    fund = funding_series(MarketView(paths.proxy_market).conn, "BTC_USDT")
    report = {"rules": RULES, "data": {"bars_1h": len(b1), "from": b1.t[0], "to": b1.t[-1]}}
    for label, b in (("1h", b1), ("4h", resample(b1, "4H"))):
        r = calc(list(b.o), list(b.h), list(b.l), list(b.c), list(b.v))
        report[label] = evaluate(b, r, fund)
    dst = paths.reports / "wl_oscillator_v1.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    return report
