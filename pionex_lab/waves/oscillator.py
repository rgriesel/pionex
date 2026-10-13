"""WL Oscillator: our own Prime-style momentum + money-flow oscillator, built from open formulas.

This is NOT ChartPrime's "Prime Oscillators Pro" (that script is closed source and paid). It is an
independent build of the same kind of tool, following only the public description of what that
indicator shows, with well-known public formulas, so the user can judge whether this family of
oscillator is worth paying for:
  main        WaveTrend: channel index of hlc3 (EMA n1), smoothed by EMA n2; signal = SMA 4 of it;
              green while above its signal, red below
  money flow  Money Flow Index (price x volume) centred to +-100 and EMA-smoothed (mfs)
  volume      volume matrix: EMA10 of signed volume (up bars +, down bars -) / EMA10 of volume, -1..1
  rank 0-7    how many of 7 trend conditions are bullish: close > EMA20, EMA20 > EMA50, RSI14 > 50,
              MACD(12,26,9) histogram > 0, WaveTrend > signal, MFI > 50, close > rolling VWAP;
              power bars when >= 5 agree (brighter = more)
  reversal    WaveTrend crossing its signal while beyond the overbought/oversold level (ob)
  divergence  a confirmed WaveTrend pivot (`pivot` bars each side) that disagrees with price versus
              the previous pivot within `lookback` bars; marked on the bar that confirms it
  fair value  close more than 2 standard deviations away from the rolling VWAP
Every value at bar i uses bars <= i only (no repainting). The WLOSC block in wavelab/index.html
computes exactly the same numbers; tests/test_oscillator.py checks parity with node.
"""
from __future__ import annotations

import math

NAN = float("nan")
DEFAULTS = {"n1": 10, "n2": 21, "mfi": 14, "mfs": 5, "ob": 53, "pivot": 5, "lookback": 60, "vwap": 50}


def _fin(x) -> bool:
    return x is not None and not math.isnan(x) and not math.isinf(x)


def ema(x, n):
    o, a, p, s, c = [NAN] * len(x), 2 / (n + 1), NAN, 0.0, 0
    for i, v in enumerate(x):
        if not _fin(v):
            continue
        if not _fin(p):
            s += v
            c += 1
            if c == n:
                p = s / n
                o[i] = p
        else:
            p = v * a + p * (1 - a)
            o[i] = p
    return o


def rma(x, n):
    o, p, s, c = [NAN] * len(x), NAN, 0.0, 0
    for i, v in enumerate(x):
        if not _fin(v):
            continue
        if not _fin(p):
            s += v
            c += 1
            if c == n:
                p = s / n
                o[i] = p
        else:
            p = (p * (n - 1) + v) / n
            o[i] = p
    return o


def sma(x, n):
    o = [NAN] * len(x)
    for i in range(n - 1, len(x)):
        s, ok = 0.0, True
        for j in range(n):
            if not _fin(x[i - j]):
                ok = False
                break
            s += x[i - j]
        if ok:
            o[i] = s / n
    return o


def calc(o, h, l, c, v, params=None) -> dict:
    p = dict(DEFAULTS, **(params or {}))
    n = len(c)
    ap = [(h[i] + l[i] + c[i]) / 3 for i in range(n)]
    esa = ema(ap, p["n1"])
    dd = ema([abs(ap[i] - esa[i]) if _fin(esa[i]) else NAN for i in range(n)], p["n1"])
    ci = [NAN if not _fin(dd[i]) else (ap[i] - esa[i]) / (0.015 * dd[i]) if dd[i] > 0 else 0.0 for i in range(n)]
    wt1 = ema(ci, p["n2"])
    wt2 = sma(wt1, 4)

    m = p["mfi"]
    mfi = [NAN] * n
    for i in range(m, n):
        pos = neg = 0.0
        for j in range(m):
            k = i - j
            f = ap[k] * v[k]
            if ap[k] > ap[k - 1]:
                pos += f
            elif ap[k] < ap[k - 1]:
                neg += f
        mfi[i] = 100 - 100 / (1 + pos / neg) if neg > 0 else (100.0 if pos > 0 else 50.0)
    mf = ema([(x - 50) * 2 if _fin(x) else NAN for x in mfi], p["mfs"])

    gains, losses = [NAN], [NAN]
    for i in range(1, n):
        ch = c[i] - c[i - 1]
        gains.append(max(ch, 0.0))
        losses.append(max(-ch, 0.0))
    ag, al = rma(gains, 14), rma(losses, 14)
    rsi = [NAN if not (_fin(ag[i]) and _fin(al[i])) else 100.0 if al[i] == 0 else 100 - 100 / (1 + ag[i] / al[i])
           for i in range(n)]
    e12, e26, e20, e50 = ema(c, 12), ema(c, 26), ema(c, 20), ema(c, 50)
    macd = [e12[i] - e26[i] if _fin(e12[i]) and _fin(e26[i]) else NAN for i in range(n)]
    sig = ema(macd, 9)
    hist = [macd[i] - sig[i] if _fin(sig[i]) else NAN for i in range(n)]

    w = p["vwap"]
    vwap, sd = [NAN] * n, [NAN] * n
    for i in range(w - 1, n):
        s1 = s2 = s3 = 0.0
        for j in range(w):
            k = i - j
            s1 += ap[k] * v[k]
            s2 += v[k]
            s3 += c[k]
        if s2 > 0:
            vwap[i] = s1 / s2
        mean, var = s3 / w, 0.0
        for j in range(w):
            dv = c[i - j] - mean
            var += dv * dv
        sd[i] = math.sqrt(var / w)

    sv = [v[i] if c[i] > o[i] else -v[i] if c[i] < o[i] else 0.0 for i in range(n)]
    es, ev = ema(sv, 10), ema(v, 10)
    vm = [es[i] / ev[i] if _fin(es[i]) and _fin(ev[i]) and ev[i] > 0 else NAN for i in range(n)]

    bull, rev, div, fair = [NAN] * n, [0] * n, [0] * n, [0] * n
    trend, mfdiv, diamond, cond = [0] * n, [0] * n, [0] * n, [NAN] * n
    dfrom, dto = [NAN] * n, [NAN] * n                 # divergence: previous pivot bar -> new pivot bar
    ob, k = p["ob"], p["pivot"]
    lows, highs, mlows, mhighs, state = [], [], [], [], 0
    for i in range(n):
        vals = (e20[i], e50[i], rsi[i], hist[i], wt1[i], wt2[i], mfi[i], vwap[i])
        if all(_fin(x) for x in vals):
            bits = (c[i] > e20[i], e20[i] > e50[i], rsi[i] > 50, hist[i] > 0, wt1[i] > wt2[i], mfi[i] > 50, c[i] > vwap[i])
            bull[i] = float(sum(bits))
            cond[i] = float(sum(1 << q for q, b in enumerate(bits) if b))   # which conditions hold (bit q)
        if i >= 1 and all(_fin(x) for x in (wt1[i - 1], wt2[i - 1], wt1[i], wt2[i])):
            if wt1[i - 1] <= wt2[i - 1] and wt1[i] > wt2[i] and wt1[i] < -ob:
                rev[i] = 1
            elif wt1[i - 1] >= wt2[i - 1] and wt1[i] < wt2[i] and wt1[i] > ob:
                rev[i] = -1
        if _fin(vwap[i]) and sd[i] > 0:
            fair[i] = 1 if c[i] < vwap[i] - 2 * sd[i] else -1 if c[i] > vwap[i] + 2 * sd[i] else 0
        j = i - k
        if j - k >= 0 and all(_fin(wt1[q]) for q in range(j - k, i + 1)):
            left, right = wt1[j - k:j], wt1[j + 1:i + 1]
            if wt1[j] < min(left) and wt1[j] <= min(right):
                if lows and j - lows[-1][0] <= p["lookback"] and l[j] < lows[-1][2] and wt1[j] > lows[-1][1] and wt1[j] < 0:
                    div[i], dfrom[i], dto[i] = 1, float(lows[-1][0]), float(j)
                lows.append((j, wt1[j], l[j]))
            if wt1[j] > max(left) and wt1[j] >= max(right):
                if (highs and j - highs[-1][0] <= p["lookback"] and h[j] > highs[-1][2] and wt1[j] < highs[-1][1]
                        and wt1[j] > 0 and div[i] == 0):
                    div[i], dfrom[i], dto[i] = -1, float(highs[-1][0]), float(j)
                highs.append((j, wt1[j], h[j]))
        if j - k >= 0 and all(_fin(mf[q]) for q in range(j - k, i + 1)):   # money flow weakening vs price
            left, right = mf[j - k:j], mf[j + 1:i + 1]
            if mf[j] > max(left) and mf[j] >= max(right):
                if (mhighs and j - mhighs[-1][0] <= p["lookback"] and mf[j] > 0 and mf[j] < mhighs[-1][1]
                        and h[j] > mhighs[-1][2]):
                    mfdiv[i] = -1
                mhighs.append((j, mf[j], h[j]))
            if mf[j] < min(left) and mf[j] <= min(right):
                if (mlows and j - mlows[-1][0] <= p["lookback"] and mf[j] < 0 and mf[j] > mlows[-1][1]
                        and l[j] < mlows[-1][2] and mfdiv[i] == 0):
                    mfdiv[i] = 1
                mlows.append((j, mf[j], l[j]))
        if _fin(bull[i]):                                    # trend arrows: rank reaches the opposite extreme
            if bull[i] >= 6 and state != 1:
                trend[i], state = 1, 1
            elif bull[i] <= 1 and state != -1:
                trend[i], state = -1, -1
        recent = range(max(0, i - 5), i + 1)                 # diamond shift: momentum dot + divergence within 6 bars
        for s in (1, -1):
            if ((rev[i] == s and any(div[q] == s for q in recent)) or (div[i] == s and any(rev[q] == s for q in recent))) \
                    and not any(diamond[q] == s for q in range(max(0, i - 5), i)):
                diamond[i] = s
                break
    return {"wt1": wt1, "wt2": wt2, "mf": mf, "mfi": mfi, "vm": vm, "bull": bull, "rev": rev, "div": div,
            "dfrom": dfrom, "dto": dto, "fair": fair, "trend": trend, "mfdiv": mfdiv, "diamond": diamond, "cond": cond}
