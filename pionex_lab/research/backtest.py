"""Conservative bar-replay backtester (research only; floats, not used for sizing).

Rules (references/research.md "Cost model"):
* A signal on completed bar i executes no earlier than the OPEN of bar i+delay
  (delay >= 1), paying half-spread + impact, and the research fee on both sides
  (base-asset fee on the buy, quote fee on the sell).
* Stops: a gap through the stop fills at the (worse) open; otherwise at the stop
  minus half-spread, impact, and optional extra stop slippage.
* Targets require the high to trade THROUGH the target by `through_bps`; the exit
  is then treated as a marketable sell (no queue priority is inferred).
* If stop and target are both reachable inside one bar, the stop is assumed first.
* Time exits at the close of the bar where the holding limit is reached.
* Trades not completed inside the evaluation window are purged, never marked.
"""
from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    fee_per_side: float = 0.0005
    half_spread_bps: float = 1.0
    impact_bps: float = 2.0
    through_bps: float = 2.0
    multiplier: float = 1.0

    def scaled(self, m: float) -> "CostModel":
        return CostModel(self.fee_per_side, self.half_spread_bps, self.impact_bps, self.through_bps, m)

    @property
    def roundtrip_bps(self) -> float:
        return (2 * self.fee_per_side * 1e4 + 2 * (self.half_spread_bps + self.impact_bps)) * self.multiplier


@dataclass(frozen=True)
class Stress:
    entry_delay: int = 1
    miss_rate: float = 0.0
    extra_stop_slip_bps: float = 0.0
    seed: int = 7


BASE = Stress()
STRESS = Stress(entry_delay=2, miss_rate=0.2, extra_stop_slip_bps=10.0)


def simulate(strategy, prep, symbol: str, start: int, end: int, cost: CostModel, stress: Stress = BASE) -> dict:
    """Replay decision bars i in [start, end) for one symbol. Returns trades and counters."""
    b = prep[symbol]["b5"]
    m = cost.multiplier
    fee = cost.fee_per_side * m
    slip = (cost.half_spread_bps + cost.impact_bps) * m / 1e4
    rng = random.Random(f"{stress.seed}:{strategy.key}:{symbol}:{start}")
    trades, signals, missed, purged = [], 0, 0, 0
    i = max(start, strategy.warmup)
    end = min(end, len(b))
    while i < end:
        sig = strategy.check(prep, symbol, i)
        if sig is None:
            i += 1
            continue
        signals += 1
        j = i + stress.entry_delay
        if j >= end:
            purged += 1
            break
        if stress.miss_rate and rng.random() < stress.miss_rate:
            missed += 1
            i += 1
            continue
        raw_entry = b.o[j]
        entry = raw_entry * (1 + slip)
        exit_px = raw_exit = reason = None
        k = j
        while k < end:
            if k > j and b.o[k] <= sig.stop:                       # gap through the stop
                raw_exit, reason = b.o[k], "STOP_GAP"
                exit_px = raw_exit * (1 - slip - stress.extra_stop_slip_bps * m / 1e4)
            elif b.l[k] <= sig.stop:                                 # stop first when ambiguous
                raw_exit, reason = sig.stop, "STOP"
                exit_px = raw_exit * (1 - slip - stress.extra_stop_slip_bps * m / 1e4)
            elif sig.target is not None and b.h[k] >= sig.target * (1 + cost.through_bps / 1e4):
                raw_exit, reason = sig.target, "TARGET"
                exit_px = raw_exit * (1 - slip)
            elif k - j + 1 >= sig.max_hold_bars:
                raw_exit, reason = b.c[k], "TIME"
                exit_px = raw_exit * (1 - slip)
            if reason:
                break
            k += 1
        if reason is None:
            purged += 1
            break
        net = (1 - fee) * exit_px * (1 - fee) / entry - 1
        gross = raw_exit / raw_entry - 1
        risk = (raw_entry - sig.stop) / raw_entry
        trades.append({"opportunity_id": sig.opportunity_id, "symbol": symbol, "strategy": strategy.key,
                       "entry_time": b.t[j], "exit_time": b.t[k] + (b.t[1] - b.t[0] if len(b) > 1 else 0),
                       "entry_px": entry, "exit_px": exit_px, "net_bps": net * 1e4, "gross_bps": gross * 1e4,
                       "r_multiple": net / risk if risk > 0 else 0.0, "exit_reason": reason, "bars_held": k - j + 1})
        i = k + 1
    return {"trades": trades, "signals": signals, "missed": missed, "purged": purged}


def simulate_universe(strategy, prep, symbols, windows: dict, cost: CostModel, stress: Stress = BASE) -> dict:
    """windows: symbol -> (start_idx, end_idx)."""
    out = {"trades": [], "signals": 0, "missed": 0, "purged": 0}
    for s in symbols:
        if s not in windows:
            continue
        r = simulate(strategy, prep, s, *windows[s], cost, stress)
        out["trades"] += r["trades"]
        for k in ("signals", "missed", "purged"):
            out[k] += r[k]
    out["trades"].sort(key=lambda t: (t["exit_time"], t["symbol"]))
    return out
