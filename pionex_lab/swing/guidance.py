"""Forward-only record of the user's YouTube channels' BTC calls, scored against what BTC then did.

The user's instruction (2026-10-13): do not test the channels on past data; start from today, BTC
only, as guidance. So a call is written down once, on or after the day it is published, and only
Pionex BTC_USDT 1h candles that open after it was recorded are used to score it. Nothing here places,
previews or suggests orders.

A call holds what the channel said about BTC for the next few days:
  bias          LONG / SHORT / NEUTRAL lean over 1-3 days
  long_zones    [[low, high], ...] areas where they would buy
  short_zones   [[low, high], ...] areas where they would sell
  triggers      [{"close_above"|"close_below": level, "side": "LONG"|"SHORT"}] conditional calls
  targets       [{"price": p, "side": "LONG"|"SHORT"}] levels they expect to be reached

Scoring (futures taker fee 5 bps a side, no leverage, no funding):
  bias      BTC return 24/48/72h after recording, signed by the bias, minus fees
  zones     first touch within 72h fills a limit at the zone edge (or the open if already through);
            result = close 24h later vs the fill, signed, minus fees; plus the worst move against it
  triggers  first 1h close beyond the level within 72h; result = close 24h later, signed, minus fees
  targets   reached (by high/low) within 72h or not
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

FORWARD_START = "2026-10-13T00:00:00+00:00"   # the user's "start from today"
SOURCES = ("More Crypto Online", "Daily Entry", "Chart Hackers", "Owner", "Crypto Banter", "Crypto Decoded", "Firm")
SAME_PRESENTER = ("Daily Entry", "Chart Hackers")   # both Dylan: not independent opinions
SIDES = {"LONG": 1, "SHORT": -1}
FEE_BPS = 5
HORIZONS = (24, 48, 72)
LIVE_H = 72                                   # zones, triggers and targets expire 72h after recording
FOLLOW_H = 24
H = 3_600_000


def _ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="minutes")


def validate(c: dict) -> dict:
    for k in ("source", "video_id", "title", "published", "recorded", "bias"):
        if not c.get(k):
            raise ValueError(f"call needs {k}")
    if c["source"] not in SOURCES:
        raise ValueError(f"unknown source {c['source']!r}")
    if c["bias"] not in ("LONG", "SHORT", "NEUTRAL"):
        raise ValueError("bias must be LONG, SHORT or NEUTRAL")
    if _ms(c["recorded"]) < _ms(FORWARD_START) or _ms(c["recorded"]) < _ms(c["published"]):
        raise ValueError("calls are recorded forward only: on/after 2026-10-13 and after publication")
    for key in ("long_zones", "short_zones"):
        for z in c.get(key, []):
            if len(z) != 2 or not 0 < z[0] <= z[1]:
                raise ValueError(f"{key}: {z} is not [low, high]")
    for t in c.get("triggers", []):
        if t.get("side") not in SIDES or len([k for k in t if k in ("close_above", "close_below")]) != 1:
            raise ValueError(f"bad trigger {t}")
    for t in c.get("targets", []):
        if t.get("side") not in SIDES or not t.get("price", 0) > 0:
            raise ValueError(f"bad target {t}")
    return c


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def add(path: Path, calls: list[dict]) -> int:
    """Append new calls (one per source and video); never rewrites earlier records."""
    have = {(c["source"], c["video_id"]) for c in load(path)}
    new = [validate(c) for c in calls if (c["source"], c["video_id"]) not in have]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        for c in new:
            f.write(json.dumps(c, sort_keys=True) + "\n")
    return len(new)


def _follow(after, k, px, side):
    """Signed net bps 24h after an entry at bar k, and the worst move against it meanwhile."""
    if len(after) - k < FOLLOW_H:
        return None
    rest = after[k:k + FOLLOW_H]
    worst = min(b[3] for b in rest) if side > 0 else max(b[2] for b in rest)
    return {"net_bps": round(side * (rest[-1][4] / px - 1) * 1e4 - 2 * FEE_BPS, 1),
            "worst_bps": round(side * (worst / px - 1) * 1e4, 1)}


def score_call(c: dict, bars: list[tuple]) -> dict:
    """bars: sorted 1h (open_ms, open, high, low, close) floats."""
    after = [b for b in bars if b[0] >= _ms(c["recorded"])]
    out = {"source": c["source"], "video_id": c["video_id"], "recorded": c["recorded"], "bias": c["bias"]}
    if not after:
        return {**out, "status": "pending"}
    entry, live = after[0][1], after[:LIVE_H]
    done = len(after) >= LIVE_H + FOLLOW_H
    out.update(entry=entry, status="final" if done else "running")
    side = SIDES.get(c["bias"], 0)
    for h in HORIZONS:
        if len(after) >= h:
            ret = (after[h - 1][4] / entry - 1) * 1e4
            out[f"ret_{h}h_bps"] = round(ret, 1)
            if side:
                out[f"bias_{h}h_net_bps"] = round(side * ret - 2 * FEE_BPS, 1)
    zones = []
    for key, zside in (("long_zones", 1), ("short_zones", -1)):
        for lo, hi in c.get(key, []):
            z = {"side": "LONG" if zside > 0 else "SHORT", "zone": [lo, hi]}
            for k, b in enumerate(live):
                if (zside > 0 and b[3] <= hi) or (zside < 0 and b[2] >= lo):
                    px = min(b[1], hi) if zside > 0 else max(b[1], lo)
                    z.update(filled=_iso(b[0]), fill=px)
                    z.update(_follow(after, k, px, zside) or {})
                    break
            else:
                z["filled"] = None if len(after) >= LIVE_H else "open"
            zones.append(z)
    trig = []
    for t in c.get("triggers", []):
        above = "close_above" in t
        level, tside = t.get("close_above", t.get("close_below")), SIDES[t["side"]]
        r = {"trigger": ("close_above " if above else "close_below ") + str(level), "side": t["side"]}
        for k, b in enumerate(live):
            if (above and b[4] > level) or (not above and b[4] < level):
                r["fired"] = _iso(b[0] + H)
                nxt = after[k + 1][1] if k + 1 < len(after) else None   # act on the next bar's open
                if nxt:
                    r["entry"] = nxt
                    r.update(_follow(after, k + 1, nxt, tside) or {})
                break
        else:
            r["fired"] = None if len(after) >= LIVE_H else "open"
        trig.append(r)
    targets = []
    for t in c.get("targets", []):
        p = t["price"]
        hit = next((b[0] for b in live if (b[2] >= p if t["side"] == "LONG" else b[3] <= p)), None)
        targets.append({"price": p, "side": t["side"],
                        "reached": _iso(hit) if hit else (None if len(after) >= LIVE_H else "open")})
    return {**out, "zones": zones, "triggers": trig, "targets": targets}


def summarize(scored: list[dict]) -> dict:
    def agg(rows):
        def stat(vals):
            vals = [v for v in vals if v is not None]
            return {"n": len(vals), "mean_net_bps": round(sum(vals) / len(vals), 1) if vals else None,
                    "win_rate": round(sum(v > 0 for v in vals) / len(vals), 2) if vals else None}
        out = {f"bias_{h}h": stat([r.get(f"bias_{h}h_net_bps") for r in rows]) for h in HORIZONS}
        out["zones"] = stat([z.get("net_bps") for r in rows for z in r.get("zones", [])])
        out["triggers"] = stat([t.get("net_bps") for r in rows for t in r.get("triggers", [])])
        tg = [t for r in rows for t in r.get("targets", []) if t["reached"] != "open"]
        out["targets"] = {"n": len(tg), "reached": sum(1 for t in tg if t["reached"])}
        out["calls"] = len(rows)
        return out
    return {"all": agg(scored), "by_source": {s: agg([r for r in scored if r["source"] == s]) for s in SOURCES}}


def fetch_bars(client=None, since_ms: int = 0) -> list[tuple]:
    from ..exchange.pionex_public import ExchangeError, PionexPublic
    client = client or PionexPublic()
    bars, end = {}, None
    for _ in range(40):                                              # 40 x 500h covers > 2 years
        try:
            kl, _ = client.klines("BTC_USDT", "60M", end_time=end, limit=500)
        except ExchangeError:
            if end is None:
                raise
            break                                                    # past the venue's history limit
        for k in kl:
            bars[k.open_time] = (k.open_time, float(k.open), float(k.high), float(k.low), float(k.close), float(k.volume))
        first = min((k.open_time for k in kl), default=None)
        if first is None or first <= since_ms or (end is not None and first > end):
            break
        end = first - 1
    now = datetime.now(timezone.utc).timestamp() * 1000
    return sorted(b for t, b in bars.items() if t + H <= now)        # closed candles only


def oscillator_forward(bars: list[tuple]) -> dict:
    """WL Oscillator diamonds on Pionex BTC 4h that close after FORWARD_START, traded with the v2 rules
    (swing/osc_study.py: stop beyond 5 bars, half at 1.5R then stop to entry, rest at 3R or 30 bars).
    The backtest had only 20 such BTC 4h trades, so they are tracked forward from 2026-10-13. No funding."""
    from ..data.store import Bars, resample
    from ..waves.oscillator import calc
    from .osc_study import simulate_v2
    if len(bars) < 500:
        return {"diamonds": [], "trades": []}
    b1 = Bars("BTC_USDT", "60M", *[list(x) for x in zip(*bars)])
    b4 = resample(b1, "4H")
    r = calc(list(b4.o), list(b4.h), list(b4.l), list(b4.c), list(b4.v))
    start = _ms(FORWARD_START)
    marks = [{"bar_close": _iso(b4.t[i] + 4 * H), "side": "LONG" if r["diamond"][i] > 0 else "SHORT"}
             for i in range(len(b4)) if r["diamond"][i] and b4.t[i] + 4 * H > start]
    keep = {k: [x if b4.t[i] + 4 * H > start else 0 for i, x in enumerate(v)] if k == "diamond" else v for k, v in r.items()}
    last = b1.t[-1] + H
    trades = [{**t, "entry": _iso(t["entry_time"]), "exit": _iso(t["exit_time"]),
               "status": "running" if t["exit_time"] >= last and t["entry_time"] + 30 * 4 * H > last else "closed"}
              for t in simulate_v2(b4, b1, keep, "diamond")]
    return {"diamonds": marks, "trades": trades, "summary": summarize_trades([t for t in trades if t["status"] == "closed"])}


def trend_forward(client=None, now_ms: int | None = None) -> dict:
    """Daily EMA50 trend filter (swing/trend.py; passed v1 and the 2017-2023 out-of-sample check) on
    Pionex's own daily candles: today's state, last flip, and the paper result of following it since
    FORWARD_START (spot, unleveraged, 7 bps a side). Watch-only: nothing is ordered."""
    from ..data.store import Bars
    from ..exchange.pionex_public import PionexPublic
    from ..strategies.indicators import ema
    from .trend import backtest, positions
    client = client or PionexPublic()
    now_ms = now_ms or int(datetime.now(timezone.utc).timestamp() * 1000)
    out = {}
    for sym in ("BTC_USDT", "ETH_USDT"):
        kl, _ = client.klines(sym, "1D", limit=500)
        kl = sorted((k for k in kl if k.open_time + 24 * H <= now_ms), key=lambda k: k.open_time)
        if len(kl) < 60:
            out[sym] = {"error": "not enough daily candles"}
            continue
        d = Bars(sym, "1D", [k.open_time for k in kl], *[[float(getattr(k, f)) for k in kl]
                                                       for f in ("open", "high", "low", "close", "volume")])
        e, pos = ema(d.c, 50), positions(d.c, "ema50")
        flips = [i for i in range(1, len(pos)) if pos[i] != pos[i - 1]]
        start = next((i for i, t in enumerate(d.t) if t >= _ms(FORWARD_START)), len(d))
        fwd = backtest(d, "ema50", start=start) if len(d) - start >= 3 else None
        out[sym] = {"day": _iso(d.t[-1])[:10], "close": d.c[-1], "ema50": e[-1],
                    "state": "IN (long spot)" if pos[-1] else "OUT (cash)",
                    "distance_pct": round((d.c[-1] / e[-1] - 1) * 100, 2),
                    "last_flip": _iso(d.t[flips[-1]])[:10] if flips else None,
                    "flipped_on_last_close": bool(flips and flips[-1] == len(pos) - 1),
                    "since_forward_start": None if not fwd else {k: fwd[k] for k in ("total", "max_drawdown", "switches", "days")}}
    return out


def summarize_trades(trades: list[dict]) -> dict:
    vals = [t["net_bps"] for t in trades]
    return {"n": len(vals), "mean_net_bps": round(sum(vals) / len(vals), 1) if vals else None,
            "win_rate": round(sum(v > 0 for v in vals) / len(vals), 2) if vals else None}


def run(paths) -> dict:
    calls = load(paths.root / "guidance" / "btc_calls.jsonl")
    since = min([_ms(c["recorded"]) for c in calls] + [_ms(FORWARD_START)]) - 120 * 24 * H   # oscillator warm-up
    bars = fetch_bars(since_ms=since)
    scored = [score_call(c, bars) for c in calls]
    report = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "venue": "Pionex BTC_USDT 1h", "forward_start": FORWARD_START,
              "note": ("Forward-only guidance scorecard, not evidence of profitability. "
                       "Daily Entry and Chart Hackers are the same presenter, so they are not "
                       "independent. Judge nothing before ~30 scored calls per channel."),
              "summary": summarize(scored), "calls": scored, "oscillator": oscillator_forward(bars)}
    try:
        report["trend"] = trend_forward()
    except Exception as exc:  # noqa: BLE001 - a feed hiccup must not lose the rest of the scorecard
        report["trend"] = {"error": str(exc)}
    try:                                                                  # CTA trend basket, paper only
        from .swing_book import run as swing_run
        st = swing_run(paths)
        report["swing_book"] = {k: st.get(k) for k in ("start", "paper_usdt", "equity", "next_targets", "next_targets_usdt", "signals", "updated")}
        report["swing_book"]["last_days"] = st.get("history", [])[-5:]
        for book in ("growth", "canary"):
            g = swing_run(paths, book=book)
            report[f"swing_book_{book}"] = {k: g.get(k) for k in ("start", "paper_usdt", "equity", "next_targets", "next_targets_usdt", "updated")}
            report[f"swing_book_{book}"]["last_days"] = g.get("history", [])[-5:]
    except Exception as exc:  # noqa: BLE001
        report["swing_book"] = {"error": str(exc)}
    dst = paths.reports / "btc_guidance.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(report, indent=2), encoding="utf-8", newline="\n")
    return report
