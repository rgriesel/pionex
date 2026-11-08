"""CLO-248 (parent CLO-246b, own-edge tournament, Quant B): H5 and H6, one pre-registered trial each.

PRE-REGISTERED 2026-11-07 23:40 SAST (UTC+02:00), committed before the run; each hypothesis run ONCE.
Research only: no order path. Binance hourly spot is PROXY for Pionex perp prices. A backtest only
screens out the bad; a PASS means "eligible for a $5-10 live micro-experiment", never proof of profit.

H4 (weekend / CME gap) is NOT run: the long-only gap fill was tested as CLO-60 (FAIL, 88 trades, mean
-0.027%) and CME crypto futures trade 24/7 since 2026-05-29, so no gap exists to fade or fill. See STRATEGY_LOG.

Data: hourly bars (60M) from var/alpha/early_1h.db (2019-01..2023-03) spliced with var/proxy_market.db
(BTC, ETH) or var/alpha/alts_1h.db (alts) (2023-04..2026-10); duplicates keep the earlier db. Missing
hours stay missing; a signal or trade touching a missing bar in its window is skipped and counted.
Eras: full = all bars; final = entries from 2023-04-01 00:00 UTC. No parameter is fitted on either era.

Costs per side 8 bps (6 taker + 2 slippage) on every filled rung/leg, stress 2x and 3x; funding charge
1 bp per 8 h held on the filled notional (both directions, conservative). Return unit: bps of the MAXIMUM
notional (unfilled ladder rungs count as zero return but still reserve notional). 1x leverage; leverage
would only scale returns and risk. Within one bar the order is: rung fills, then stop, then take profit
(worst case first); stops/TPs fill at their level, time exit at the next open after the deadline.

H5 volatility-regime breakout, ATR-sized futures ladder (BTC_USDT, ETH_USDT, long and short):
  range24[i] = max high - min low over bars i-23..i. ATRd[i] = mean of range24 at i, i-24, ... i-312 (14
  samples). Short-term range S[i] = mean of range24 at i, i-24, i-48. Compression: S[i-1]/ATRd[i-1] <= 0.70.
  Signal at closed bar i: compression and close[i] > max high of bars i-72..i-1 (long) or
  close[i] < min low of bars i-72..i-1 (short). Entry rung 1 (1/3) at open[i+1]; rungs 2, 3 (1/3 each) are
  stop orders at entry +0.25 ATR and +0.50 ATR in the trade direction, filled on touch. Hard stop at
  entry1 -0.75 ATR (all filled rungs), take profit at entry1 +1.5 ATR, time exit 96 bars after entry.
  ATR = ATRd[i] frozen at signal. One position per symbol; later signals while in a position are ignored.
H6 BTC/ETH lead-lag (alts ADA AVAX BNB DOGE LINK LTC SOL XRP, long and short):
  Lr[i] = mean of the 4-bar log returns of BTC and ETH ending at closed bar i, both with the same sign.
  z = Lr[i] / std(Lr[i-720..i-1]) with |z| >= 2.0. The alt lags if s*r4_alt[i] < 0.5*s*Lr[i], s = sign(Lr).
  Enter alt at open[i+1] in direction s. Gap = s*Lr - s*r4_alt (>0). Take profit at entry*exp(s*0.5*Gap).
  Hard stop at entry*exp(-s*1.5*sd1h_alt*sqrt(8)), sd1h = std of the alt's 1-bar log returns over the
  prior 168 bars. Time exit 8 bars after entry. One position per alt.
Diagnostic only (not a new test): same signals with the side flipped and identical stop/TP distances.

PASS gates (the screen for a micro-experiment), ALL required:
  n >= 100 trades in full and in final; mean net > 0 in full and in final; final profit factor >= 1.2;
  final mean net > 0 at 2x costs; final mean without the best trade > 0; final one-sided 95% lower bound on
  mean net >0 (metrics.block_bootstrap_lower, 3-day blocks, alpha 0.05, fixed seed). Also report the
  Bonferroni bound at alpha 0.05/ntrials (not a gate for the screen, required before any promotion).
  n < 100 in final -> INSUFFICIENT; otherwise FAIL. Edge must also exceed the flipped-side diagnostic by
  being positive while it is not (reported, not gated).
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pionex_lab.research.metrics import block_bootstrap_lower, summarize  # noqa: E402

H = 3_600_000
FINAL_MS = 1_680_307_200_000  # 2023-04-01 00:00 UTC
SIDE_BPS = 8.0
FUND_BPS_8H = 1.0
LEADS = ("BTC_USDT", "ETH_USDT")
ALTS = ("ADA_USDT", "AVAX_USDT", "BNB_USDT", "DOGE_USDT", "LINK_USDT", "LTC_USDT", "SOL_USDT", "XRP_USDT")


def load(symbol, later_db):
    """Hourly bars on a contiguous grid: returns (t0, [ (o,h,l,c) | None ])."""
    rows = {}
    for db in (ROOT / "var/alpha/early_1h.db", ROOT / later_db):
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        for t, o, h, l, c in con.execute(
                "SELECT open_time,open,high,low,close FROM klines WHERE symbol=? AND interval='60M' ORDER BY open_time",
                (symbol,)):
            rows.setdefault(t, (float(o), float(h), float(l), float(c)))
        con.close()
    t0, t1 = min(rows), max(rows)
    return t0, [rows.get(t0 + i * H) for i in range(int((t1 - t0) // H) + 1)]


def align(series):
    """Put several (t0, bars) series on one common grid starting at the latest t0."""
    t0 = max(s[0] for s in series.values())
    end = max(s[0] + (len(s[1]) - 1) * H for s in series.values())
    n = int((end - t0) // H) + 1
    out = {}
    for k, (s0, bars) in series.items():
        off = int((t0 - s0) // H)
        seg = bars[off:off + n]
        out[k] = seg + [None] * (n - len(seg))
    return t0, out


def _ok(bars, a, b):
    return a >= 0 and all(bars[j] is not None for j in range(a, b + 1))


def trade_cost_bps(weights_filled, hours, mult):
    return sum(w * (2 * SIDE_BPS * mult + FUND_BPS_8H * hours / 8.0) for w in weights_filled)


def run_path(bars, t0, i0, side, entry, stop, tp, rungs, deadline, mult):
    """Walk bars from index i0 (entry bar, entry at its open). rungs: list of (level, weight) beyond rung 1.

    Returns trade dict or None when a bar is missing. side=+1 long, -1 short.
    """
    filled = [(entry, 1.0 / 3.0)]
    pending = list(rungs)
    j = i0
    while True:
        b = bars[j] if j < len(bars) else None
        if b is None:
            return None
        o, h, l, c = b
        for lv, w in list(pending):
            if (side > 0 and h >= lv) or (side < 0 and l <= lv):
                filled.append((lv, w))
                pending.remove((lv, w))
        hit_stop = (side > 0 and l <= stop) or (side < 0 and h >= stop)
        hit_tp = (side > 0 and h >= tp) or (side < 0 and l <= tp)
        if hit_stop:
            px, reason = stop, "stop"
        elif hit_tp:
            px, reason = tp, "tp"
        elif j >= deadline:
            nb = bars[j + 1] if j + 1 < len(bars) else None
            if nb is None:
                return None
            px, reason, j = nb[0], "time", j + 1
        else:
            j += 1
            continue
        break
    hours = j - i0 + 1
    gross = sum(w * side * (px / e - 1.0) * 1e4 for e, w in filled)
    net = gross - trade_cost_bps([w for _, w in filled], hours, mult)
    return dict(entry_time=t0 + i0 * H, exit_time=t0 + j * H, side=side, rungs=len(filled), exit_reason=reason,
                gross_bps=gross, net_bps=net, hours=hours)


def h5_signals(bars):
    """Yield (i, side, atr) for closed bar i that triggers a compression breakout."""
    n = len(bars)
    rng = [None] * n
    for i in range(23, n):
        if _ok(bars, i - 23, i):
            rng[i] = max(bars[k][1] for k in range(i - 23, i + 1)) - min(bars[k][2] for k in range(i - 23, i + 1))
    for i in range(24 * 13 + 72, n - 2):
        samp = [rng[i - 24 * k] for k in range(14)]
        prev3 = [rng[i - 1 - 24 * k] for k in range(3)]
        prev14 = [rng[i - 1 - 24 * k] for k in range(14)]
        if None in samp or None in prev3 or None in prev14 or not _ok(bars, i - 72, i):
            continue
        if (sum(prev3) / 3) / (sum(prev14) / 14) > 0.70:
            continue
        hi = max(bars[k][1] for k in range(i - 72, i))
        lo = min(bars[k][2] for k in range(i - 72, i))
        c = bars[i][3]
        side = 1 if c > hi else -1 if c < lo else 0
        if side:
            yield i, side, sum(samp) / 14


def h5(bars, t0, mult=1.0, flip=False):
    trades, skipped, busy = [], 0, -1
    n = len(bars)
    for i, side, atr in h5_signals(bars):
        if i + 1 <= busy or bars[i + 1] is None:
            continue
        s = -side if flip else side
        e = bars[i + 1][0]
        rungs = [(e + s * 0.25 * atr, 1 / 3), (e + s * 0.50 * atr, 1 / 3)]
        tr = run_path(bars, t0, i + 1, s, e, e - s * 0.75 * atr, e + s * 1.5 * atr, rungs, i + 1 + 96, mult)
        if tr is None:
            skipped += 1
            continue
        tr["signal_time"] = t0 + i * H
        tr["symbol"] = None
        busy = int((tr["exit_time"] - t0) // H)
        trades.append(tr)
    return trades, skipped


def lead_stats(lead):
    """Per closed bar: (Lr, z) for the BTC/ETH lead, z against the prior 720 bars (>=360 valid)."""
    n = len(lead[0])
    lr = [None] * n
    for i in range(4, n):
        if all(_ok(b, i - 4, i) for b in lead):
            r = [math.log(b[i][3] / b[i - 4][3]) for b in lead]
            if r[0] * r[1] > 0:
                lr[i] = (r[0] + r[1]) / 2
    z = [None] * n
    s = s2 = 0.0
    cnt = 0
    for i in range(n):
        if i >= 1 and lr[i - 1] is not None:
            s += lr[i - 1]
            s2 += lr[i - 1] ** 2
            cnt += 1
        if i - 721 >= 0 and lr[i - 721] is not None:
            s -= lr[i - 721]
            s2 -= lr[i - 721] ** 2
            cnt -= 1
        if lr[i] is not None and cnt >= 360:
            var = s2 / cnt - (s / cnt) ** 2
            if var > 1e-18:
                z[i] = lr[i] / math.sqrt(var)
    return lr, z


def h6(stats, alt, t0, mult=1.0, flip=False):
    """stats: lead_stats() output; alt: bar list on the same grid."""
    lr, z = stats
    n = len(alt)
    trades, skipped, busy = [], 0, -1
    for i in range(724, n - 2):
        if z[i] is None or abs(z[i]) < 2.0 or i + 1 <= busy or alt[i + 1] is None or not _ok(alt, i - 168, i):
            continue
        s = 1 if lr[i] > 0 else -1
        ra = math.log(alt[i][3] / alt[i - 4][3])
        if not s * ra < 0.5 * s * lr[i]:
            continue
        gap = s * lr[i] - s * ra
        rets = [math.log(alt[k][3] / alt[k - 1][3]) for k in range(i - 167, i + 1)]
        mu = sum(rets) / len(rets)
        sd1 = math.sqrt(sum((x - mu) ** 2 for x in rets) / len(rets))
        e = alt[i + 1][0]
        d = -s if flip else s
        tp = e * math.exp(d * 0.5 * gap)
        stop = e * math.exp(-d * 1.5 * sd1 * math.sqrt(8))
        tr = run_path(alt, t0, i + 1, d, e, stop, tp, [], i + 1 + 8, mult)
        if tr is None:
            skipped += 1
            continue
        for k in ("gross_bps", "net_bps"):  # run_path weights rung 1 at 1/3; single-rung trade uses full notional
            tr[k] *= 3.0
        tr["signal_time"] = t0 + i * H
        busy = int((tr["exit_time"] - t0) // H)
        trades.append(tr)
    return trades, skipped

def evaluate(trades, ntrials):
    full = trades
    final = [t for t in trades if t["entry_time"] >= FINAL_MS]
    out = {}
    for name, ts in (("full", full), ("final", final)):
        out[name] = summarize(ts) if ts else {"n": 0}
    out["final_boot_lb95"] = block_bootstrap_lower(final, 0.05) if len(final) > 5 else None
    out["final_boot_lb_bonferroni"] = block_bootstrap_lower(final, 0.05 / ntrials) if len(final) > 5 else None
    return out, final


def verdict(res, final_2x):
    f, fi = res["full"], res["final"]
    if fi["n"] < 100 or f["n"] < 100:
        return "INSUFFICIENT", {}
    gates = dict(
        full_mean_gt0=f["expectancy_bps"] > 0, final_mean_gt0=fi["expectancy_bps"] > 0,
        final_pf_ge_1_2=(fi["profit_factor"] or 0) >= 1.2,
        final_2x_mean_gt0=final_2x["expectancy_bps"] is not None and final_2x["expectancy_bps"] > 0,
        final_ex_best_gt0=(fi["total_minus_best_bps"] / (fi["n"] - 1)) > 0,
        final_boot_lb95_gt0=res["final_boot_lb95"] is not None and res["final_boot_lb95"] > 0)
    return ("PASS" if all(gates.values()) else "FAIL"), gates


def run_h(name, ntrials):
    if name == "H5":
        series = {s: load(s, "var/proxy_market.db") for s in LEADS}
        t0, g = align(series)
        fn = lambda mult, flip: {s: h5(g[s], t0, mult, flip) for s in LEADS}
    else:
        series = {s: load(s, "var/proxy_market.db") for s in LEADS}
        series.update({s: load(s, "var/alpha/alts_1h.db") for s in ALTS})
        t0, g = align(series)
        st = lead_stats([g[s] for s in LEADS])
        fn = lambda mult, flip: {s: h6(st, g[s], t0, mult, flip) for s in ALTS}
    runs, skipped = {}, {}
    for key, (mult, flip) in dict(base=(1, False), x2=(2, False), x3=(3, False), flipped=(1, True)).items():
        per = fn(mult, flip)
        runs[key] = [dict(t, symbol=s) for s, (ts, _) in per.items() for t in ts]
        skipped[key] = {s: sk for s, (_, sk) in per.items()}
    base = sorted(runs["base"], key=lambda t: t["exit_time"])
    res, final = evaluate(base, ntrials)
    fin = lambda k: summarize([t for t in runs[k] if t["entry_time"] >= FINAL_MS])
    v, gates = verdict(res, fin("x2"))
    res.update(final_2x=fin("x2"), final_3x=fin("x3"), final_flipped=fin("flipped"),
               full_flipped=summarize(runs["flipped"]) if runs["flipped"] else {"n": 0},
               by_symbol={s: round(sum(t["net_bps"] for t in base if t["symbol"] == s), 1) for s in sorted(set(t["symbol"] for t in base))},
               exit_reasons={r: sum(1 for t in base if t["exit_reason"] == r) for r in ("stop", "tp", "time")},
               gross_mean_final=(sum(t["gross_bps"] for t in final) / len(final)) if final else None)
    years = {}
    for t in base:
        y = datetime.fromtimestamp(t["entry_time"] / 1000, UTC).year
        years.setdefault(y, []).append(t["net_bps"])
    res["by_year"] = {str(y): dict(n=len(v_), mean=round(sum(v_) / len(v_), 1)) for y, v_ in sorted(years.items())}
    return dict(verdict=v, gates=gates, results=res, skipped=skipped)


def main(name):
    out = ROOT / f"var/reports/own_edge_b_clo248_{name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as f:  # sentinel: re-execution forbidden
        json.dump(dict(state="started", at=datetime.now(UTC).isoformat()), f)
    con = sqlite3.connect(ROOT / "var/trials.db")
    with con:
        con.execute("INSERT INTO trials(ts,source,ref,strategy_id,params,data_span,result,weight) VALUES(?,?,?,?,?,?,?,1)",
                    (int(datetime.now(UTC).timestamp() * 1000), "own_edge_b", f"CLO-248:{name}:v1",
                     f"own_edge_b_clo248_{name}", json.dumps(dict(hypothesis=name)),
                     "2019-01..2026-10 hourly Binance PROXY", "STARTED"))
    ntrials = max(266, con.execute("SELECT SUM(weight) FROM trials").fetchone()[0])
    r = run_h(name, ntrials)
    report = dict(state="complete", at=datetime.now(UTC).isoformat(), hypothesis=name, mode="RESEARCH PROXY",
                  ntrials=ntrials, code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), **r)
    out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=1, default=str))


if __name__ == "__main__":
    main(sys.argv[1])
