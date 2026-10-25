"""Owner grid bots vs daily support/resistance and confluence levels (CLO-128 follow-up, 2026-10-25 17:00 SAST).
Descriptive only: read-only, no network, no orders. Rules fixed BEFORE running (owner_rules_v1.md definitions, our own code):
- Daily bars built from hourly BTC_USDT klines (var/market.db, then var/proxy_market.db), UTC days, only days complete BEFORE
  the bot's start (point-in-time). Fractal pivots n=5 (confirmed 5 days late), lookback 180 days.
- Level types: SR (cluster of >=3 pivots within 0.5*ATR14, centre = mean), AVWAP_H / AVWAP_L (volume-weighted typical price
  from the last confirmed swing high / low to the start), EMA50, EMA200 (daily close), FIB (0.5 and 0.618 of last swing
  low<->high), counted as one type.
- Confluence at a price = >=2 DISTINCT level types within 0.5*ATR14 of it. A bot's range edge(s) (bottom, top) are tested;
  bot is "confluence" if its entry-side edge is at confluence (long: bottom, short: top, neutral: either edge).
- Liquidation: the first non-zero estimateLiquidationPriceDown/Up snapshot of the bot; distance to the nearest SR level beyond
  the edge-side, in ATR; "beyond support" = liquidation below the nearest SR support under the bottom (long/neutral) or above
  the nearest SR resistance over the top (short).
- Outcome: realized profit (fallback total_pnl). Compare confluence vs not: n, win rate, median, mean, sum, permutation p
  (seed 12801, 20,000, two-sided on mean difference). One pair, overlapping bots: every p is descriptive, not a pass/fail gate."""
from __future__ import annotations

import json
import random
import sqlite3
from pathlib import Path

from .owner_grid_attrib import build

DAY = 86_400_000
TOL = 0.5


def hourly(paths):
    seen = {}
    for p in paths:
        if not Path(p).exists():
            continue
        c = sqlite3.connect(f"file:{Path(p).as_posix()}?mode=ro", uri=True)
        for t, h, l, cl, v in c.execute("SELECT open_time,high,low,close,volume FROM klines WHERE symbol='BTC_USDT' "
                                        "AND interval='60M' ORDER BY open_time"):
            seen.setdefault(int(t), (float(h), float(l), float(cl), float(v)))
        c.close()
    return sorted(seen.items())


def daily(hr):
    d = {}
    for t, (h, l, c, v) in hr:
        k = t // DAY
        if k not in d:
            d[k] = [h, l, c, v, 0]
        else:
            d[k][0] = max(d[k][0], h)
            d[k][1] = min(d[k][1], l)
            d[k][2] = c
            d[k][3] += v
        d[k][4] += 1
    return {k: v for k, v in d.items() if v[4] >= 23}


def ema(xs, n):
    a = 2 / (n + 1)
    e = xs[0]
    for x in xs[1:]:
        e = a * x + (1 - a) * e
    return e


def levels(days, hr, start_ms):
    k0 = start_ms // DAY
    ks = [k for k in sorted(days) if k < k0][-400:]
    if len(ks) < 60:
        return None
    H = [days[k][0] for k in ks]
    L = [days[k][1] for k in ks]
    C = [days[k][2] for k in ks]
    tr = [max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1])) for i in range(1, len(ks))]
    atr = sum(tr[-14:]) / 14
    n = 5
    piv = []                                    # (idx, price, 'H'|'L'), confirmed n bars later
    for i in range(max(n, len(ks) - 180), len(ks) - n):
        if H[i] == max(H[i - n:i + n + 1]):
            piv.append((i, H[i], "H"))
        if L[i] == min(L[i - n:i + n + 1]):
            piv.append((i, L[i], "L"))
    sr, grp = [], []
    for p in sorted(p[1] for p in piv):
        if grp and p - grp[-1] > TOL * atr:
            if len(grp) >= 3:
                sr.append(sum(grp) / len(grp))
            grp = []
        grp.append(p)
    if len(grp) >= 3:
        sr.append(sum(grp) / len(grp))
    lv = {"SR": sr, "EMA50": [ema(C[-150:], 50)], "EMA200": [ema(C, 200)] if len(C) >= 200 else []}
    sh = [p for p in piv if p[2] == "H"]
    sl = [p for p in piv if p[2] == "L"]

    def avwap(i):
        t0 = ks[i] * DAY
        num = den = 0.0
        for t, (h, l, c, v) in hr:
            if t0 <= t < start_ms:
                num += (h + l + c) / 3 * v
                den += v
        return num / den if den else None
    if sh:
        lv["AVWAP_H"] = [avwap(sh[-1][0])]
    if sl:
        lv["AVWAP_L"] = [avwap(sl[-1][0])]
    if sh and sl:
        hi, lo = sh[-1][1], sl[-1][1]
        lv["FIB"] = [hi - r * (hi - lo) for r in (0.5, 0.618)]
    return {"atr": atr, "lv": {k: [x for x in v if x] for k, v in lv.items()}}


def conf_types(price, L):
    return sorted(k for k, v in L["lv"].items() if any(abs(price - x) <= TOL * L["atr"] for x in v))


def liq(snaps, oid):
    for r in snaps.get(oid, []):
        for k in ("estimateLiquidationPriceDown", "estimateLiquidationPriceUp"):
            v = float(r.get(k) or 0)
            if v > 0:
                return k[len("estimateLiquidationPrice"):].lower(), v
    return None, None


def perm(a, b, n=20000, seed=12801):
    if len(a) < 3 or len(b) < 3:
        return None
    rng = random.Random(seed)
    allv = a + b
    d0 = abs(sum(a) / len(a) - sum(b) / len(b))
    hit = 0
    for _ in range(n):
        rng.shuffle(allv)
        x, y = allv[:len(a)], allv[len(a):]
        hit += abs(sum(x) / len(x) - sum(y) / len(y)) >= d0
    return (hit + 1) / (n + 1)


def stats(v):
    if not v:
        return {"n": 0}
    s = sorted(v)
    return {"n": len(v), "win": sum(x > 0 for x in v) / len(v), "median": s[len(s) // 2], "mean": sum(v) / len(v),
            "sum": sum(v)}


def compare(ok, key):
    y = [o["pnl"] for o in ok if o[key]]
    n = [o["pnl"] for o in ok if not o[key]]
    return {"yes": stats(y), "no": stats(n), "perm_p": perm(list(y), list(n))}


def main():
    root = Path(__file__).resolve().parents[2]
    rows = build(root)
    hr = hourly([root / "var" / "market.db", root / "var" / "proxy_market.db"])
    days = daily(hr)
    c = sqlite3.connect(f"file:{(root / 'var' / 'account.db').as_posix()}?mode=ro", uri=True)
    snaps = {}
    for oid, raw in c.execute("SELECT bu_order_id, raw FROM bots WHERE bu_order_id IS NOT NULL AND raw IS NOT NULL ORDER BY at"):
        snaps.setdefault(oid, []).append(json.loads(raw)["summary"]["buOrderData"])
    c.close()
    out = []
    for b in rows:
        L = levels(days, hr, b["start"])
        o = {"id": b["id"], "dir": b["dirsign"], "bottom": b["bottom"], "top": b["top"],
             "pnl": b["realized"] if b["realized"] is not None else b["total_pnl"]}
        if L:
            a = L["atr"]
            o["atr"] = a
            o["bottom_types"] = conf_types(b["bottom"], L)
            o["top_types"] = conf_types(b["top"], L)
            cb, ct = len(o["bottom_types"]) >= 2, len(o["top_types"]) >= 2
            o["confluence"] = cb if b["dirsign"] > 0 else ct if b["dirsign"] < 0 else (cb or ct)
            o["both_edges"] = cb and ct
            side, lp = liq(snaps, b["id"])
            o["liq_side"], o["liq_price"] = side, lp
            sr = L["lv"]["SR"]
            if lp:
                if side == "down":
                    sup = [x for x in sr if x < b["bottom"]]
                    o["nearest_sr"] = max(sup) if sup else None
                    o["liq_beyond_sr"] = bool(sup) and lp < max(sup)
                    o["liq_dist_atr_from_edge"] = (b["bottom"] - lp) / a
                else:
                    res_ = [x for x in sr if x > b["top"]]
                    o["nearest_sr"] = min(res_) if res_ else None
                    o["liq_beyond_sr"] = bool(res_) and lp > min(res_)
                    o["liq_dist_atr_from_edge"] = (lp - b["top"]) / a
        out.append(o)
    ok = [o for o in out if "confluence" in o]
    lq = [o for o in ok if o.get("liq_price") and o.get("nearest_sr") is not None]
    res = {"n_bots": len(out), "n_with_levels": len(ok), "n_with_liq": sum(1 for o in ok if o.get("liq_price")),
           "n_liq_and_sr": len(lq),
           "edge_confluence": compare(ok, "confluence"), "both_edges": compare(ok, "both_edges"),
           "liq_beyond_nearest_sr": compare(lq, "liq_beyond_sr"), "bots": out}
    p = root / "var" / "reports" / "owner_grid_levels_2026-10-25.json"
    p.write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps({k: v for k, v in res.items() if k != "bots"}, indent=1, default=str))


if __name__ == "__main__":
    main()
