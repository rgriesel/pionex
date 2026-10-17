"""Mine the owner's FINISHED Pionex grid bots (CLO-46). Research only: reads var/account.db read-only (table `bots`,
the key is never touched) and local hourly BTC klines (var/market.db, then var/proxy_market.db); no network, no orders.

One row per finished bot (latest snapshot per bu_order_id; status != running):
  pair, type, start/end (ms), range_pct = (top-bottom)/start price, grids (`row`), leverage (`leverage`, else `setLeverage`),
  direction (`trend`), investment (initUsdtInvestment), duration_h, grid_profit (gridProfit), total_pnl = final equity -
  investment (futures: marginBalance, spot: quoteTotalAmount), float_pnl = total - grid, ret = total/investment,
  closed_outside (close price outside [bottom, top]).
Market during the bot's life (hourly BTC_USDT closes): rv_life (hourly log-return sd * sqrt(24), i.e. daily vol), move (net
return start->end), abs_move, path (max-min over start), range_over_vol = range_pct / (rv_life * sqrt(duration_days)) (how many
life-time sigmas the grid spans), trend_in = 168h return before the start, trend_aligned = sign(direction) * trend_in,
regime = regime.classify() on the day-before-start daily features (CLO-45 labels) when 90+ daily bars exist.
Statistics (`analyse`): Spearman rank correlation of each feature with ret and with ret per day, and a permutation p-value
(fixed seed, 20,000 shuffles, two-sided). n is small and bots overlap in time (one market): every p is descriptive, and the
firm's multiple-comparison count for this table is len(FEATURES). Nothing here is evidence of profit.
"""
from __future__ import annotations

import json
import math
import random
import sqlite3
from pathlib import Path

HOUR_MS = 3_600_000
DAY_MS = 86_400_000
FEATURES = ("range_pct", "grids", "leverage", "investment", "duration_h", "rv_life", "range_over_vol", "abs_move",
            "trend_aligned", "grids_per_range", "step_pct")
N_PERM = 20_000
SEED = 4601


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def load_bots(account_db) -> list[dict]:
    c = sqlite3.connect(f"file:{Path(account_db).as_posix()}?mode=ro", uri=True)
    try:
        rows = c.execute("SELECT bu_order_id, at, raw FROM bots WHERE bu_order_id IS NOT NULL AND raw IS NOT NULL "
                         "ORDER BY at").fetchall()
    finally:
        c.close()
    latest = {}
    for oid, at, raw in rows:
        latest[oid] = raw                                # ordered by `at`: the last snapshot wins
    out = []
    for oid, raw in latest.items():
        s = json.loads(raw)["summary"]
        if s.get("status") == "open" or s.get("status") == "running" or not s.get("closeTime"):
            continue
        b = s["buOrderData"]
        typ = s.get("buOrderType")
        pair = f'{s.get("base", "")}_{s.get("quote", "USDT")}'
        top, bot, p0 = _f(b.get("top")), _f(b.get("bottom")), (_f(b.get("initPrice")) or _f(b.get("openPrice")) or
                                                    _f(b.get("positionOpenPrice")) or None)
        inv = _f(b.get("initUsdtInvestment") or b.get("usdtInvestment"))
        final = _f(b.get("marginBalance")) if typ == "futures_grid" else _f(b.get("quoteTotalAmount"))
        grid = _f(b.get("gridProfit")) or 0.0
        if None in (top, bot, p0, inv, final) or not inv or not p0:
            continue
        lev = _f(b.get("leverage")) or _f(b.get("setLeverage")) or 1.0
        closed = _f(b.get("closedPrice"))
        grids = int(b.get("row") or 0)
        total = final - inv
        out.append({
            "id": oid, "pair": pair, "type": typ, "copy": s.get("copyType") or "",
            "start": int(s["createTime"]), "end": int(s["closeTime"]),
            "bottom": bot, "top": top, "start_price": p0, "end_price": closed,
            "range_pct": (top - bot) / p0, "grids": grids, "leverage": lev, "direction": b.get("trend") or "",
            "investment": inv, "duration_h": (int(s["closeTime"]) - int(s["createTime"])) / HOUR_MS,
            "grid_profit": grid, "total_pnl": total, "float_pnl": total - grid, "ret": total / inv,
            "closed_outside": bool(closed is not None and not (bot <= closed <= top)),
            "grids_per_range": grids / ((top - bot) / p0 * 100) if top > bot else None,
            "step_pct": ((top - bot) / p0) / grids if grids else None,
        })
    out.sort(key=lambda r: r["start"])
    return out


def load_hourly(paths: list, symbol="BTC_USDT") -> list[tuple]:
    """(open_time, close) merged over the given DBs (earlier DB wins on duplicates)."""
    seen = {}
    for p in paths:
        if not Path(p).exists():
            continue
        c = sqlite3.connect(f"file:{Path(p).as_posix()}?mode=ro", uri=True)
        try:
            for t, cl in c.execute("SELECT open_time, close FROM klines WHERE symbol=? AND interval='60M' "
                                   "ORDER BY open_time", (symbol,)):
                seen.setdefault(int(t), float(cl))
        finally:
            c.close()
    return sorted(seen.items())


def _sd(xs):
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def market_features(bar_t: list, bar_c: list, start: int, end: int, direction: str, range_pct: float) -> dict:
    """Features from hourly closes strictly inside [start, end] (life) and before `start` (entry context)."""
    from bisect import bisect_left, bisect_right
    out = dict.fromkeys(("rv_life", "move", "abs_move", "path", "range_over_vol", "trend_in", "trend_aligned"))
    i0, i1 = bisect_left(bar_t, start - HOUR_MS), bisect_right(bar_t, end)
    if i0 <= 0 or i1 > len(bar_t) or bar_t[-1] < end - HOUR_MS or i1 - i0 < 3:
        return out
    cl = bar_c[i0:i1]
    rets = [math.log(cl[k] / cl[k - 1]) for k in range(1, len(cl))]
    sd = _sd(rets)
    days = max((end - start) / DAY_MS, 1 / 24)
    out["rv_life"] = sd * math.sqrt(24) if sd is not None else None
    out["move"] = cl[-1] / cl[0] - 1
    out["abs_move"] = abs(out["move"])
    out["path"] = (max(cl) - min(cl)) / cl[0]
    if out["rv_life"]:
        out["range_over_vol"] = range_pct / (out["rv_life"] * math.sqrt(days))
    j = bisect_left(bar_t, start - 168 * HOUR_MS)
    if j >= 0 and i0 - j >= 100:
        out["trend_in"] = bar_c[i0] / bar_c[j] - 1
        sign = {"long": 1, "short": -1}.get(direction, 0)
        out["trend_aligned"] = sign * out["trend_in"]
    return out


def regime_label(bar_t: list, bar_c: list, start: int) -> str:
    """CLO-45 label from daily closes (UTC day-end bars) known before `start`; 'unknown' when < 91 daily bars."""
    from ..live import regime
    day = start // DAY_MS * DAY_MS
    closes = {}
    for t, c in zip(bar_t, bar_c):
        d = t // DAY_MS * DAY_MS
        if d < day:
            closes[d] = c                                # last hourly close of each day before the start day
    ds = [closes[k] for k in sorted(closes)]
    if len(ds) < 91:
        return "unknown"
    try:
        return regime.label_from_daily(ds) or "unknown"
    except Exception:
        return "unknown"


def build_table(account_db, kline_dbs) -> list[dict]:
    bars = load_hourly(kline_dbs)
    bt, bc = [b[0] for b in bars], [b[1] for b in bars]
    rows = load_bots(account_db)
    for r in rows:
        r.update(market_features(bt, bc, r["start"], r["end"], r["direction"], r["range_pct"]))
        r["regime"] = regime_label(bt, bc, r["start"]) if bt else "unknown"
        r["ret_per_day"] = r["ret"] / max(r["duration_h"] / 24, 1 / 24)
    return rows


# ------------------------------------------------------------------ statistics
def _ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    rk = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            rk[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return rk


def spearman(x, y):
    if len(x) < 4:
        return None
    rx, ry = _ranks(x), _ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx == 0 or syy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / math.sqrt(sxx * syy)


def perm_p(x, y, n_perm=N_PERM, seed=SEED):
    obs = spearman(x, y)
    if obs is None:
        return None, None
    rx, ry = _ranks(x), _ranks(y)                        # ranks are permutation-invariant: shuffle one, reuse the moments
    n = len(rx)
    mx, my = sum(rx) / n, sum(ry) / n
    cx = [a - mx for a in rx]
    cy = [b - my for b in ry]
    den = math.sqrt(sum(a * a for a in cx) * sum(b * b for b in cy))
    rng = random.Random(seed)
    hit = 0
    for _ in range(n_perm):
        rng.shuffle(cy)
        if abs(sum(a * b for a, b in zip(cx, cy)) / den) >= abs(obs) - 1e-12:
            hit += 1
    return obs, (hit + 1) / (n_perm + 1)


def analyse(rows: list[dict], target="ret", feats=FEATURES, n_perm=N_PERM) -> list[dict]:
    res = []
    for f in feats:
        pairs = [(r[f], r[target]) for r in rows if r.get(f) is not None and r.get(target) is not None]
        x, y = [p[0] for p in pairs], [p[1] for p in pairs]
        rho, p = perm_p(x, y, n_perm=n_perm) if len(pairs) >= 8 else (None, None)
        res.append({"feature": f, "target": target, "n": len(pairs), "rho": rho, "p": p})
    return res


def summarise(rows: list[dict]) -> dict:
    fut = [r for r in rows if r["type"] == "futures_grid"]
    rets = [r["ret"] for r in rows]
    return {"n_finished": len(rows), "n_futures": len(fut), "n_spot": len(rows) - len(fut),
            "n_winners": sum(1 for r in rows if r["total_pnl"] > 0), "n_with_market": sum(1 for r in rows if r.get("rv_life") is not None),
            "total_pnl_usdt": sum(r["total_pnl"] for r in rows), "grid_pnl_usdt": sum(r["grid_profit"] for r in rows),
            "float_pnl_usdt": sum(r["float_pnl"] for r in rows), "median_ret": sorted(rets)[len(rets) // 2] if rets else None,
            "span": [min(r["start"] for r in rows), max(r["end"] for r in rows)] if rows else None}


def main(argv=None):
    import argparse
    root = Path(__file__).resolve().parents[2]
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(root / "var" / "reports" / "owner_bots_2026-10-17.json"))
    a = ap.parse_args(argv)
    rows = build_table(root / "var" / "account.db", [root / "var" / "market.db", root / "var" / "proxy_market.db"])
    rep = {"summary": summarise(rows), "rows": rows, "ret": analyse(rows, "ret"), "ret_per_day": analyse(rows, "ret_per_day"),
           "futures_only_ret": analyse([r for r in rows if r["type"] == "futures_grid"], "ret")}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(rep, indent=1, default=str))
    print(json.dumps(rep["summary"], indent=1))
    for k in ("ret", "ret_per_day"):
        print(k)
        for r in rep[k]:
            print(f'  {r["feature"]:16s} n={r["n"]:3d} rho={r["rho"] if r["rho"] is None else round(r["rho"], 3)} p={r["p"] if r["p"] is None else round(r["p"], 4)}')
    return rep


if __name__ == "__main__":
    main()
