"""CLO-129 support-anchored tournament preparation. Research only; no execution.

Separate hypothesis from the original percentage-band cohort. Does not change
grid_tournament's frozen policy or turn owner/analyst anecdotes into evidence.
Input bars use swing.grid's (open_ms, open, high, low, close) convention.
"""
from __future__ import annotations

import math

from ..swing.grid import FEE, MIN_GRID_USDT, step_pct

HOUR = 3_600_000
LOOKBACK = 168


def _closed_hours(bars, asof_ms):
    out = []
    for row in bars:
        ts, o, h, l, c = row
        if not isinstance(ts, int) or ts % HOUR:
            raise ValueError("hourly timestamps must be integer UTC hour opens")
        if ts + HOUR > asof_ms:
            continue
        if (any(not math.isfinite(p) or p <= 0 for p in (o, h, l, c))
                or not l <= min(o, c) <= max(o, c) <= h):
            raise ValueError("invalid closed OHLC bar")
        out.append((ts, o, h, l, c))
    out.sort()
    if len({r[0] for r in out}) != len(out):
        raise ValueError("duplicate hourly bars")
    return out


def support_family(symbol, bars, decision_ms):
    """PRE-REGISTERED 2026-10-25 18:54 SAST, before tests or market evaluation.

    Offline plans only. BTC_USDT/ETH_USDT, fixed trailing 168 CLOSED hourly
    bars ending at the most recent UTC hour boundary <= decision_ms. Support
    = their minimum low (earliest bar wins a tie); range bottom = support,
    top = support*1.16, 40 geometric rows, stop = support*0.97. The latest
    closed-bar close must lie 2%..8% ABOVE support. No support or stale/missing
    hour -> no family; no expanding lookback, re-anchoring or retrospective fit.
    No extra indicator filter: this is an explicit proxy for prior support,
    not a reconstruction of the owner's discretionary indicators.

    Three plans/pair: unleveraged SPOT and LONG PERP at 2x and 3x, each with
    1,000 simulated USDT margin/capital. Reuse swing.grid levels/cost checks;
    grid spacing >=3x round-trip 5bp fees, minimum 10 USDT/cell. Futures fees,
    settled funding, dynamic inventory margin, liquidation tiers/fees and stop
    slippage require CLO-37's ledger. A perp may launch only if that model
    verifies liquidation < planned stop < support at entry and each update;
    unknown/stale model inputs -> no launch. Never multiply spot returns.
    SPOT has no liquidation price. Fresh Pionex quotes/rules must revalidate
    the fixed range before any eventual next-open simulated entry; bar close
    here is a reference, never a fill. Count all six planned configurations
    before their first observation and retain skipped attempts in the registry.

    Freeze support/range for one seven-day cohort. Count subsequent support
    breaks with support_breaks; no automatic respawn when a support fails.
    Qualification verdict INSUFFICIENT, pass=false: unstarted preparation.
    A performance test needs prior board-confirmed gates and all unchanged
    firm qualification checks; unit-test success cannot qualify a strategy.
    """
    if symbol not in ("BTC_USDT", "ETH_USDT"):
        raise ValueError("support family is restricted to BTC/ETH")
    end = decision_ms // HOUR * HOUR
    start = end - LOOKBACK * HOUR
    history = [r for r in _closed_hours(bars, decision_ms) if start <= r[0] < end]
    out = {"family": "clo129_support_v1", "symbol": symbol,
           "decision_ms": decision_ms, "verdict": "INSUFFICIENT", "pass": False,
           "live_eligible": False, "plans": [], "errors": []}
    if [r[0] for r in history] != list(range(start, end, HOUR)):
        out["errors"].append("need 168 contiguous closed hourly bars through last closed hour")
        return out
    anchor = min(history, key=lambda r: (r[3], r[0]))
    support, ref = anchor[3], history[-1][4]
    distance = ref / support - 1
    if not 0.02 - 1e-12 <= distance <= 0.08 + 1e-12:
        out["errors"].append("reference close is outside fixed 2..8% support distance")
        return out
    top = support * 1.16
    assert 1000/40 >= MIN_GRID_USDT and step_pct(support, top, 40) >= 6*FEE
    for product, lev in (("SPOT", 1), ("PERP", 2), ("PERP", 3)):
        out["plans"].append({
            "id": f"clo129_support_{symbol}_{end}_{product}_{lev}x_v1",
            "symbol": symbol if product == "SPOT" else symbol+"_PERP",
            "product": product, "direction": "long", "leverage": lev,
            "support": support, "bottom": support, "top": top,
            "support_bar_ms": anchor[0], "support_known_ms": end,
            "reference_close": ref, "rows": 40, "grid_type": "geometric",
            "capital": 1000.0, "stop": support*0.97,
            "liquidation_price": None, "launch_eligible": False,
            "pending": "forward protocol/supervisor" if lev == 1 else "CLO-37 liquidation/funding verification",
        })
    return out


def support_breaks(bars, support, start_ms, end_ms, asof_ms):
    """PRE-REGISTERED 2026-10-25 18:54 SAST before any break-count evaluation.

    Audit fixed support after cohort start, never a signal or fill. Require
    complete closed hourly coverage of [start_ms,end_ms), up to seven days;
    missing/duplicate/invalid bars -> unknown, never zero breaks. Discard bars
    at/after end or still open at asof. Count STRICT low<support wick hours
    and close<support close hours, separate episodes (false->true, first hour
    starts a new episode), and first-break timestamps. Equality is a touch.
    A recovery resets an episode only for that series. Do not re-anchor. Counts
    cannot determine intrabar order, stop execution or liquidation. No PASS.
    """
    if (not math.isfinite(support) or support <= 0 or start_ms % HOUR or end_ms % HOUR
            or not start_ms < end_ms <= start_ms + 168*HOUR):
        raise ValueError("need positive support and aligned interval of 1..168 hours")
    obs = [r for r in _closed_hours(bars, asof_ms) if start_ms <= r[0] < end_ms]
    out = {"coverage": "INSUFFICIENT", "support": support, "wick_hours": None,
           "close_hours": None, "wick_episodes": None, "close_episodes": None,
           "first_wick_ms": None, "first_close_ms": None}
    if [r[0] for r in obs] != list(range(start_ms, end_ms, HOUR)):
        return out
    out.update(coverage="COMPLETE", wick_hours=0, close_hours=0, wick_episodes=0, close_episodes=0)
    prev = {"wick": False, "close": False}
    for ts, _o, _h, low, close in obs:
        for name, broken in (("wick", low < support), ("close", close < support)):
            out[name+"_hours"] += int(broken)
            out[name+"_episodes"] += int(broken and not prev[name])
            if broken and out["first_"+name+"_ms"] is None:
                out["first_"+name+"_ms"] = ts
            prev[name] = broken
    return out
