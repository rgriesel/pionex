"""Paper swing book: the CTA trend basket (swing/cta.py, pre-registered and passed) run forward on
Pionex's own daily candles. PAPER ONLY: it computes target weights and simulated equity; it places
no orders and has no order path. Outside the lab mandate (which caps holds at 4h); the user asked
for longer holds on 2026-10-14 and owns any mandate change.

Rules (unchanged from cta.py): 10 coins; a coin is IN when at least 2 of its 20/60/120-day returns
are positive (on the last closed daily candle); weight = (40% / N) / 30-day annualised vol, total
capped at 100%; only weight changes > 2% trade; 0.07% per side on traded weight; rebalanced at the
00:00 UTC open. Paper capital: 100 USDT from FORWARD_START.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

from .cta import UNIVERSE

FORWARD_START = "2026-10-14"
TARGET, BAND, SIDE = 0.40, 0.02, (5 + 2) / 1e4
DAY = 86_400_000


def candles(client, sym, now_ms):
    kl, _ = client.klines(sym, "1D", limit=300)
    kl = sorted((k for k in kl if k.open_time + DAY <= now_ms), key=lambda k: k.open_time)
    return [(k.open_time, float(k.open), float(k.close)) for k in kl]


def targets(series: dict) -> dict:
    """series: {sym: [(open_time, open, close)] oldest first, last element = last CLOSED day}."""
    avail, info = [], {}
    for s, rows in series.items():
        if len(rows) < 121:
            continue
        c = [r[2] for r in rows]
        votes = [c[-1] / c[-1 - L] - 1 > 0 for L in (20, 60, 120)]
        rets = [c[i] / c[i - 1] - 1 for i in range(len(c) - 30, len(c))]
        m = sum(rets) / 30
        vol = math.sqrt(sum((x - m) ** 2 for x in rets) / 30 * 365.25)
        info[s] = {"in": sum(votes) >= 2, "vol": vol, "r20": c[-1] / c[-21] - 1, "r60": c[-1] / c[-61] - 1, "r120": c[-1] / c[-121] - 1}
        avail.append(s)
    n = len(avail)
    w = {s: (TARGET / n) / info[s]["vol"] for s in avail if info[s]["in"] and info[s]["vol"] > 0} if n else {}
    gross = sum(w.values())
    if gross > 1:
        w = {s: v / gross for s, v in w.items()}
    return {"weights": w, "info": info, "available": n}


def step(state: dict, day_ms: int, opens: dict, prev_opens: dict, tgt: dict) -> dict:
    """Advance one day: book yesterday->today open-to-open returns on the held weights, then
    rebalance to today's targets (band + costs)."""
    w = state.get("weights", {})
    r = sum(v * (opens[s] / prev_opens[s] - 1) for s, v in w.items() if s in opens and s in prev_opens)
    traded, new = 0.0, dict(w)
    for s in set(tgt) | set(w):
        a, b = w.get(s, 0.0), tgt.get(s, 0.0)
        if abs(b - a) > BAND or (a == 0.0) != (b == 0.0):
            traded += abs(b - a)
            new[s] = b
    new = {s: v for s, v in new.items() if v > 0}
    eq = state.get("equity", 100.0) * (1 + r) * (1 - traded * SIDE)
    state.update(equity=eq, weights=new, last_day=day_ms)
    state.setdefault("history", []).append({"day": datetime.fromtimestamp(day_ms / 1000, timezone.utc).date().isoformat(),
                                            "ret_pct": round(100 * r, 3), "traded": round(traded, 4), "equity": round(eq, 4)})
    return state


def run(paths, client=None, now_ms=None) -> dict:
    from ..exchange.pionex_public import PionexPublic
    client = client or PionexPublic()
    now_ms = now_ms or int(datetime.now(timezone.utc).timestamp() * 1000)
    path = Path(paths.root) / "swing_book" / "state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    state = json.loads(path.read_text()) if path.exists() else {"start": FORWARD_START, "equity": 100.0, "weights": {}}
    series = {s: candles(client, s, now_ms) for s in UNIVERSE}
    start_ms = int(datetime.fromisoformat(FORWARD_START).replace(tzinfo=timezone.utc).timestamp() * 1000)
    days = sorted({r[0] for rows in series.values() for r in rows})
    for d in days:                                             # each day's open is a rebalance point
        if d < start_ms or d <= state.get("last_day", 0):
            continue
        hist = {s: [r for r in rows if r[0] < d] for s, rows in series.items()}   # closed days before d
        tgt = targets(hist)["weights"]
        opens = {s: r[1] for s, rows in series.items() for r in rows if r[0] == d}
        prev = {s: r[1] for s, rows in series.items() for r in rows if r[0] == d - DAY}
        state = step(state, d, opens, prev, tgt)
    latest = targets(series)
    state["next_targets"] = {s: round(v, 4) for s, v in latest["weights"].items()}
    state["signals"] = {s: {"in": v["in"], "vol_pct": round(100 * v["vol"], 1), "r20_pct": round(100 * v["r20"], 1),
                            "r60_pct": round(100 * v["r60"], 1), "r120_pct": round(100 * v["r120"], 1)} for s, v in latest["info"].items()}
    state["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path.write_text(json.dumps(state, indent=1), encoding="utf-8")
    return state
