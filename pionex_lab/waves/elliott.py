"""Automatic Elliott Wave counting over OHLC bars. Standard library only.

Pipeline: zigzag swing pivots (reversal threshold scaled to typical bar range per degree)
-> candidate 5-wave impulses and A-B-C corrections over consecutive pivots -> hard Elliott
rules filter candidates, guideline ratios score them -> the best count ending at the latest
swing is the primary count, the next best are alternates -> Fibonacci targets, invalidation
level, Elliott channels and pivot-cluster support/resistance for the chart.

Counts are pattern hypotheses with known subjectivity. A high score means the swing ratios
resemble textbook guidelines; it is not a probability and not evidence of profitability.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

FIB_RETRACE = (0.236, 0.382, 0.5, 0.618, 0.786)
FIB_EXTEND = (0.618, 1.0, 1.272, 1.618, 2.0, 2.618)
# Zigzag reversal threshold = median bar range (%) x multiplier.
DEGREES = {"minor": 3.0, "intermediate": 6.0, "primary": 12.0}
IMPULSE_LABELS = ("0", "1", "2", "3", "4", "5")
CORRECTION_LABELS = ("0", "A", "B", "C")


@dataclass(frozen=True)
class Pivot:
    i: int
    price: float
    kind: str        # "H" swing high, "L" swing low
    confirmed: bool  # False for the latest extreme, which has not reversed by the threshold yet


def zigzag(h, l, pct: float) -> list[Pivot]:
    """Alternating swing pivots. A swing is confirmed once price reverses by `pct` (fraction)
    from its extreme; the final extreme is returned unconfirmed."""
    n = len(h)
    if n < 2 or pct <= 0:
        return []
    pivots: list[Pivot] = []
    trend, hi, lo, ext = 0, 0, 0, 0
    for i in range(1, n):
        if trend == 0:
            if h[i] > h[hi]:
                hi = i
            if l[i] < l[lo]:
                lo = i
            if h[hi] >= l[lo] * (1 + pct):
                if lo < hi:
                    pivots.append(Pivot(lo, l[lo], "L", True))
                    trend, ext = 1, hi
                else:
                    pivots.append(Pivot(hi, h[hi], "H", True))
                    trend, ext = -1, lo
        elif trend == 1:
            if h[i] >= h[ext]:
                ext = i
            elif l[i] <= h[ext] * (1 - pct):
                pivots.append(Pivot(ext, h[ext], "H", True))
                trend, ext = -1, i
        else:
            if l[i] <= l[ext]:
                ext = i
            elif h[i] >= l[ext] * (1 + pct):
                pivots.append(Pivot(ext, l[ext], "L", True))
                trend, ext = 1, i
    if trend == 1:
        pivots.append(Pivot(ext, h[ext], "H", False))
    elif trend == -1:
        pivots.append(Pivot(ext, l[ext], "L", False))
    return pivots


def auto_threshold(h, l, c, degree: str = "intermediate", lookback: int = 200) -> float:
    """Reversal fraction for a degree: median bar range over the lookback times the degree
    multiplier, clamped to [0.2%, 50%]."""
    mult = DEGREES.get(degree)
    if mult is None:
        raise ValueError(f"unknown degree {degree}")
    start = max(0, len(c) - lookback)
    ranges = sorted((h[i] - l[i]) / c[i] for i in range(start, len(c)) if c[i] > 0)
    med = ranges[len(ranges) // 2] if ranges else 0.01
    return min(0.5, max(0.002, med * mult))


def _round(x: float, nd: int) -> float:
    """Round half up, identically to wavelab/engine.js (Python's round() is half-even)."""
    k = 10 ** nd
    return math.floor(x * k + 0.5) / k


def _band(x: float, lo: float, hi: float) -> float:
    """1 inside [lo, hi], decaying with log-distance outside it."""
    if x <= 0 or not math.isfinite(x):
        return 0.0
    if lo <= x <= hi:
        return 1.0
    d = math.log(lo / x) if x < lo else math.log(x / hi)
    return max(0.0, 1.0 - d / math.log(2.0))


def _norm(prices, up: bool):
    return list(prices) if up else [-p for p in prices]


def check_impulse(prices, up: bool):
    """Rules and guidelines for a (possibly partial) impulse given 3..6 pivot prices starting at
    the origin of wave 1. Returns (rules, guidelines) as lists of (text, value)."""
    q = _norm(prices, up)
    n = len(q)
    w = [q[k + 1] - q[k] if k % 2 == 0 else q[k] - q[k + 1] for k in range(n - 1)]  # lengths, positive
    rules, guides = [], []
    if n >= 3:
        rules.append(("Wave 2 does not retrace beyond the start of wave 1", q[2] > q[0]))
        guides.append(("Wave 2 retraces 38.2%-78.6% of wave 1", _band(w[1] / w[0], 0.382, 0.786)))
    if n >= 4:
        rules.append(("Wave 3 travels beyond the end of wave 1", q[3] > q[1]))
        guides.append(("Wave 3 is 1.382-2.618 x wave 1", _band(w[2] / w[0], 1.382, 2.618)))
    if n >= 5:
        rules.append(("Wave 4 does not overlap wave 1", q[4] > q[1]))
        guides.append(("Wave 4 retraces 23.6%-50% of wave 3", _band(w[3] / w[2], 0.236, 0.5)))
        r2, r4 = w[1] / w[0], w[3] / w[2]
        guides.append(("Waves 2 and 4 alternate in depth", min(1.0, abs(r2 - r4) / 0.2)))
    if n >= 6:
        rules.append(("Wave 3 is not the shortest of waves 1, 3, 5", not (w[2] < w[0] and w[2] < w[4])))
        rules.append(("Wave 5 travels beyond the end of wave 3 (no truncation)", q[5] > q[3]))
        guides.append(("Wave 5 is 0.618-1.618 x wave 1", _band(w[4] / w[0], 0.618, 1.618)))
    return rules, guides


def check_correction(prices, down: bool):
    """Rules/guidelines for an A-B-C correction (3..4 pivot prices from the start of A).
    `down` means wave A falls. Returns (kind, rules, guidelines)."""
    q = _norm(prices, down)  # normalised so wave A falls
    a = q[0] - q[1]
    b = q[2] - q[1]
    rb = b / a
    kind = "zigzag" if rb < 0.9 else ("expanded flat" if rb > 1.0 else "flat")
    rules, guides = [], []
    if kind == "zigzag":
        rules.append(("Wave B does not retrace beyond the start of wave A", q[2] < q[0]))
        guides.append(("Wave B retraces 38.2%-78.6% of wave A", _band(rb, 0.382, 0.786)))
    else:
        rules.append(("Wave B retraces at most 138.2% of wave A", rb <= 1.382))
        guides.append(("Wave B retraces 90%-123.6% of wave A", _band(rb, 0.9, 1.236)))
    if len(q) >= 4:
        c = q[2] - q[3]
        if kind == "zigzag":
            rules.append(("Wave C travels beyond the end of wave A", q[3] < q[1]))
            guides.append(("Wave C is 0.618-1.618 x wave A", _band(c / a, 0.618, 1.618)))
        else:
            rules.append(("Wave C reaches at least 80% of wave A", c >= 0.8 * a))
            guides.append(("Wave C is 1.0-1.618 x wave A", _band(c / a, 1.0, 1.618)))
    return kind, rules, guides


def _score(rules, guides) -> float:
    if not all(ok for _, ok in rules) or not guides:
        return 0.0
    return _round(100.0 * sum(v for _, v in guides) / len(guides), 1)


def _levels(base: float, length: float, ratios, sign: float, kind: str, ref: str):
    return [{"ratio": r, "price": base + sign * r * length, "kind": kind, "ref": ref} for r in ratios]


def _targets(kind: str, labels, prices, up: bool):
    """Fibonacci targets and invalidation for the wave in progress (the last label)."""
    s = 1.0 if up else -1.0
    p = prices
    last = labels[-1]
    if kind == "impulse":
        w1 = abs(p[1] - p[0])
        if last == "2":
            return (_levels(p[1], w1, (0.5, 0.618, 0.786), -s, "retracement", "wave 1"), p[0],
                    "Wave 2 correcting wave 1; wave 3 expected next")
        if last == "3":
            return (_levels(p[2], w1, (1.0, 1.618, 2.618), s, "extension", "wave 1 from end of 2"), p[0],
                    "Wave 3 in progress")
        if last == "4":
            w3 = abs(p[3] - p[2])
            return (_levels(p[3], w3, (0.236, 0.382, 0.5), -s, "retracement", "wave 3"), p[1],
                    "Wave 4 correcting wave 3; wave 5 expected next")
        if last == "5":
            w13 = abs(p[3] - p[0])
            tg = (_levels(p[4], w1, (0.618, 1.0), s, "extension", "wave 1 from end of 4")
                  + _levels(p[4], w13, (0.618,), s, "extension", "waves 1-3 from end of 4"))
            return tg, p[1], "Wave 5 in progress; an A-B-C correction usually follows"
    else:
        wa = abs(p[1] - p[0])
        if last == "B":
            return (_levels(p[1], wa, (0.5, 0.618, 0.786), -s, "retracement", "wave A"), p[0],
                    "Wave B retracing wave A; wave C expected next")
        if last == "C":
            return (_levels(p[2], wa, (0.618, 1.0, 1.618), s, "extension", "wave A from end of B"), p[2],
                    "Wave C in progress; the prior trend may resume after it")
    return [], None, ""


# Time reference for the wave in progress: the wave whose duration the current one is compared with.
ZONE_REF = {"2": "1", "3": "1", "4": "2", "5": "1", "B": "A", "C": "A"}
ZONE_TIME = (0.618, 1.618)


def _zone(labels, seg, t, targets):
    """Projected end zone of the wave in progress: a price band spanning its Fibonacci targets and a
    time window of 0.618-1.618x the reference wave's duration, from the start of the current wave."""
    last = labels[-1]
    ref = ZONE_REF.get(last)
    if not targets or ref is None or ref not in labels:
        return None
    j = labels.index(ref)
    if j < 1:
        return None
    dur = t[seg[j].i] - t[seg[j - 1].i]
    start = t[seg[-2].i]
    prices = [x["price"] for x in targets]
    return {"price_lo": min(prices), "price_hi": max(prices), "t_from": start + ZONE_TIME[0] * dur,
            "t_to": start + ZONE_TIME[1] * dur, "wave": last, "time_ref": ref}


def _channels(kind: str, pts):
    """Elliott channels as point pairs (index, price): a base line and its parallel."""
    out = []

    def parallel(a, b, through, name):
        slope = (b[1] - a[1]) / (b[0] - a[0]) if b[0] != a[0] else 0.0
        out.append({"name": name, "base": [a, b],
                    "parallel": [through, (through[0] + (b[0] - a[0]), through[1] + slope * (b[0] - a[0]))]})

    if kind == "impulse":
        if len(pts) == 4:  # 0-2 line, parallel through 1: projects wave 3
            parallel(pts[0], pts[2], pts[1], "0-2 channel")
        elif len(pts) >= 5:  # 2-4 line, parallel through 3: projects wave 5
            parallel(pts[2], pts[4], pts[3], "2-4 channel")
    elif len(pts) >= 3:  # 0-B line, parallel through A: projects wave C
        parallel(pts[0], pts[2], pts[1], "A-C channel")
    return out


def _candidates(pivots: list[Pivot], end: int, min_len: int):
    """Impulse/correction candidates over pivots[start..end] (inclusive) with >= min_len pivots."""
    out = []
    for size in range(min_len, 7):
        start = end - size + 1
        if start < 0:
            continue
        seg = pivots[start:end + 1]
        prices = [p.price for p in seg]
        up = seg[0].kind == "L"
        rules, guides = check_impulse(prices, up)
        sc = _score(rules, guides)
        if sc > 0:
            out.append(("impulse", None, seg, up, rules, guides, sc))
    for size in (3, 4):
        start = end - size + 1
        if start < 0:
            continue
        seg = pivots[start:end + 1]
        down = seg[0].kind == "H"
        sub, rules, guides = check_correction([p.price for p in seg], down)
        sc = _score(rules, guides)
        if sc > 0:
            out.append(("correction", sub, seg, not down, rules, guides, sc))
    return out


def _count_json(cand, t, current_price):
    kind, sub, seg, up, rules, guides, score = cand
    labels = (IMPULSE_LABELS if kind == "impulse" else CORRECTION_LABELS)[:len(seg)]
    prices = [p.price for p in seg]
    targets, invalid, status = _targets(kind, labels, prices, up)
    # Completeness: a longer structure explains more of the move. 5 waves > 3 > partials.
    weight = {3: 0.70, 4: 0.85, 5: 0.93, 6: 1.0}[len(seg)] if kind == "impulse" else {3: 0.70, 4: 0.95}[len(seg)]
    broken = invalid is not None and ((current_price < invalid) if up else (current_price > invalid))
    # The wave in progress moves with the structure on 1/3/5/A/C and against it on 2/4/B.
    with_trend = labels[-1] in ("1", "3", "5", "A", "C")
    return {
        "type": kind if sub is None else f"{kind} ({sub})",
        "direction": "bullish" if up else "bearish",
        "trend": "up" if up else "down",
        "move": "up" if up == with_trend else "down",
        "complete": len(seg) == len(labels) and labels[-1] in ("5", "C") and seg[-1].confirmed,
        "current_wave": labels[-1],
        "status": status,
        "waves": [{"label": lab, "i": p.i, "t": t[p.i], "price": p.price, "confirmed": p.confirmed}
                  for lab, p in zip(labels, seg)],
        "rules": [{"text": tx, "ok": bool(ok)} for tx, ok in rules],
        "guidelines": [{"text": tx, "fit": _round(v, 2)} for tx, v in guides],
        "score": _round(score * weight, 1),
        "targets": targets,
        "zone": _zone(labels, seg, t, targets),
        "invalidation": invalid,
        "invalidated": bool(broken),
        "channels": [{"name": ch["name"],
                      "base": [{"t": t[a[0]], "i": a[0], "price": a[1]} for a in ch["base"]],
                      "parallel": [{"i": a[0], "price": a[1]} for a in ch["parallel"]]}
                     for ch in _channels(kind, [(p.i, p.price) for p in seg])],
    }


def support_resistance(h, l, c, max_levels: int = 8):
    """Pivot clusters across all degrees. Touches within half a median bar range merge."""
    if len(c) < 10:
        return []
    seen = {}
    for deg in DEGREES:  # the same swing found at several degrees counts once
        for p in zigzag(h, l, auto_threshold(h, l, c, deg)):
            if p.confirmed:
                seen[(p.i, p.kind)] = p.price
    prices = [(price, kind) for (_, kind), price in seen.items()]
    if not prices:
        return []
    tol = auto_threshold(h, l, c, "minor") / 6.0  # half the median bar range
    prices.sort()
    clusters = []
    for price, kind in prices:
        if clusters and price <= clusters[-1]["hi"] * (1 + tol):
            cl = clusters[-1]
            cl["sum"] += price
            cl["n"] += 1
            cl["hi"] = price
            cl["kinds"].add(kind)
        else:
            clusters.append({"sum": price, "n": 1, "hi": price, "kinds": {kind}})
    last = c[-1]
    out = [{"price": cl["sum"] / cl["n"], "touches": cl["n"],
            "kind": "resistance" if cl["sum"] / cl["n"] > last else "support"}
           for cl in clusters if cl["n"] >= 2]
    out.sort(key=lambda x: (-x["touches"], abs(x["price"] - last)))
    return sorted(out[:max_levels], key=lambda x: x["price"])


def wave_oscillator(h, l, fast: int = 5, slow: int = 35):
    """Elliott Wave Oscillator: SMA(fast) - SMA(slow) of the median price (None while warming up)."""
    m = [(a + b) / 2 for a, b in zip(h, l)]
    out = []
    sf = ss = 0.0
    for i, v in enumerate(m):
        sf += v
        ss += v
        if i >= fast:
            sf -= m[i - fast]
        if i >= slow:
            ss -= m[i - slow]
        out.append(sf / fast - ss / slow if i + 1 >= slow else None)
    return out


def analyze(t, o, h, l, c, degree: str = "intermediate", pct: float | None = None,
            max_alternates: int = 3, history: bool = True) -> dict:
    """Full analysis for one series. Bars are parallel lists (oldest first)."""
    n = len(c)
    if n < 20:
        return {"degree": degree, "threshold": None, "pivots": [], "primary": None, "alternates": [],
                "history": [], "levels": [], "note": "not enough bars"}
    thr = pct if pct else auto_threshold(h, l, c, degree)
    pivots = zigzag(h, l, thr)
    last = c[-1]
    counts = []
    if len(pivots) >= 3:
        for cand in _candidates(pivots, len(pivots) - 1, 3):
            counts.append(_count_json(cand, t, last))
    # Counts that end one pivot earlier describe a structure that has just finished; the latest
    # swing is the first wave of what follows. Shown only as alternates.
    if len(pivots) >= 5:
        for cand in _candidates(pivots, len(pivots) - 2, 4):
            kind, seg = cand[0], cand[2]
            if not ((kind == "impulse" and len(seg) == 6) or (kind == "correction" and len(seg) == 4)):
                continue
            cj = _count_json(cand, t, last)
            done5 = kind == "impulse"
            cj["status"] = ("Five waves complete; the latest swing may be wave A of a correction" if done5
                            else "A-B-C complete; the latest swing may start a new trend")
            cj["current_wave"] = "A" if done5 else "1"
            cj["move"] = "down" if cj["trend"] == "up" else "up"
            cj["targets"], cj["invalidation"], cj["invalidated"] = _post_targets(cj), None, False
            cj["zone"] = None
            cj["channels"] = []
            cj["score"] = _round(cj["score"] * 0.97, 1)
            counts.append(cj)
    valid = [x for x in counts if not x["invalidated"]]
    valid.sort(key=lambda x: -x["score"])
    seen, ranked = set(), []
    for x in valid:
        key = (x["type"], x["waves"][0]["i"], len(x["waves"]))
        if key not in seen:
            seen.add(key)
            ranked.append(x)
    primary = ranked[0] if ranked else None
    alternates = ranked[1:1 + max_alternates]
    hist = _history(pivots, t, last, primary) if history else []
    return {
        "degree": degree, "threshold": thr,
        "pivots": [{"i": p.i, "t": t[p.i], "price": p.price, "kind": p.kind, "confirmed": p.confirmed}
                   for p in pivots],
        "primary": primary, "alternates": alternates, "history": hist,
        "levels": support_resistance(h, l, c),
        "note": "Wave counts are pattern hypotheses, not forecasts or evidence of an edge.",
    }


def _post_targets(cj):
    """After a completed structure: retracement levels of the whole structure."""
    w = cj["waves"]
    start, end = w[0]["price"], w[-1]["price"]
    length = abs(end - start)
    sign = -1.0 if end > start else 1.0
    return _levels(end, length, (0.382, 0.5, 0.618), sign, "retracement", "completed structure")


def _history(pivots, t, last, primary):
    """Greedy non-overlapping complete impulses/corrections earlier in the series."""
    taken = []
    if primary:
        taken.append((primary["waves"][0]["i"], primary["waves"][-1]["i"]))
    cands = []
    for end in range(3, len(pivots) - 1):
        for cand in _candidates(pivots, end, 4):
            kind, _, seg = cand[0], cand[1], cand[2]
            if (kind == "impulse" and len(seg) == 6) or (kind == "correction" and len(seg) == 4):
                cands.append(cand)
    cands.sort(key=lambda x: -x[6])
    out = []
    for cand in cands:
        a, b = cand[2][0].i, cand[2][-1].i
        if any(not (b <= x0 or a >= x1) for x0, x1 in taken):
            continue
        taken.append((a, b))
        cj = _count_json(cand, t, last)
        out.append({k: cj[k] for k in ("type", "direction", "waves", "score")})
        if len(out) >= 8:
            break
    return sorted(out, key=lambda x: x["waves"][0]["i"])


def scan_summary(symbol: str, interval: str, analysis: dict, last: float) -> dict:
    """One scanner row (wave setup) from an analysis."""
    p = analysis.get("primary")
    row = {"symbol": symbol, "interval": interval, "degree": analysis.get("degree"), "last": last,
           "pattern": None, "direction": None, "move": None, "current_wave": None, "status": "no valid count",
           "score": 0.0, "next_target": None, "invalidation": None, "risk_pct": None}
    if not p:
        return row
    row.update(pattern=p["type"], direction=p["direction"], move=p["move"], current_wave=p["current_wave"],
               status=p["status"], score=p["score"], invalidation=p["invalidation"])
    up = p["move"] == "up"
    ahead = [x["price"] for x in p["targets"] if (x["price"] > last if up else x["price"] < last)]
    if ahead:
        row["next_target"] = min(ahead, key=lambda v: abs(v - last))
    if p["invalidation"]:
        row["risk_pct"] = _round(abs(last - p["invalidation"]) / last * 100.0, 2)
    return row
