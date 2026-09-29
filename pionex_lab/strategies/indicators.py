"""O(n) indicator arrays over completed bars. NaN marks insufficient history."""
from __future__ import annotations

import math
from collections import deque

NAN = float("nan")


def ema(x, n):
    out, k, prev = [NAN] * len(x), 2.0 / (n + 1), None
    for i, v in enumerate(x):
        if i + 1 < n:
            continue
        if prev is None:
            prev = sum(x[i + 1 - n:i + 1]) / n
        else:
            prev = v * k + prev * (1 - k)
        out[i] = prev
    return out


def sma(x, n):
    out, s = [NAN] * len(x), 0.0
    for i, v in enumerate(x):
        s += v
        if i >= n:
            s -= x[i - n]
        if i + 1 >= n:
            out[i] = s / n
    return out


def rolling_std(x, n):
    out = [NAN] * len(x)
    s = s2 = 0.0
    for i, v in enumerate(x):
        s += v
        s2 += v * v
        if i >= n:
            s -= x[i - n]
            s2 -= x[i - n] ** 2
        if i + 1 >= n:
            var = max(0.0, s2 / n - (s / n) ** 2)
            out[i] = math.sqrt(var)
    return out


def atr(h, l, c, n=14):
    """Wilder's average true range."""
    out, prev = [NAN] * len(c), None
    trs = []
    for i in range(len(c)):
        tr = h[i] - l[i] if i == 0 else max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
        trs.append(tr)
        if i + 1 == n:
            prev = sum(trs) / n
            out[i] = prev
        elif i + 1 > n:
            prev = (prev * (n - 1) + tr) / n
            out[i] = prev
    return out


def rsi(c, n=14):
    out = [NAN] * len(c)
    gain = loss = 0.0
    for i in range(1, len(c)):
        d = c[i] - c[i - 1]
        g, lo = max(d, 0.0), max(-d, 0.0)
        if i <= n:
            gain += g
            loss += lo
            if i == n:
                gain /= n
                loss /= n
            else:
                continue
        else:
            gain = (gain * (n - 1) + g) / n
            loss = (loss * (n - 1) + lo) / n
        out[i] = 100.0 if loss == 0 else 100.0 - 100.0 / (1 + gain / loss)
    return out


def prior_max(x, n):
    """max(x[i-n:i]) — excludes the current bar."""
    out, dq = [NAN] * len(x), deque()
    for i in range(len(x)):
        while dq and dq[0] < i - n:
            dq.popleft()
        if i >= n:
            out[i] = x[dq[0]]
        while dq and x[dq[-1]] <= x[i]:
            dq.pop()
        dq.append(i)
    return out


def prior_min(x, n):
    neg = prior_max([-v for v in x], n)
    return [-v if not math.isnan(v) else NAN for v in neg]


def efficiency_ratio(c, n):
    """|net change| / path length over n bars: ~1 trending, ~0 choppy."""
    out = [NAN] * len(c)
    path = 0.0
    for i in range(1, len(c)):
        path += abs(c[i] - c[i - 1])
        if i > n:
            path -= abs(c[i - n] - c[i - n - 1])
        if i >= n and path > 0:
            out[i] = abs(c[i] - c[i - n]) / path
    return out


def rolling_vwap(h, l, c, v, n):
    out = [NAN] * len(c)
    pv = vol = 0.0
    tp = [(h[i] + l[i] + c[i]) / 3 for i in range(len(c))]
    for i in range(len(c)):
        pv += tp[i] * v[i]
        vol += v[i]
        if i >= n:
            pv -= tp[i - n] * v[i - n]
            vol -= v[i - n]
        if i + 1 >= n and vol > 0:
            out[i] = pv / vol
    return out


def percentile_rank(x, n):
    """Fraction of the previous n finite values strictly below x[i]."""
    out = [NAN] * len(x)
    for i in range(n, len(x)):
        if math.isnan(x[i]):
            continue
        window = [w for w in x[i - n:i] if not math.isnan(w)]
        if len(window) >= n // 2:
            out[i] = sum(1 for w in window if w < x[i]) / len(window)
    return out


def finite(*vals) -> bool:
    return all(v is not None and not math.isnan(v) for v in vals)
