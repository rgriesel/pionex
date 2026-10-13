"""Factor research for BTC, the way a desk screens signals. Pre-registered 2026-10-13 23:00 SAST.

Decision points: every 4h close of Binance BTCUSDT spot (PROXY) from 2023-04 to now. Each factor uses
only data available at that moment (hourly series from closed candles; daily series - Fear & Greed,
stablecoins, FRED macro - only from the next UTC day on).
Targets: BTC return over the next 4h, 24h and 72h.
Step 1 (screen): Spearman IC of every factor with every target, overall and per calendar year;
  t-statistic with the effective sample size (overlap removed). A factor 'holds' only if
  |t| > 3.2 (Bonferroni for ~30 factors x 3 horizons) AND its IC has the same sign in every year.
Step 2 (combine): walk-forward ridge regression on all factors (expanding window, refit every 30
  days, first fit after 365 days, factors z-scored on the training window, missing -> 0) predicting
  the 24h return. Trade when flat: long if prediction > thr, short if < -thr, hold 24h; 0.05% fee +
  0.01% slippage per side; thr fixed in advance at 0 and at 0.2%. Also a long-only version.
Research only: no orders.
"""
from __future__ import annotations

import bisect
import json
import math

H, D = 3_600_000, 86_400_000
NAN = float("nan")
COST = 2 * (0.0005 + 0.0001)


def _fin(x):
    return x is not None and x == x and abs(x) != math.inf


class Series:
    """Sorted (t, v) with 'last value at or before t' lookups."""

    def __init__(self, pairs, avail_lag=0):
        pairs = sorted((t + avail_lag, v) for t, v in pairs if _fin(v))
        self.t = [p[0] for p in pairs]
        self.v = [p[1] for p in pairs]

    def at(self, t, max_age=None):
        k = bisect.bisect_right(self.t, t) - 1
        if k < 0 or (max_age is not None and t - self.t[k] > max_age):
            return NAN
        return self.v[k]

    def mean_between(self, a, b):
        i, j = bisect.bisect_right(self.t, a), bisect.bisect_right(self.t, b)
        xs = self.v[i:j]
        return sum(xs) / len(xs) if xs else NAN


def build(paths):
    from ..data import altdata
    from ..data.proxy import funding_series
    from ..data.store import MarketView
    from ..strategies.indicators import ema
    view = MarketView(paths.proxy_market)
    b = view.bars("BTC_USDT", "60M")
    close_at = {t + H: c for t, c in zip(b.t, b.c)}                      # price known at each hour's close
    hours = sorted(close_at)
    px = Series(close_at.items())
    hret = {}
    for k in range(1, len(hours)):
        if hours[k] - hours[k - 1] == H:
            hret[hours[k]] = math.log(close_at[hours[k]] / close_at[hours[k - 1]])
    hr = Series(hret.items())
    daily = view.bars("BTC_USDT", "1D")
    e50 = ema(list(daily.c), 50)
    ema_d = Series([(t + D, v) for t, v in zip(daily.t, e50)])         # EMA of a day known after it closes
    fund = Series(funding_series(view.conn, "BTC_USDT"))
    from ..data.proxy import metrics_series
    met = metrics_series(view.conn, "BTC_USDT")
    mets = {f: Series(met.get(f, {}).items()) for f in ("oi_usd", "ls_count", "top_ls_sum", "taker_ls")}
    alt_db = paths.root / "alpha" / "alt.db"
    alt = {}
    if alt_db.exists():
        for name, lag in (("fng", D), ("stables", D), ("fred:DTWEXBGS", D), ("fred:DGS10", D), ("fred:VIXCLS", D),
                          ("fred:NASDAQCOM", D), ("dvol_1h", H)):
            alt[name] = Series(altdata.series(alt_db, name), avail_lag=lag)
        cb = dict(altdata.series(alt_db, "cb_1h"))
        prem = {t + H: cb[t] / close_at[t + H] - 1 for t in cb if t + H in close_at}
        alt["cb_prem"] = Series(prem.items())
    depth = None
    dpath = paths.root / "orderbook" / "depth.db"
    if dpath.exists():
        import sqlite3
        con = sqlite3.connect(dpath)
        rows = con.execute("SELECT t, pct, depth FROM depth5m WHERE symbol='BTCUSDT' AND pct IN (-1.0, 1.0, -5.0, 5.0)").fetchall()
        by = {}
        for t, p, d in rows:
            by.setdefault(t + 300_000, {})[p] = d                            # known at the bucket's close
        depth = {k: Series([(t, (v[-k] - v[k]) / (v[-k] + v[k])) for t, v in by.items() if -k in v and k in v and v[-k] + v[k] > 0])
                 for k in (1.0, 5.0)}

    def rv(t, hrs):
        i, j = bisect.bisect_right(hr.t, t - hrs * H), bisect.bisect_right(hr.t, t)
        xs = hr.v[i:j]
        if len(xs) < hrs * 0.8:
            return NAN
        m = sum(xs) / len(xs)
        return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs) * 24 * 365)

    def chg(s, t, back, rel=True):
        a, b0 = s.at(t), s.at(t - back)
        if not (_fin(a) and _fin(b0)) or (rel and b0 == 0):
            return NAN
        return a / b0 - 1 if rel else a - b0

    start = hours[0] + 31 * D
    grid = [t for t in hours if t >= start and t % (4 * H) == 0]
    rows = []
    for T in grid:
        p = close_at[T]
        f = {}
        f["mom_4h"] = math.log(p / px.at(T - 4 * H)) if _fin(px.at(T - 4 * H)) else NAN
        f["mom_24h"] = math.log(p / px.at(T - D)) if _fin(px.at(T - D)) else NAN
        f["mom_7d"] = math.log(p / px.at(T - 7 * D)) if _fin(px.at(T - 7 * D)) else NAN
        f["mom_30d"] = math.log(p / px.at(T - 30 * D)) if _fin(px.at(T - 30 * D)) else NAN
        ed = ema_d.at(T)
        f["dist_ema50d"] = p / ed - 1 if _fin(ed) else NAN
        f["rvol_7d"] = rv(T, 168)
        fr = fund.at(T, max_age=9 * H)
        f["funding"] = fr
        k = bisect.bisect_right(fund.t, T)
        win = fund.v[max(0, k - 90):k]
        if len(win) > 30 and _fin(fr):
            m = sum(win) / len(win)
            sd = math.sqrt(sum((x - m) ** 2 for x in win) / len(win))
            f["funding_z"] = (fr - m) / sd if sd > 0 else NAN
        else:
            f["funding_z"] = NAN
        f["oi_chg_24h"] = chg(mets["oi_usd"], T, D)
        f["ls_count"] = mets["ls_count"].mean_between(T - 4 * H, T)
        f["top_ls_sum"] = mets["top_ls_sum"].mean_between(T - 4 * H, T)
        f["taker_ls_4h"] = mets["taker_ls"].mean_between(T - 4 * H, T)
        f["taker_ls_24h"] = mets["taker_ls"].mean_between(T - D, T)
        if alt:
            f["fng"] = alt["fng"].at(T, max_age=3 * D)
            f["fng_chg_7d"] = chg(alt["fng"], T, 7 * D, rel=False)
            f["stables_7d"] = chg(alt["stables"], T, 7 * D)
            f["stables_30d"] = chg(alt["stables"], T, 30 * D)
            f["dxy_5d"] = chg(alt["fred:DTWEXBGS"], T, 7 * D)
            f["us10y_5d"] = chg(alt["fred:DGS10"], T, 7 * D, rel=False)
            f["vix"] = alt["fred:VIXCLS"].at(T, max_age=5 * D)
            f["vix_5d"] = chg(alt["fred:VIXCLS"], T, 7 * D, rel=False)
            f["ndx_1d"] = chg(alt["fred:NASDAQCOM"], T, 3 * D)
            f["ndx_5d"] = chg(alt["fred:NASDAQCOM"], T, 7 * D)
            dv = alt["dvol_1h"].at(T, max_age=3 * H)
            f["dvol"] = dv
            f["dvol_chg_24h"] = chg(alt["dvol_1h"], T, D, rel=False)
            r30 = rv(T, 720)
            f["vrp"] = dv / 100 - r30 if _fin(dv) and _fin(r30) else NAN
            f["cb_prem_24h"] = alt["cb_prem"].mean_between(T - D, T)
            f["cb_prem_chg"] = (f["cb_prem_24h"] - alt["cb_prem"].mean_between(T - 2 * D, T - D)
                                if _fin(f["cb_prem_24h"]) else NAN)
        if depth:
            f["book_imb_1pct"] = depth[1.0].at(T, max_age=15 * 60_000)
            f["book_imb_5pct"] = depth[5.0].at(T, max_age=15 * 60_000)
            f["book_imb_1pct_4h"] = depth[1.0].mean_between(T - 4 * H, T)
        y = {}
        for h, n in (("4h", 4 * H), ("24h", D), ("72h", 3 * D)):
            q = close_at.get(T + n)
            y[h] = q / p - 1 if q else NAN
        rows.append((T, f, y))
    return rows


def _rank(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2
        i = j + 1
    return r


def spearman(a, b):
    if len(a) < 20:
        return NAN
    ra, rb = _rank(a), _rank(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = math.sqrt(sum((x - ma) ** 2 for x in ra))
    vb = math.sqrt(sum((y - mb) ** 2 for y in rb))
    return cov / (va * vb) if va and vb else NAN


def screen(rows):
    from datetime import datetime, timezone
    names = sorted({k for _, f, _ in rows for k in f})
    out = []
    for h, step in (("4h", 1), ("24h", 6), ("72h", 18)):
        for name in names:
            pts = [(T, f[name], y[h]) for T, f, y in rows if _fin(f.get(name)) and _fin(y[h])]
            if len(pts) < 200:
                continue
            ic = spearman([p[1] for p in pts], [p[2] for p in pts])
            n_eff = len(pts) / step
            t = ic * math.sqrt(max(1.0, n_eff - 2)) / math.sqrt(max(1e-9, 1 - ic * ic)) if _fin(ic) else NAN
            years = {}
            for T, x, y in pts:
                years.setdefault(datetime.fromtimestamp(T / 1000, timezone.utc).year, []).append((x, y))
            yic = {yr: spearman([a for a, _ in v], [b for _, b in v]) for yr, v in sorted(years.items()) if len(v) >= 100}
            same = len(yic) >= 3 and (all(v > 0 for v in yic.values()) or all(v < 0 for v in yic.values()))
            out.append({"factor": name, "horizon": h, "n": len(pts), "ic": ic, "t": t, "years": yic,
                        "holds": bool(_fin(t) and abs(t) > 3.2 and same)})
    return out


def _solve(A, b):
    n = len(A)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[p] = M[p], M[c]
        if abs(M[c][c]) < 1e-12:
            continue
        for r in range(n):
            if r != c:
                k = M[r][c] / M[c][c]
                for j in range(c, n + 1):
                    M[r][j] -= k * M[c][j]
    return [M[i][n] / M[i][i] if abs(M[i][i]) > 1e-12 else 0.0 for i in range(n)]


MICRO = ("book_imb_1pct", "book_imb_5pct", "mom_4h", "oi_chg_24h")
MICRO_RULES = """4h combination test (pre-registered 2026-10-13 23:40 SAST, after the screen):
  A: walk-forward ridge on ALL factors predicting the 4h return; B: the same on the 4 factors that held
  in the screen (book imbalance +-1% and +-5%, last 4h return, 24h open-interest change). B's factor
  choice used the full-sample screen, so only A is clean; a live paper test is the real check.
  Trade when flat: long if prediction > thr, short if < -thr, hold 4h, 0.12% round trip; thr fixed at
  0, 0.1% and 0.2%; long/short and long-only. Out of sample from the first fit (1 year of training)."""


QUANTILE_RULES = """v2 (pre-registered 2026-10-14 00:05 SAST after v1, whose fixed thresholds never triggered because
  the ridge predictions are strongly shrunk): same walk-forward predictions; trade only when the new
  prediction is in the top (long) or bottom (short) q of the previous 90 days of predictions,
  q = 10% and 5%; hold the horizon; 0.12% round trip; long/short and long-only; 4h and 24h horizons."""


def trade_quantiles(preds, hold, q, longonly=False, window=540):
    nets, busy, hist = [], -1, []
    for T, pr, yv in preds:
        ref = sorted(hist[-window:])
        hist.append(pr)
        if len(ref) < 200 or T < busy or not _fin(yv):
            continue
        hi, lo = ref[int((1 - q) * (len(ref) - 1))], ref[int(q * (len(ref) - 1))]
        side = 1 if pr >= hi else (-1 if pr <= lo and not longonly else 0)
        if side:
            nets.append(side * yv - COST)
            busy = T + hold
    return {"n": len(nets), "mean_pct": 100 * sum(nets) / len(nets) if nets else None,
            "gross_pct": 100 * (sum(nets) / len(nets) + COST) if nets else None,
            "win": sum(x > 0 for x in nets) / len(nets) if nets else None, "total_pct": 100 * sum(nets) if nets else None}


def run_micro(paths):
    rows = build(paths)
    rep = {"rules": MICRO_RULES + "\n" + QUANTILE_RULES, "decisions": len(rows)}
    for key, only in (("A_all_factors", None), ("B_micro_factors", MICRO)):
        for horizon, hold in (("4h", 4 * H), ("24h", D)):
            c = combine(rows, horizon=horizon, hold=hold, thresholds=(0.0,), only=only)
            preds = c.pop("preds")
            c["quantile"] = {f"q{q}_{'long' if lo else 'longshort'}": trade_quantiles(preds, hold, q, lo)
                             for q in (0.10, 0.05) for lo in (False, True)}
            rep[f"{key}_{horizon}"] = c
    dst = paths.reports / "factors_micro_4h.json"
    dst.write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    return rep


def combine(rows, lam=10.0, horizon="24h", hold=D, thresholds=(0.0, 0.002), only=None):
    names = sorted({k for _, f, _ in rows for k in f if only is None or k in only})
    preds, last_fit, w, mu, sd = [], None, None, None, None
    first = rows[0][0] + 365 * D
    for idx, (T, f, y) in enumerate(rows):
        if T < first:
            continue
        if last_fit is None or T - last_fit >= 30 * D:
            train = [(ff, yy[horizon]) for TT, ff, yy in rows[:idx] if TT + D <= T and _fin(yy[horizon])]
            mu, sd = {}, {}
            for n in names:
                xs = [ff[n] for ff, _ in train if _fin(ff.get(n))]
                m = sum(xs) / len(xs) if xs else 0.0
                s = math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs)) if len(xs) > 1 else 1.0
                mu[n], sd[n] = m, (s or 1.0)
            X = [[(ff[n] - mu[n]) / sd[n] if _fin(ff.get(n)) else 0.0 for n in names] for ff, _ in train]
            Y = [yy for _, yy in train]
            ym = sum(Y) / len(Y)
            A = [[sum(r[i] * r[j] for r in X) + (lam * len(X) if i == j else 0) for j in range(len(names))] for i in range(len(names))]
            bb = [sum(r[i] * (yv - ym) for r, yv in zip(X, Y)) for i in range(len(names))]
            w = (_solve(A, bb), ym)
            last_fit = T
        x = [(f[n] - mu[n]) / sd[n] if _fin(f.get(n)) else 0.0 for n in names]
        preds.append((T, w[1] + sum(a * c for a, c in zip(w[0], x)), y[horizon]))
    res = {"weights_last_fit": dict(zip(names, w[0])) if w else {}, "oos_from": preds[0][0] if preds else None, "preds": preds}
    ic = spearman([p[1] for p in preds if _fin(p[2])], [p[2] for p in preds if _fin(p[2])])
    res["oos_ic"] = ic
    for thr in thresholds:
        for longonly in (False, True):
            nets, busy = [], -1
            for T, pr, yv in preds:
                if T < busy or not _fin(yv) or abs(pr) <= thr or (longonly and pr <= 0):
                    continue
                side = 1 if pr > 0 else -1
                nets.append(side * yv - COST)
                busy = T + hold
            key = f"thr{thr}_{'long' if longonly else 'longshort'}"
            res[key] = {"n": len(nets), "mean_pct": 100 * sum(nets) / len(nets) if nets else None,
                        "win": sum(x > 0 for x in nets) / len(nets) if nets else None,
                        "total_pct": 100 * sum(nets) if nets else None}
    return res


def run(paths):
    rows = build(paths)
    scr = screen(rows)
    comb = combine(rows)
    comb.pop("preds", None)
    rep = {"rules": "factor screen + walk-forward ridge (pre-registered 2026-10-13)", "decisions": len(rows),
           "screen": scr, "combine_24h": comb}
    dst = paths.reports / "factors_v1.json"
    dst.write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    return rep
