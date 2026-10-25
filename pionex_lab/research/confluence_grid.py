"""CLO-129 confluence and random-level plan adapter. Research only; no orders.

Consumes causal level evidence from a future validated indicator pipeline;
does not compute owner indicators, simulate fills, infer liquidation or launch.
"""
from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass

from ..swing.grid import FEE, step_pct

SEED = 20261025
KINDS = {"SR": "SR", "AVWAP_HIGH": "AVWAP", "AVWAP_LOW": "AVWAP",
         "EMA50": "EMA", "EMA200": "EMA", "FIB50": "FIB", "FIB618": "FIB"}


@dataclass(frozen=True)
class Level:
    kind: str
    price: float
    known_ms: int
    source_id: str
    touches: int = 0


def _zones(levels, tolerance):
    ordered = sorted(levels, key=lambda p: (p.price, p.kind, p.source_id))
    out = []
    for i, left in enumerate(ordered):
        members = [p for p in ordered[i:] if p.price-left.price <= tolerance]
        if len({KINDS[p.kind] for p in members}) < 2:
            continue
        out.append({"low": members[0].price, "high": members[-1].price,
                    "center": (members[0].price+members[-1].price)/2,
                    "types": sorted({KINDS[p.kind] for p in members}),
                    "kinds": sorted({p.kind for p in members}),
                    "sources": sorted({p.source_id for p in members})})
    return out


def _random_entry(zones, reference, atr, side, key):
    seed = int.from_bytes(hashlib.sha256(f"{SEED}:{key}".encode()).digest()[:8], "big")
    rng = random.Random(seed)
    for _ in range(100):
        price = reference - side*rng.uniform(0.5, 4.0)*atr
        if price > 0 and all(not z["low"]-0.5*atr <= price <= z["high"]+0.5*atr for z in zones):
            return price, seed
    return None, seed


def confluence_family(symbol, timeframe, levels, reference, atr, decision_ms):
    """PRE-REGISTERED 2026-10-25 19:02 SAST before tests or performance reads.

    Separate v1 hypothesis from band/support cohorts, not a retune. Offline
    adapter for BTC/ETH and 4H/1D causal levels only. Source rule:
    research/owner_method/owner_rules_v1.md. Indicator pipeline (NOT supplied
    by this adapter) must use confirmed n=5 fractals, AVWAP from latest high/
    low, fib .5/.618, EMA50/200 and SR zones with >=3 distinct pivot touches.
    Reuse zoo.ema/atr(14); exact SRchannel settings are unknown. The pipeline
    requires its own frozen objective definition and causal validation before
    launch; source labels alone do not prove it. No Elliott calculation.

    Reject unknown types/invalid evidence; exclude future-known levels and SR
    evidence with <3 touches. Complete-link zones span <=0.5 ATR and contain
    >=2 DISTINCT families {SR, AVWAP, EMA, FIB}; EMA50+EMA200 or two fibs alone
    cannot count. No chained clusters wider than tolerance. Short resistance
    MUST contain AVWAP_HIGH plus another family, wholly above reference.
    Mirror long support MUST contain AVWAP_LOW, wholly below. Choose nearest
    entry zone; target nearest opposite confluence across reference. No
    opposite zone -> record skipped direction. Fixed stop one ATR beyond far
    zone boundary; target zone center. Freeze all levels for a 7-day cohort.

    Plans are conditional touch FROM BELOW for short / FROM ABOVE for long;
    closed-bar observation then next-open simulated fill (not at old level),
    with reward/risk and stop revalidated on a fresh Pionex quote. No instant
    entry or touch-fill assumption in this adapter. Two modes: directional
    fade and 10-cell geometric directional grid spanning entry to target.
    Reject grid mode for both matched arms if either step <3x round-trip 5bp
    fees. Constant 1000 simulated USDT, 1x isolated PERP for both directions
    (never spot short); 2x/3x remain in the separate support family. Fees,
    spread, slippage, funding, margin and liquidation belong to CLO-37's ledger.

    Matched R3: seed=20261025 + SHA256(symbol,timeframe,decision,direction),
    at most 100 uniform signed distances 0.5..4 ATR from reference; first
    non-confluence point >0.5 ATR from every zone wins. Translate entry zone,
    stop and target by SAME offset, preserving stop/target distances, capital,
    mode, costs, hold and trigger direction. No outcome-dependent draws.
    Target need not be a real confluence in R3. If no admissible control or
    any translated price <=0, skip BOTH arms. Control entry distance from
    reference differs: report touch rates and exposure; this is not an exact
    distance-matched placebo. Never compare unmatched surviving opportunities.

    Attempt budget: 2 pairs x 2 frames x 2 directions x 2 modes x 2 arms =32
    configurations; register all attempts/skips before first prices. No tuning
    or automatic variants. Report R1 short/R2 long/R3 controls separately,
    net expectancy, hit/win/loss, breakthroughs, sample count and paired uplift.
    Owner protocol needs >=100 trades/rule, after-cost positive, beats control,
    untouched chronological half and firm-wide DSR/luck gates. Exact inferential
    thresholds/stress/bootstrap protocol require confirmation before evaluation.
    All outputs remain INSUFFICIENT, pass=false, launch/live eligible=false.
    Tests validate synthetic plan mechanics only; no performance run here.
    """
    if symbol not in ("BTC_USDT", "ETH_USDT") or timeframe not in ("4H", "1D"):
        raise ValueError("unregistered symbol/timeframe")
    if not all(math.isfinite(x) and x > 0 for x in (reference, atr)):
        raise ValueError("need positive finite reference and ATR")
    if not isinstance(decision_ms, int) or decision_ms < 0:
        raise ValueError("need integer decision timestamp")
    visible = []
    for p in levels:
        if (p.kind not in KINDS or not math.isfinite(p.price) or p.price <= 0
                or not isinstance(p.known_ms, int) or p.known_ms < 0 or not p.source_id):
            raise ValueError("invalid causal level evidence")
        if p.known_ms <= decision_ms and (p.kind != "SR" or p.touches >= 3):
            visible.append(p)
    zones = _zones(visible, 0.5*atr)
    supports = sorted((z for z in zones if z["high"] < reference),
                      key=lambda z: (-z["center"], z["sources"]))
    resistances = sorted((z for z in zones if z["low"] > reference),
                         key=lambda z: (z["center"], z["sources"]))
    long_entries = [z for z in supports if "AVWAP_LOW" in z["kinds"]]
    short_entries = [z for z in resistances if "AVWAP_HIGH" in z["kinds"]]
    out = {"family": "clo129_confluence_v1", "symbol": symbol, "timeframe": timeframe,
           "decision_ms": decision_ms, "zones": zones, "plans": [], "skipped": [],
           "verdict": "INSUFFICIENT", "pass": False, "live_eligible": False}
    for direction, side, entries, targets in (("long", 1, long_entries, resistances),
                                               ("short", -1, short_entries, supports)):
        if not entries or not targets:
            out["skipped"].append({"direction": direction, "reason": "no anchored entry/target confluence"})
            continue
        entry, target = entries[0], targets[0]["center"]
        stop = entry["low"]-atr if side == 1 else entry["high"]+atr
        key = f"{symbol}:{timeframe}:{decision_ms}:{direction}"
        control, seed = _random_entry(zones, reference, atr, side, key)
        if control is None or min(entry["low"], stop, target) <= 0:
            out["skipped"].append({"direction": direction, "reason": "no admissible paired control"})
            continue
        delta = control-entry["center"]
        if min(entry["low"]+delta, target+delta, stop+delta) <= 0:
            out["skipped"].append({"direction": direction, "reason": "nonpositive translated control"})
            continue
        # A full zone must stay on its approach side of the reference.
        if not (entry["high"]+delta < reference if side == 1 else entry["low"]+delta > reference):
            out["skipped"].append({"direction": direction, "reason": "control zone crosses reference"})
            continue
        for mode in ("fade", "grid"):
            bounds = [(min(entry["center"]+d, target+d), max(entry["center"]+d, target+d))
                      for d in (0, delta)]
            if mode == "grid" and any(step_pct(lo, hi, 10) < 6*FEE for lo, hi in bounds):
                out["skipped"].append({"direction": direction, "mode": mode, "reason": "paired grid spacing fails"})
                continue
            for arm, shift in (("confluence", 0), ("random", delta)):
                out["plans"].append({
                    "id": f"clo129_cf_{symbol}_{timeframe}_{decision_ms}_{direction}_{mode}_{arm}_v1",
                    "pair_key": f"{key}:{mode}", "arm": arm, "mode": mode,
                    "symbol": symbol+"_PERP", "timeframe": timeframe, "direction": direction,
                    "leverage": 1, "capital": 1000.0, "entry_low": entry["low"]+shift,
                    "entry_high": entry["high"]+shift, "entry_reference": entry["center"]+shift,
                    "target": target+shift, "stop": stop+shift, "rows": 10 if mode == "grid" else None,
                    "trigger": "touch_from_above" if side == 1 else "touch_from_below",
                    "seed": seed, "source_ids": entry["sources"], "target_sources": targets[0]["sources"],
                    "launch_eligible": False, "liquidation_price": None,
                })
    return out
