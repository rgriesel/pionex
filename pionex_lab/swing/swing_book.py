"""Paper swing book: the CTA trend basket (swing/cta.py v1.1, an in-sample backtest that passed and
survived red-team review with fixes) run forward on Pionex's own daily candles. PAPER ONLY: it
computes target weights and simulated equity; it places no orders and has no order path. Outside
the lab mandate (which caps holds at 4h); the user asked for longer holds and owns any mandate change.

Rules (same as cta.py): a coin is IN when at least 2 of its 20/60/120-day returns are positive (on
the last closed daily candle); weight = (40% / N) / 30-day annualised vol, total capped at 100%;
weights drift with prices and only changes > 2% (or opens/closes) trade; buys under 10 USDT are
skipped (Pionex minimum); cost per side = 0.05% fee + 0.02% slippage + half the measured spread;
rebalanced at the 00:00 UTC open from FORWARD_START.
Books (paper USDT chosen before the start so the 10 USDT minimum does not distort them):
  defensive  10 coins, vol sizing (the tested variant)                         1000 USDT
  growth     10 coins, 1/N per IN coin (comparison; backtest DD ~55%)            1000 USDT
  canary     BTC + ETH only, vol sizing: exactly what a <= $100 live canary        100 USDT
             could hold (the full basket at $100 would sit ~89% in cash)
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

from .cta import UNIVERSE, drift, rebalance

FORWARD_START = "2026-10-14"
TARGET, BAND = 0.40, 0.02
DAY = 86_400_000
BOOKS = {"defensive": {"sizing": "vol", "coins": UNIVERSE, "usdt": 1000.0, "file": "state.json"},
         "growth": {"sizing": "equal", "coins": UNIVERSE, "usdt": 1000.0, "file": "state_growth.json"},
         "canary": {"sizing": "vol", "coins": ("BTC_USDT", "ETH_USDT"), "usdt": 100.0, "file": "state_canary.json"}}


def candles(client, sym, now_ms):
    """Daily candles oldest first; today's unfinished candle is kept with close=None so its 00:00 UTC
    open can be the rebalance price as soon as it exists (signals only ever use closed candles)."""
    kl, _ = client.klines(sym, "1D", limit=300)
    kl = sorted((k for k in kl if k.open_time <= now_ms), key=lambda k: k.open_time)
    return [(k.open_time, float(k.open), float(k.close) if k.open_time + DAY <= now_ms else None) for k in kl]


def targets(series: dict, sizing: str = "vol") -> dict:
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
    if sizing == "equal":                                     # growth book: 1/N per IN coin
        w = {s: 1.0 / n for s in avail if info[s]["in"]} if n else {}
    else:
        w = {s: (TARGET / n) / info[s]["vol"] for s in avail if info[s]["in"] and info[s]["vol"] > 0} if n else {}
    gross = sum(w.values())
    if gross > 1:
        w = {s: v / gross for s, v in w.items()}
    return {"weights": w, "info": info, "available": n}


def step(state: dict, day_ms: int, opens: dict, prev_opens: dict, tgt: dict, capital: float | None = None) -> dict:
    """Advance one day: book yesterday->today open-to-open returns on the held weights (which then
    drift with prices), then rebalance to today's targets (band, minimum buy, gross cap, costs).
    `capital` caps the USDT used for the minimum-buy check (as in cta.simulate)."""
    w = state.get("weights", {})
    rets = {s: opens[s] / prev_opens[s] - 1 for s in w if s in opens and s in prev_opens}
    w, r = drift(w, rets)
    eq = state.get("equity", capital or 100.0) * (1 + r)
    usdt = None if capital is None else min(eq, capital)
    new, paid, traded = rebalance(w, tgt, set(opens), BAND, usdt)
    eq *= 1 - paid
    state.update(equity=eq, weights=new, last_day=day_ms)
    state.setdefault("history", []).append({"day": datetime.fromtimestamp(day_ms / 1000, timezone.utc).date().isoformat(),
                                            "ret_pct": round(100 * r, 3), "traded": round(traded, 4),
                                            "cost_pct": round(100 * paid, 4), "equity": round(eq, 4)})
    return state


def run(paths, client=None, now_ms=None, book="defensive") -> dict:
    from ..exchange.pionex_public import PionexPublic
    client = client or PionexPublic()
    now_ms = now_ms or int(datetime.now(timezone.utc).timestamp() * 1000)
    cfg = BOOKS[book]
    sizing, capital = cfg["sizing"], cfg["usdt"]
    path = Path(paths.root) / "swing_book" / cfg["file"]
    path.parent.mkdir(parents=True, exist_ok=True)
    state = json.loads(path.read_text()) if path.exists() else {"start": FORWARD_START, "equity": capital, "weights": {}, "book": book}
    if not state.get("history"):                               # not started yet: (re)set the paper notional
        state["equity"] = capital
    state.update(book=book, paper_usdt=capital, coins=list(cfg["coins"]))
    series = {s: candles(client, s, now_ms) for s in cfg["coins"]}
    start_ms = int(datetime.fromisoformat(FORWARD_START).replace(tzinfo=timezone.utc).timestamp() * 1000)
    days = sorted({r[0] for rows in series.values() for r in rows})
    for d in days:                                             # each day's open is a rebalance point
        if d < start_ms or d <= state.get("last_day", 0):
            continue
        hist = {s: [r for r in rows if r[0] < d] for s, rows in series.items()}   # closed days before d
        tgt = targets(hist, sizing)["weights"]
        opens = {s: r[1] for s, rows in series.items() for r in rows if r[0] == d}
        prev = {s: r[1] for s, rows in series.items() for r in rows if r[0] == d - DAY}
        state = step(state, d, opens, prev, tgt, capital)
    latest = targets({s: [r for r in rows if r[2] is not None] for s, rows in series.items()}, sizing)  # closed only
    state["next_targets"] = {s: round(v, 4) for s, v in latest["weights"].items()}
    state["next_targets_usdt"] = {s: round(v * min(state["equity"], capital), 2) for s, v in latest["weights"].items()}
    state["signals"] = {s: {"in": v["in"], "vol_pct": round(100 * v["vol"], 1), "r20_pct": round(100 * v["r20"], 1),
                            "r60_pct": round(100 * v["r60"], 1), "r120_pct": round(100 * v["r120"], 1)} for s, v in latest["info"].items()}
    state["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path.write_text(json.dumps(state, indent=1), encoding="utf-8")
    return state
