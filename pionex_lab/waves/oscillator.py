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


# ---- Prime Oscillators Pro modes (our own maths from ChartPrime's public docs and guide video) ----
# Mirrors prime/fusion/mvp in the WLOSC block of wavelab/index.html (parity-tested).
PRO = {"pivot": 5, "mindist": 5, "maxdist": 35}


def std(x, n):
    o = [NAN] * len(x)
    for i in range(n - 1, len(x)):
        s, ok = 0.0, True
        for j in range(n):
            if not _fin(x[i - j]):
                ok = False
                break
            s += x[i - j]
        if not ok:
            continue
        m, vr = s / n, 0.0
        for j in range(n):
            dv = x[i - j] - m
            vr += dv * dv
        o[i] = math.sqrt(vr / n)
    return o


def rsi_of(c, n):
    g, ls = [NAN], [NAN]
    for i in range(1, len(c)):
        ch = c[i] - c[i - 1]
        g.append(max(ch, 0.0))
        ls.append(max(-ch, 0.0))
    ag, al = rma(g, n), rma(ls, n)
    return [NAN if not (_fin(ag[i]) and _fin(al[i])) else 100.0 if al[i] == 0 else 100 - 100 / (1 + ag[i] / al[i])
            for i in range(len(c))]


def mfi_of(ap, v, m):
    o = [NAN] * len(ap)
    for i in range(m, len(ap)):
        pos = neg = 0.0
        for j in range(m):
            k = i - j
            f = ap[k] * v[k]
            if ap[k] > ap[k - 1]:
                pos += f
            elif ap[k] < ap[k - 1]:
                neg += f
        o[i] = 100 - 100 / (1 + pos / neg) if neg > 0 else (100.0 if pos > 0 else 50.0)
    return o


def stoch_of(h, l, c, n):
    o = [NAN] * len(c)
    for i in range(n - 1, len(c)):
        hh, ll = -math.inf, math.inf
        for j in range(n):
            hh = max(hh, h[i - j])
            ll = min(ll, l[i - j])
        o[i] = 50.0 if hh == ll else 100 * (c[i] - ll) / (hh - ll)
    return o


def atr_of(h, l, c, n):
    tr = [h[0] - l[0] if i == 0 else max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(len(c))]
    return rma(tr, n)


def divs(y, h, l, k, min_d, max_d):
    """1/-1 regular bull/bear, 2/-2 hidden bull/bear, 3/-3 multiple (chained regular) at the confirming bar."""
    n = len(y)
    div, dfrom, dto, lows, highs = [0] * n, [NAN] * n, [NAN] * n, [], []
    bull_to = bear_to = -1
    for i in range(n):
        j = i - k
        if not (j - k >= 0 and all(_fin(y[q]) for q in range(j - k, i + 1))):
            continue
        left, right = y[j - k:j], y[j + 1:i + 1]
        if y[j] < min(left) and y[j] <= min(right):
            pv = lows[-1] if lows else -1
            if pv >= 0 and min_d <= j - pv <= max_d:
                if l[j] < l[pv] and y[j] > y[pv]:
                    div[i] = 3 if pv == bull_to else 1
                    bull_to = j
                elif l[j] > l[pv] and y[j] < y[pv]:
                    div[i] = 2
                if div[i]:
                    dfrom[i], dto[i] = float(pv), float(j)
            lows.append(j)
        if y[j] > max(left) and y[j] >= max(right):
            pv = highs[-1] if highs else -1
            if pv >= 0 and min_d <= j - pv <= max_d and div[i] == 0:
                if h[j] > h[pv] and y[j] < y[pv]:
                    div[i] = -3 if pv == bear_to else -1
                    bear_to = j
                elif h[j] < h[pv] and y[j] > y[pv]:
                    div[i] = -2
                if div[i]:
                    dfrom[i], dto[i] = float(pv), float(j)
            highs.append(j)
    return {"div": div, "dfrom": dfrom, "dto": dto}


def prime(o, h, l, c, v, params=None) -> dict:
    """0-100 ribbon: mean of RSI14, MFI14 and stochastic 14, EMA5 (fast) and EMA5 of that (slow)."""
    p = dict(PRO, **(params or {}))
    n = len(c)
    ap = [(h[i] + l[i] + c[i]) / 3 for i in range(n)]
    r, m, s = rsi_of(c, 14), mfi_of(ap, v, 14), stoch_of(h, l, c, 14)
    raw = [(r[i] + m[i] + s[i]) / 3 if _fin(r[i]) and _fin(m[i]) and _fin(s[i]) else NAN for i in range(n)]
    fast = ema(raw, 5)
    slow, mid, sd = ema(fast, 5), sma(fast, 20), std(fast, 20)
    up = [x + 2 * sd[i] if _fin(x) else NAN for i, x in enumerate(mid)]
    lo = [x - 2 * sd[i] if _fin(x) else NAN for i, x in enumerate(mid)]
    brk, tri, obos, peak = [0] * n, [0] * n, [0] * n, [0] * n
    for i in range(1, n):
        if all(_fin(x) for x in (fast[i], fast[i - 1], up[i], up[i - 1])):
            if fast[i] > up[i] and fast[i - 1] <= up[i - 1]:
                brk[i] = -1
            elif fast[i] < lo[i] and fast[i - 1] >= lo[i - 1]:
                brk[i] = 1
        if all(_fin(x) for x in (fast[i], fast[i - 1], slow[i], slow[i - 1])):
            if fast[i - 1] <= slow[i - 1] and fast[i] > slow[i] and fast[i] < 40:
                tri[i] = 1
            elif fast[i - 1] >= slow[i - 1] and fast[i] < slow[i] and fast[i] > 60:
                tri[i] = -1
        if _fin(fast[i]):
            obos[i] = -1 if fast[i] >= 80 else 1 if fast[i] <= 20 else 0
    dv = divs(fast, h, l, p["pivot"], p["mindist"], p["maxdist"])
    for i in range(n):
        d = dv["div"][i]
        if d in (1, 3) and fast[int(dv["dto"][i])] <= 25:
            peak[i] = 1
        elif d in (-1, -3) and fast[int(dv["dto"][i])] >= 75:
            peak[i] = -1
    return {"fast": fast, "slow": slow, "mid": mid, "up": up, "lo": lo, "brk": brk, "tri": tri, "obos": obos,
            "div": dv["div"], "dfrom": dv["dfrom"], "dto": dv["dto"], "peak": peak}


def fusion(o, h, l, c, v, params=None) -> dict:
    """Price-volume wave (distance from the 21-bar VWMA in ATRs) vs an adaptive Kaufman line; MFI behind."""
    p = dict(PRO, **(params or {}))
    n = len(c)
    ap = [(h[i] + l[i] + c[i]) / 3 for i in range(n)]
    a, vw = atr_of(h, l, c, 21), [NAN] * n
    for i in range(20, n):
        s1 = s2 = 0.0
        for j in range(21):
            s1 += c[i - j] * v[i - j]
            s2 += v[i - j]
        if s2 > 0:
            vw[i] = s1 / s2
    dev = [(c[i] - vw[i]) / a[i] * 25 if _fin(vw[i]) and _fin(a[i]) and a[i] > 0 else NAN for i in range(n)]
    wave, kama = ema(dev, 5), [NAN] * n
    for i in range(10, n):
        if not (_fin(wave[i]) and _fin(wave[i - 10])):
            continue
        if not _fin(kama[i - 1]):
            kama[i] = wave[i]
            continue
        vol = 0.0
        for j in range(10):
            vol += abs(wave[i - j] - wave[i - j - 1])
        er = abs(wave[i] - wave[i - 10]) / vol if vol > 0 else 0.0
        sc0 = er * (2 / 3 - 2 / 31) + 2 / 31
        kama[i] = kama[i - 1] + sc0 * sc0 * (wave[i] - kama[i - 1])
    mfi_t = mfi_of(ap, v, 14)
    mfw = ema([(x - 50) * 2 if _fin(x) else NAN for x in mfi_t], 3)
    trend = [(1 if wave[i] > kama[i] else -1) if _fin(wave[i]) and _fin(kama[i]) else 0 for i in range(n)]
    strong = [1 if t != 0 and _fin(mfw[i]) and (mfw[i] > 0 if t > 0 else mfw[i] < 0) else 0 for i, t in enumerate(trend)]
    m20, s20 = sma(c, 20), std(c, 20)
    dot, diamond, runs, run = [0] * n, [0] * n, [], 0
    for i in range(n):
        if i > 0 and trend[i] != 0 and trend[i] == trend[i - 1]:
            run += 1
        else:
            if run > 0:
                runs.append(run)
            run = 1 if trend[i] != 0 else 0
        if i < 2 or not all(_fin(x) for x in (wave[i], wave[i - 1], wave[i - 2], m20[i], s20[i], mfi_t[i])) or s20[i] == 0:
            continue
        z = (c[i] - m20[i]) / s20[i]
        dn = wave[i] < wave[i - 1] and wave[i - 1] >= wave[i - 2]
        up_t = wave[i] > wave[i - 1] and wave[i - 1] <= wave[i - 2]
        if dn and z >= 2 and mfi_t[i] >= 65:
            dot[i] = -1                                     # regular bearish
        elif up_t and z <= -2 and mfi_t[i] <= 35:
            dot[i] = 1                                      # regular bullish
        elif dn and z >= 1.5:
            dot[i] = -2                                     # special bearish
        elif up_t and z <= -1.5:
            dot[i] = 2                                      # special bullish
        elif dn and wave[i] >= 60 and _fin(mfw[i]) and _fin(mfw[i - 1]) and mfw[i] < mfw[i - 1]:
            dot[i] = -3                                     # caution bearish
        if dot[i] in (1, -1) and len(runs) >= 5:            # diamond: regular dot after an unusually long run
            last = sorted(runs[-20:])
            if run >= 1.5 * last[len(last) // 2]:
                diamond[i] = dot[i]
    dv = divs(wave, h, l, p["pivot"], p["mindist"], p["maxdist"])
    return {"wave": wave, "kama": kama, "mfw": mfw, "trend": trend, "strong": strong, "dot": dot, "diamond": diamond,
            "div": dv["div"], "dfrom": dv["dfrom"], "dto": dv["dto"]}


def mvp(o, h, l, c, v, params=None) -> dict:
    """MACD normalised by its largest size over the last 100 bars (-100..100), EMA9 signal, bottom bars."""
    n = len(c)
    e12, e26, line = ema(c, 12), ema(c, 26), [NAN] * n
    macd = [e12[i] - e26[i] if _fin(e12[i]) and _fin(e26[i]) else NAN for i in range(n)]
    for i in range(n):
        if not _fin(macd[i]):
            continue
        mx, cnt = 0.0, 0
        for j in range(max(0, i - 99), i + 1):
            if _fin(macd[j]):
                mx = max(mx, abs(macd[j]))
                cnt += 1
        if cnt >= 50 and mx > 0:
            line[i] = 100 * macd[i] / mx
    sig, sigs = ema(line, 9), [0] * n
    for i in range(1, n):
        if all(_fin(x) for x in (line[i], line[i - 1], sig[i], sig[i - 1])):
            if line[i - 1] <= sig[i - 1] and line[i] > sig[i] and line[i] < -40:
                sigs[i] = 1
            elif line[i - 1] >= sig[i - 1] and line[i] < sig[i] and line[i] > 40:
                sigs[i] = -1
    va = sma(v, 50)
    relv = [min(3.0, x / va[i]) if _fin(va[i]) and va[i] > 0 else NAN for i, x in enumerate(v)]
    m20, s20, r, bs = sma(c, 20), std(c, 20), rsi_of(c, 14), [0] * n
    for i in range(n):
        if not all(_fin(x) for x in (m20[i], s20[i], r[i])) or s20[i] == 0:
            continue
        z = (c[i] - m20[i]) / s20[i]
        if z < -1:
            bs[i] = min(1.0, (-z - 1) / 1.5) * (1 if r[i] < 40 else 0.5)
    return {"line": line, "sig": sig, "sigs": sigs, "relv": relv, "bs": bs}
