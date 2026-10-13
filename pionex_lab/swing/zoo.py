"""Scalping / day-trading strategy zoo: popular public strategies, long AND short, 1m-4h, walk-forward.

Pre-registered 2026-10-13 (before any result). The strategies are the common ones found in public
guides and TradingView scripts (EMA crossovers with/without VWAP, MACD + EMA200, RSI and Bollinger
mean reversion, Bollinger squeeze, Supertrend, UT Bot, Parabolic SAR, StochRSI pullbacks, Donchian /
Keltner breakouts, range trading with ADX, NY opening-range breakout, Heikin Ashi, VWAP reversion,
volume-spike fades, engulfing + EMA + volume). Research only: it places no orders.

Execution (same for all): a signal on a bar close enters at the next bar's open; stop and target are
ATR multiples set at entry and walked inside each bar like TradingView (open -> nearer extreme ->
other extreme); a strategy exit signal or the time limit closes at the next open; one position at
a time. Costs: Pionex 0.05% fee + 0.01% slippage per side (futures; funding ignored, holds are short).
Each strategy has a small grid of signal settings x 4 exit styles:
  (sl 1.0 ATR, tp 1.0), (1.0, 2.0), (2.0, 1.0) "many small wins", (1.5, signal exit / time only).
Walk-forward: the data is cut into 5 equal parts; for parts 2-5 the config with the best net
expectancy on ALL earlier data (>= 30 trades) is traded on that part only. Only those out-of-sample
trades count.
PASS needs all of: >= 100 OOS trades, mean net > 0, profit factor >= 1.1, positive in >= 3 of 4
OOS parts, and a daily-block bootstrap lower bound > 0 at alpha 0.05 / (strategies x timeframes).
A pass on BTC must then repeat on ETH (same timeframe, same procedure) before it is called real.
"""
from __future__ import annotations

import math
from collections import deque

NAN = float("nan")
FEE, SLIP = 0.0005, 0.0001
EXITS = ((1.0, 1.0), (1.0, 2.0), (2.0, 1.0), (1.5, None))
DAY = 86_400_000


# ---------------------------------------------------------------- fast indicators (lists of floats)
def fin(x):
    return x == x and x not in (math.inf, -math.inf)


def ema(x, n):
    o, a, p, s, k = [NAN] * len(x), 2 / (n + 1), NAN, 0.0, 0
    for i, v in enumerate(x):
        if not fin(v):
            continue
        if not fin(p):
            s += v
            k += 1
            if k == n:
                p = s / n
                o[i] = p
        else:
            p = v * a + p * (1 - a)
            o[i] = p
    return o


def rma(x, n):
    o, p, s, k = [NAN] * len(x), NAN, 0.0, 0
    for i, v in enumerate(x):
        if not fin(v):
            continue
        if not fin(p):
            s += v
            k += 1
            if k == n:
                p = s / n
                o[i] = p
        else:
            p = (p * (n - 1) + v) / n
            o[i] = p
    return o


def sma(x, n):
    o, s = [NAN] * len(x), 0.0
    for i, v in enumerate(x):
        s += v
        if i >= n:
            s -= x[i - n]
        if i >= n - 1:
            o[i] = s / n
    return o


def rstd(x, n):
    o, s, q = [NAN] * len(x), 0.0, 0.0
    for i, v in enumerate(x):
        s += v
        q += v * v
        if i >= n:
            s -= x[i - n]
            q -= x[i - n] * x[i - n]
        if i >= n - 1:
            m = s / n
            o[i] = math.sqrt(max(0.0, q / n - m * m))
    return o


def rmax(x, n):
    o, d = [NAN] * len(x), deque()
    for i, v in enumerate(x):
        while d and x[d[-1]] <= v:
            d.pop()
        d.append(i)
        if d[0] <= i - n:
            d.popleft()
        if i >= n - 1:
            o[i] = x[d[0]]
    return o


def rmin(x, n):
    return [-v if fin(v) else NAN for v in rmax([-v for v in x], n)]


def rsi(c, n):
    g, ls = [NAN], [NAN]
    for i in range(1, len(c)):
        ch = c[i] - c[i - 1]
        g.append(max(ch, 0.0))
        ls.append(max(-ch, 0.0))
    ag, al = rma(g, n), rma(ls, n)
    return [NAN if not (fin(a) and fin(b)) else 100.0 if b == 0 else 100 - 100 / (1 + a / b) for a, b in zip(ag, al)]


def atr(h, l, c, n=14):
    tr = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    return rma(tr, n)


def cross_up(a, b, i):
    return fin(a[i]) and fin(b[i]) and fin(a[i - 1]) and fin(b[i - 1]) and a[i - 1] <= b[i - 1] and a[i] > b[i]


def cross_dn(a, b, i):
    return fin(a[i]) and fin(b[i]) and fin(a[i - 1]) and fin(b[i - 1]) and a[i - 1] >= b[i - 1] and a[i] < b[i]


def session_vwap(t, h, l, c, v):
    o, pv, vv, day = [NAN] * len(c), 0.0, 0.0, None
    for i in range(len(c)):
        d = t[i] // DAY
        if d != day:
            pv = vv = 0.0
            day = d
        tp = (h[i] + l[i] + c[i]) / 3
        pv += tp * v[i]
        vv += v[i]
        o[i] = pv / vv if vv > 0 else c[i]
    return o


def supertrend(h, l, c, n=10, mult=3.0):
    a, out = atr(h, l, c, n), [0] * len(c)
    fu = fl = NAN
    d = 1
    for i in range(len(c)):
        if not fin(a[i]):
            continue
        m = (h[i] + l[i]) / 2
        bu, bl = m + mult * a[i], m - mult * a[i]
        fu = bu if not fin(fu) or bu < fu or c[i - 1] > fu else fu
        fl = bl if not fin(fl) or bl > fl or c[i - 1] < fl else fl
        if d == 1 and c[i] < fl:
            d = -1
        elif d == -1 and c[i] > fu:
            d = 1
        out[i] = d
    return out


def ut_bot(c, a, key=1.0):
    """ATR trailing stop direction (UT Bot): +1 above the trail, -1 below."""
    trail, d, out = NAN, 0, [0] * len(c)
    for i in range(len(c)):
        if not fin(a[i]):
            continue
        nl = key * a[i]
        if not fin(trail):
            trail = c[i] - nl
        elif c[i] > trail and c[i - 1] > trail:
            trail = max(trail, c[i] - nl)
        elif c[i] < trail and c[i - 1] < trail:
            trail = min(trail, c[i] + nl)
        elif c[i] > trail:
            trail = c[i] - nl
        else:
            trail = c[i] + nl
        d = 1 if c[i] > trail else -1
        out[i] = d
    return out


def psar(h, l, step=0.02, mx=0.2):
    n, out = len(h), [0] * len(h)
    if n < 3:
        return out
    up, af, ep, s = True, step, h[0], l[0]
    for i in range(1, n):
        s = s + af * (ep - s)
        if up:
            s = min(s, l[i - 1], l[i - 2] if i > 1 else l[i - 1])
            if l[i] < s:
                up, s, ep, af = False, ep, l[i], step
            elif h[i] > ep:
                ep, af = h[i], min(mx, af + step)
        else:
            s = max(s, h[i - 1], h[i - 2] if i > 1 else h[i - 1])
            if h[i] > s:
                up, s, ep, af = True, ep, h[i], step
            elif l[i] < ep:
                ep, af = l[i], min(mx, af + step)
        out[i] = 1 if up else -1
    return out


def adx(h, l, c, n=14):
    pdm, mdm = [0.0], [0.0]
    for i in range(1, len(c)):
        u, d = h[i] - h[i - 1], l[i - 1] - l[i]
        pdm.append(u if u > d and u > 0 else 0.0)
        mdm.append(d if d > u and d > 0 else 0.0)
    tr = rma([h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))], n)
    p, m = rma(pdm, n), rma(mdm, n)
    dx = [100 * abs(a - b) / (a + b) if fin(a) and fin(b) and fin(t_) and (a + b) > 0 else NAN
          for a, b, t_ in zip(p, m, tr)]
    return rma(dx, n)


# ---------------------------------------------------------------- strategies: (sig, ex) per bar
# sig[i] = +1/-1 enter at next open; ex[i] = +1 close longs, -1 close shorts, 2 close any
def s_ema_cross(b, p):
    f, s = ema(b["c"], p["fast"]), ema(b["c"], p["slow"])
    vw = session_vwap(b["t"], b["h"], b["l"], b["c"], b["v"]) if p.get("vwap") else None
    n = len(f)
    sig, ex = [0] * n, [0] * n
    for i in range(1, n):
        if cross_up(f, s, i) and (vw is None or b["c"][i] > vw[i]):
            sig[i] = 1
        elif cross_dn(f, s, i) and (vw is None or b["c"][i] < vw[i]):
            sig[i] = -1
        if cross_up(f, s, i):
            ex[i] = -1
        elif cross_dn(f, s, i):
            ex[i] = 1
    return sig, ex


def s_macd_ema200(b, p):
    c = b["c"]
    m = [x - y if fin(x) and fin(y) else NAN for x, y in zip(ema(c, 12), ema(c, 26))]
    sg, e200 = ema(m, 9), ema(c, p["trend"])
    n = len(c)
    sig, ex = [0] * n, [0] * n
    for i in range(1, n):
        if cross_up(m, sg, i) and m[i] < 0 and c[i] > e200[i]:
            sig[i] = 1
        elif cross_dn(m, sg, i) and m[i] > 0 and c[i] < e200[i]:
            sig[i] = -1
        if cross_dn(m, sg, i):
            ex[i] = 1
        elif cross_up(m, sg, i):
            ex[i] = -1
    return sig, ex


def s_rsi_reversion(b, p):
    r = rsi(b["c"], p["len"])
    lo, hi = p["lo"], 100 - p["lo"]
    n = len(r)
    sig, ex = [0] * n, [0] * n
    for i in range(1, n):
        if fin(r[i]) and fin(r[i - 1]):
            if r[i - 1] < lo <= r[i]:
                sig[i] = 1
            elif r[i - 1] > hi >= r[i]:
                sig[i] = -1
            if r[i] >= 50:
                ex[i] = 1
            if r[i] <= 50:
                ex[i] = 2 if ex[i] else -1
    return sig, ex


def s_rsi2(b, p):
    c = b["c"]
    r, ma, m5 = rsi(c, 2), sma(c, p["trend"]), sma(c, 5)
    n = len(c)
    sig, ex = [0] * n, [0] * n
    for i in range(n):
        if fin(r[i]) and fin(ma[i]):
            if r[i] < p["lo"] and c[i] > ma[i]:
                sig[i] = 1
            elif r[i] > 100 - p["lo"] and c[i] < ma[i]:
                sig[i] = -1
        if fin(m5[i]):
            if c[i] > m5[i]:
                ex[i] = 1
            elif c[i] < m5[i]:
                ex[i] = -1
    return sig, ex


def s_bb_reversion(b, p):
    c = b["c"]
    m, s = sma(c, 20), rstd(c, 20)
    n = len(c)
    sig, ex = [0] * n, [0] * n
    for i in range(1, n):
        if not fin(s[i]):
            continue
        lo, hi = m[i] - p["k"] * s[i], m[i] + p["k"] * s[i]
        if c[i - 1] < m[i - 1] - p["k"] * s[i - 1] and c[i] > lo:       # close back inside the lower band
            sig[i] = 1
        elif c[i - 1] > m[i - 1] + p["k"] * s[i - 1] and c[i] < hi:
            sig[i] = -1
        if c[i] >= m[i]:
            ex[i] = 1
        if c[i] <= m[i]:
            ex[i] = 2 if ex[i] else -1
    return sig, ex


def s_bb_squeeze(b, p):
    c = b["c"]
    m, s = sma(c, 20), rstd(c, 20)
    width = [2 * x / y if fin(x) and y else NAN for x, y in zip(s, m)]
    wmin = rmin([w if fin(w) else 1e9 for w in width], p["look"])
    n = len(c)
    sig, ex = [0] * n, [0] * n
    for i in range(1, n):
        if not (fin(width[i - 1]) and fin(wmin[i - 1])):
            continue
        squeezed = width[i - 1] <= wmin[i - 1] * 1.1
        if squeezed and c[i] > m[i] + 2 * s[i]:
            sig[i] = 1
        elif squeezed and c[i] < m[i] - 2 * s[i]:
            sig[i] = -1
        if fin(m[i]):
            if c[i] < m[i]:
                ex[i] = 1
            elif c[i] > m[i]:
                ex[i] = -1
    return sig, ex


def s_supertrend(b, p):
    st = supertrend(b["h"], b["l"], b["c"], 10, p["mult"])
    e = ema(b["c"], 200) if p.get("filter") else None
    n = len(st)
    sig, ex = [0] * n, [0] * n
    for i in range(1, n):
        if st[i] == 1 and st[i - 1] == -1:
            ex[i] = -1
            if e is None or (fin(e[i]) and b["c"][i] > e[i]):
                sig[i] = 1
        elif st[i] == -1 and st[i - 1] == 1:
            ex[i] = 1
            if e is None or (fin(e[i]) and b["c"][i] < e[i]):
                sig[i] = -1
    return sig, ex


def s_ut_bot(b, p):
    a = atr(b["h"], b["l"], b["c"], 10)
    d = ut_bot(b["c"], a, p["key"])
    e = ema(b["c"], p["ema"]) if p.get("ema") else None
    n = len(d)
    sig, ex = [0] * n, [0] * n
    for i in range(1, n):
        if d[i] == 1 and d[i - 1] == -1:
            ex[i] = -1
            if e is None or (fin(e[i]) and b["c"][i] > e[i]):
                sig[i] = 1
        elif d[i] == -1 and d[i - 1] == 1:
            ex[i] = 1
            if e is None or (fin(e[i]) and b["c"][i] < e[i]):
                sig[i] = -1
    return sig, ex


def s_psar(b, p):
    d, e = psar(b["h"], b["l"]), ema(b["c"], p["trend"])
    n = len(d)
    sig, ex = [0] * n, [0] * n
    for i in range(1, n):
        if d[i] == 1 and d[i - 1] == -1:
            ex[i] = -1
            if fin(e[i]) and b["c"][i] > e[i]:
                sig[i] = 1
        elif d[i] == -1 and d[i - 1] == 1:
            ex[i] = 1
            if fin(e[i]) and b["c"][i] < e[i]:
                sig[i] = -1
    return sig, ex


def s_stochrsi(b, p):
    c = b["c"]
    r = rsi(c, 14)
    rr = [x if fin(x) else 50.0 for x in r]
    hh, ll = rmax(rr, 14), rmin(rr, 14)
    raw = [100 * (x - lo) / (hi - lo) if fin(hi) and hi > lo else 50.0 for x, hi, lo in zip(rr, hh, ll)]
    k = sma(raw, 3)
    d = sma([x if fin(x) else 50.0 for x in k], 3)
    e = ema(c, p["trend"])
    n = len(c)
    sig, ex = [0] * n, [0] * n
    for i in range(1, n):
        if not fin(e[i]):
            continue
        if cross_up(k, d, i) and k[i] < p["zone"] and c[i] > e[i]:
            sig[i] = 1
        elif cross_dn(k, d, i) and k[i] > 100 - p["zone"] and c[i] < e[i]:
            sig[i] = -1
        if fin(k[i]):
            if k[i] > 100 - p["zone"]:
                ex[i] = 1
            elif k[i] < p["zone"]:
                ex[i] = -1
    return sig, ex


def s_donchian(b, p):
    h, l, c = b["h"], b["l"], b["c"]
    up, dn = rmax(h, p["n"]), rmin(l, p["n"])
    xu, xd = rmax(h, max(2, p["n"] // 2)), rmin(l, max(2, p["n"] // 2))
    n = len(c)
    sig, ex = [0] * n, [0] * n
    for i in range(1, n):
        if fin(up[i - 1]) and c[i] > up[i - 1]:
            sig[i] = 1
        elif fin(dn[i - 1]) and c[i] < dn[i - 1]:
            sig[i] = -1
        if fin(xd[i - 1]) and c[i] < xd[i - 1]:
            ex[i] = 1
        elif fin(xu[i - 1]) and c[i] > xu[i - 1]:
            ex[i] = -1
    return sig, ex


def s_keltner(b, p):
    c = b["c"]
    m, a = ema(c, 20), atr(b["h"], b["l"], c, 10)
    n = len(c)
    sig, ex = [0] * n, [0] * n
    for i in range(1, n):
        if not (fin(m[i]) and fin(a[i])):
            continue
        if c[i] > m[i] + p["mult"] * a[i] and c[i - 1] <= m[i - 1] + p["mult"] * a[i - 1]:
            sig[i] = 1
        elif c[i] < m[i] - p["mult"] * a[i] and c[i - 1] >= m[i - 1] - p["mult"] * a[i - 1]:
            sig[i] = -1
        if c[i] < m[i]:
            ex[i] = 1
        elif c[i] > m[i]:
            ex[i] = -1
    return sig, ex


def s_range_adx(b, p):
    h, l, c = b["h"], b["l"], b["c"]
    ax, hi, lo = adx(h, l, c, 14), rmax(h, p["n"]), rmin(l, p["n"])
    n = len(c)
    sig, ex = [0] * n, [0] * n
    for i in range(1, n):
        if not (fin(ax[i]) and fin(hi[i - 1])) or ax[i] >= p["adx"]:
            continue
        mid = (hi[i - 1] + lo[i - 1]) / 2
        if l[i] <= lo[i - 1] and c[i] > lo[i - 1]:                     # wick below the range low, closed back in
            sig[i] = 1
        elif h[i] >= hi[i - 1] and c[i] < hi[i - 1]:
            sig[i] = -1
        if c[i] >= mid:
            ex[i] = 1
        if c[i] <= mid:
            ex[i] = 2 if ex[i] else -1
    return sig, ex


def s_heikin_ashi(b, p):
    o, h, l, c = b["o"], b["h"], b["l"], b["c"]
    n = len(c)
    hc = [(o[i] + h[i] + l[i] + c[i]) / 4 for i in range(n)]
    ho = [0.0] * n
    ho[0] = (o[0] + c[0]) / 2
    for i in range(1, n):
        ho[i] = (ho[i - 1] + hc[i - 1]) / 2
    e = ema(c, p["trend"])
    sig, ex = [0] * n, [0] * n
    for i in range(2, n):
        g, pg = hc[i] > ho[i], hc[i - 1] > ho[i - 1]
        if g and not pg:
            ex[i] = -1
            if fin(e[i]) and c[i] > e[i]:
                sig[i] = 1
        elif not g and pg:
            ex[i] = 1
            if fin(e[i]) and c[i] < e[i]:
                sig[i] = -1
    return sig, ex


def s_vwap_reversion(b, p):
    c = b["c"]
    vw, a = session_vwap(b["t"], b["h"], b["l"], c, b["v"]), atr(b["h"], b["l"], c, 14)
    n = len(c)
    sig, ex = [0] * n, [0] * n
    for i in range(1, n):
        if not fin(a[i]):
            continue
        dev = (c[i] - vw[i]) / a[i]
        if dev < -p["k"] and c[i] > c[i - 1]:
            sig[i] = 1
        elif dev > p["k"] and c[i] < c[i - 1]:
            sig[i] = -1
        if c[i] >= vw[i]:
            ex[i] = 1
        if c[i] <= vw[i]:
            ex[i] = 2 if ex[i] else -1
    return sig, ex


def s_volume_fade(b, p):
    o, c, v = b["o"], b["c"], b["v"]
    va, a = sma(v, 50), atr(b["h"], b["l"], c, 14)
    n = len(c)
    sig, ex = [0] * n, [0] * n
    for i in range(1, n):
        if not (fin(va[i - 1]) and fin(a[i])) or va[i - 1] <= 0:
            continue
        if v[i] > p["vol"] * va[i - 1] and abs(c[i] - o[i]) > 1.5 * a[i]:
            sig[i] = 1 if c[i] < o[i] else -1                          # fade the climax candle
    return sig, ex


def s_engulfing(b, p):
    o, c, v = b["o"], b["c"], b["v"]
    e20, e50, va = ema(c, 20), ema(c, 50), sma(v, 20)
    n = len(c)
    sig, ex = [0] * n, [0] * n
    for i in range(1, n):
        if not (fin(e50[i]) and fin(va[i])):
            continue
        bull = c[i] > o[i] and o[i - 1] > c[i - 1] and c[i] >= o[i - 1] and o[i] <= c[i - 1]
        bear = c[i] < o[i] and o[i - 1] < c[i - 1] and c[i] <= o[i - 1] and o[i] >= c[i - 1]
        vol_ok = v[i] > p["vol"] * va[i]
        if bull and vol_ok and e20[i] > e50[i]:
            sig[i] = 1
        elif bear and vol_ok and e20[i] < e50[i]:
            sig[i] = -1
    return sig, ex


def s_orb_ny(b, p):
    """NY opening-range breakout: range of the first `mins` minutes after 09:30 New York."""
    from .btc_swing import _ny_ms
    from datetime import datetime, timezone
    t, h, l, c = b["t"], b["h"], b["l"], b["c"]
    n = len(c)
    step = t[1] - t[0]
    sig, ex = [0] * n, [0] * n
    opens = {}
    for i in range(n):
        d = datetime.fromtimestamp(t[i] / 1000, timezone.utc).strftime("%Y-%m-%d")
        if d not in opens:
            opens[d] = _ny_ms(d, 9, 30)
    rng_hi = rng_lo = NAN
    cur_day, traded = None, False
    for i in range(n):
        d = datetime.fromtimestamp(t[i] / 1000, timezone.utc).strftime("%Y-%m-%d") if i == 0 or t[i] // DAY != t[i - 1] // DAY else cur_day
        if d != cur_day:
            cur_day, traded, rng_hi, rng_lo = d, False, NAN, NAN
        op = opens[d]
        end_rng = op + p["mins"] * 60_000
        if op <= t[i] and t[i] + step <= end_rng:
            rng_hi = h[i] if not fin(rng_hi) else max(rng_hi, h[i])
            rng_lo = l[i] if not fin(rng_lo) else min(rng_lo, l[i])
        elif t[i] >= end_rng and t[i] < op + 3 * 3_600_000 and fin(rng_hi) and not traded:
            if c[i] > rng_hi:
                sig[i], traded = 1, True
            elif c[i] < rng_lo:
                sig[i], traded = -1, True
        if t[i] >= op + 6 * 3_600_000:
            ex[i] = 2                                                  # flat by the end of the US session
    return sig, ex


STRATEGIES = {
    "ema_cross": (s_ema_cross, [{"fast": 9, "slow": 21}, {"fast": 20, "slow": 50}]),
    "ema_cross_vwap": (s_ema_cross, [{"fast": 9, "slow": 21, "vwap": True}, {"fast": 20, "slow": 50, "vwap": True}]),
    "macd_ema200": (s_macd_ema200, [{"trend": 200}, {"trend": 100}]),
    "rsi_reversion": (s_rsi_reversion, [{"len": 14, "lo": 30}, {"len": 7, "lo": 20}]),
    "rsi2_connors": (s_rsi2, [{"lo": 10, "trend": 200}, {"lo": 5, "trend": 100}]),
    "bb_reversion": (s_bb_reversion, [{"k": 2.0}, {"k": 2.5}]),
    "bb_squeeze": (s_bb_squeeze, [{"look": 120}, {"look": 60}]),
    "supertrend": (s_supertrend, [{"mult": 3.0}, {"mult": 2.0, "filter": True}]),
    "ut_bot": (s_ut_bot, [{"key": 1.0}, {"key": 2.0, "ema": 50}]),
    "psar_ema": (s_psar, [{"trend": 200}, {"trend": 50}]),
    "stochrsi_trend": (s_stochrsi, [{"trend": 50, "zone": 20}, {"trend": 200, "zone": 20}]),
    "donchian": (s_donchian, [{"n": 20}, {"n": 55}]),
    "keltner_breakout": (s_keltner, [{"mult": 2.0}, {"mult": 3.0}]),
    "range_adx": (s_range_adx, [{"n": 30, "adx": 20}, {"n": 60, "adx": 25}]),
    "heikin_ashi": (s_heikin_ashi, [{"trend": 50}, {"trend": 200}]),
    "vwap_reversion": (s_vwap_reversion, [{"k": 2.0}, {"k": 3.0}]),
    "volume_fade": (s_volume_fade, [{"vol": 3.0}, {"vol": 5.0}]),
    "engulfing_ema_vol": (s_engulfing, [{"vol": 1.5}, {"vol": 2.0}]),
    "orb_ny": (s_orb_ny, [{"mins": 15}, {"mins": 30}]),
}
INTRADAY_ONLY = {"orb_ny"}                         # needs sub-hour bars


# ---------------------------------------------------------------- execution
def _exit_in_bar(side, o, h, l, stop, limit):
    if side > 0:
        if o <= stop:
            return o
        if limit == limit and o >= limit:
            return o
    else:
        if o >= stop:
            return o
        if limit == limit and o <= limit:
            return o
    hi_first = abs(h - o) < abs(o - l)
    for leg in (("hi", "lo") if hi_first else ("lo", "hi")):
        if side > 0:
            if leg == "hi" and limit == limit and h >= limit:
                return limit
            if leg == "lo" and l <= stop:
                return stop
        else:
            if leg == "lo" and limit == limit and l <= limit:
                return limit
            if leg == "hi" and h >= stop:
                return stop
    return None


def simulate(b, a, sig, ex, sl, tp, max_hold, fee=FEE, slip=SLIP):
    t, o, h, l, c = b["t"], b["o"], b["h"], b["l"], b["c"]
    n = len(c)
    trades, pos, pend, close_next = [], 0, 0, False
    entry = stop = limit = 0.0
    t_in = i_in = 0
    for i in range(1, n):
        if pos and close_next:                                          # signal / time exit at this open
            px = o[i]
            g = pos * (px / entry - 1)
            trades.append((t_in, t[i], pos, g, g - 2 * (fee + slip)))
            pos, close_next = 0, False
        if pend and not pos:
            pos, entry, t_in, i_in = pend, o[i], t[i], i
            k = a[i - 1]
            stop = entry - pos * sl * k
            limit = entry + pos * tp * k if tp else NAN
            pend = 0
        pend = 0
        if pos:
            px = _exit_in_bar(pos, o[i], h[i], l[i], stop, limit)
            if px is not None:
                g = pos * (px / entry - 1)
                trades.append((t_in, t[i], pos, g, g - 2 * (fee + slip)))
                pos = 0
            elif ex[i] == 2 or ex[i] == pos or i - i_in + 1 >= max_hold or sig[i] == -pos:
                close_next = True
        if not pos and sig[i] and fin(a[i]):
            pend = sig[i]
    return trades


# ---------------------------------------------------------------- walk-forward evaluation
def _stats(tr):
    if not tr:
        return {"n": 0, "mean": None, "pf": None, "win": None}
    nets = [x[4] for x in tr]
    w = [x for x in nets if x > 0]
    ls = [-x for x in nets if x < 0]
    return {"n": len(nets), "mean": sum(nets) / len(nets), "pf": (sum(w) / sum(ls)) if ls else None,
            "win": len(w) / len(nets), "gross": sum(x[3] for x in tr) / len(nets)}


TIMEFRAMES = {"1m": 120, "5m": 96, "15m": 64, "1h": 48, "4h": 30}      # max hold in bars (2h .. 5 days)
_CACHE = {}


def load(tf, symbol="BTC_USDT"):
    """Bars as plain lists: 1m from var/fib/btc_1m.db (12 months), others from the proxy archive."""
    key = (tf, symbol)
    if key in _CACHE:
        return _CACHE[key]
    from ..data.store import MarketView, resample
    from ..paths import Paths
    p = Paths.default()
    if tf == "1m":
        bars = MarketView(p.root / "fib" / ("btc_1m.db" if symbol == "BTC_USDT" else "eth_1m.db")).bars(symbol, "1M")
    elif tf in ("5m", "15m"):
        bars = MarketView(p.proxy_market).bars(symbol, "5M")
        bars = resample(bars, "15M") if tf == "15m" else bars
    else:
        src = p.proxy_market if symbol in ("BTC_USDT", "ETH_USDT") else p.root / "alpha" / "alts_1h.db"
        bars = MarketView(src).bars(symbol, "60M")
        bars = resample(bars, "4H") if tf == "4h" else bars
    b = {"t": list(bars.t), "o": list(bars.o), "h": list(bars.h), "l": list(bars.l), "c": list(bars.c), "v": list(bars.v)}
    _CACHE[key] = b
    return b


def work(task):
    """One (timeframe, strategy, symbol) walk-forward; returns a summary row (picklable)."""
    tf, name, symbol = task
    b = load(tf, symbol)
    oos, folds, chosen, configs = evaluate(b, name, TIMEFRAMES[tf])
    s = _stats(oos)
    years = (b["t"][-1] - b["t"][0]) / (365.25 * DAY) * 4 / 5
    return {"tf": tf, "strategy": name, "symbol": symbol, "oos": s, "per_year": s["n"] / years if years else None,
            "folds": folds, "chosen": chosen,
            "trades": [{"entry_time": x[0], "exit_time": x[1], "side": x[2], "gross_bps": x[3] * 1e4, "net_bps": x[4] * 1e4} for x in oos]}


TREND = ("keltner_breakout", "ema_cross", "supertrend", "psar_ema", "donchian", "heikin_ashi", "ut_bot", "macd_ema200")
COINS = ("BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", "DOGE_USDT", "LINK_USDT", "ADA_USDT", "BNB_USDT", "AVAX_USDT", "LTC_USDT")
POOLED_RULES = """pooled 4h trend family (pre-registered 2026-10-14 01:40 SAST): the 8 trend/breakout strategies on 4h
bars of 10 coins, the same per-coin walk-forward (5 parts), max hold 60 bars (10 days), Pionex costs.
Pass for a strategy: pooled out-of-sample mean net > 0, profit factor >= 1.1, positive total on >= 7 of
10 coins, and a daily-block bootstrap lower bound > 0 at alpha 0.05 / 8."""


def _pooled_work(task):
    tf, name, symbol, hold = task
    b = load(tf, symbol)
    oos, folds, chosen, _ = evaluate(b, name, hold)
    return name, symbol, [{"entry_time": x[0], "exit_time": x[1], "side": x[2], "gross_bps": x[3] * 1e4, "net_bps": x[4] * 1e4} for x in oos]


def run_pooled(tf="4h", hold=60, workers=None):
    import os
    from concurrent.futures import ProcessPoolExecutor
    from ..research import metrics
    tasks = [(tf, n, s, hold) for n in TREND for s in COINS]
    with ProcessPoolExecutor(max_workers=workers or max(1, (os.cpu_count() or 2) - 1)) as pool:
        res = list(pool.map(_pooled_work, tasks))
    out = {}
    for name in TREND:
        per = {s: tr for n, s, tr in res if n == name}
        allt = sorted([t for tr in per.values() for t in tr], key=lambda x: x["exit_time"])
        nets = [t["net_bps"] for t in allt]
        wins = [x for x in nets if x > 0]
        ls = [-x for x in nets if x < 0]
        coin_tot = {s: sum(t["net_bps"] for t in tr) / 100 for s, tr in per.items()}
        mean = sum(nets) / len(nets) if nets else 0.0
        pf = sum(wins) / sum(ls) if ls else None
        pos = sum(v > 0 for v in coin_tot.values())
        cand = mean > 0 and (pf or 0) >= 1.1 and pos >= 7
        lb = metrics.block_bootstrap_lower(allt, 0.05 / len(TREND)) if cand else None
        out[name] = {"n": len(nets), "mean_bps": mean, "pf": pf, "win": len(wins) / len(nets) if nets else None,
                     "coins_positive": pos, "coin_total_pct": coin_tot, "bootstrap_lower_bps": lb,
                     "pass": bool(cand and lb is not None and lb > 0)}
    return out


def run_all(symbol="BTC_USDT", workers=None):
    import os
    from concurrent.futures import ProcessPoolExecutor
    from ..research import metrics
    tasks = [(tf, name, symbol) for tf in TIMEFRAMES for name in STRATEGIES
             if not (name in INTRADAY_ONLY and tf in ("1h", "4h"))]
    tasks.sort(key=lambda x: x[0] != "1m")                              # heavy 1m tasks first
    with ProcessPoolExecutor(max_workers=workers or max(1, (os.cpu_count() or 2) - 1)) as pool:
        rows = list(pool.map(work, tasks))
    alpha = 0.05 / len(tasks)
    for r in rows:
        s = r["oos"]
        folds = [f for f in r["folds"] if f is not None]
        r["positive_folds"] = sum(f > 0 for f in folds)
        cand = s["n"] >= 100 and (s["mean"] or 0) > 0 and (s["pf"] or 0) >= 1.1 and r["positive_folds"] >= 3
        r["bootstrap_lower_bps"] = metrics.block_bootstrap_lower(r["trades"], alpha) if cand else None
        r["pass"] = bool(cand and r["bootstrap_lower_bps"] is not None and r["bootstrap_lower_bps"] > 0)
    return rows, alpha


def evaluate(b, name, max_hold, parts=5):
    """Walk-forward over `parts` equal time slices; returns OOS trades and per-part results."""
    fn, grid = STRATEGIES[name]
    a = atr(b["h"], b["l"], b["c"], 14)
    configs = []
    for sp in grid:
        sig, ex = fn(b, sp)
        for sl, tp in EXITS:
            tr = simulate(b, a, sig, ex, sl, tp, max_hold)
            configs.append(({**sp, "sl": sl, "tp": tp}, tr))
    t = b["t"]
    edges = [t[0] + (t[-1] - t[0]) * k // parts for k in range(parts + 1)]
    oos, folds, chosen = [], [], []
    for k in range(1, parts):
        best, best_s = None, None
        for cfg, tr in configs:
            s = _stats([x for x in tr if x[0] < edges[k]])
            if s["n"] >= 30 and (best_s is None or s["mean"] > best_s["mean"]):
                best, best_s = (cfg, tr), s
        if best is None:
            folds.append(None)
            continue
        part = [x for x in best[1] if edges[k] <= x[0] < edges[k + 1]]
        oos += part
        folds.append(sum(x[4] for x in part))
        chosen.append(best[0])
    return oos, folds, chosen, configs
