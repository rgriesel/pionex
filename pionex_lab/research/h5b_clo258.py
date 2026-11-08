"""H5b preparation only: pure hourly-bar simulator; no loader or evaluation entry point."""
from __future__ import annotations

import math

from research.own_edge_b_clo248 import H, h5_signals


def _bar(bars, i):
    """Reject missing/malformed bars without interpolating or fabricating fills."""
    if not 0 <= i < len(bars) or bars[i] is None:
        return None
    b = bars[i]
    if len(b) != 4 or not all(math.isfinite(x) and x > 0 for x in b):
        raise ValueError("expected positive finite OHLC")
    o, h, l, c = b
    if not l <= min(o, c) <= max(o, c) <= h:
        raise ValueError("invalid OHLC ordering")
    return b


def execution_cost(hours, mult=1, half_spread_bps=None):
    """Full-notional entry + exit friction; adverse funding for either side."""
    spread = 5.0 if half_spread_bps is None else half_spread_bps
    if mult not in (1, 2, 3, 4) or not math.isfinite(spread) or spread < 0 or hours < 0:
        raise ValueError("invalid fixed cost assumptions")
    return 2 * (8.0 + spread) * mult, hours / 8.0


def _position(bars, t0, entry_i, side, stop, tp, mult, spread):
    entry = _bar(bars, entry_i)[0]
    # The 96th completed hour ends at open entry_i+96. That open is the
    # scheduled market exit; its later high/low cannot change an open fill.
    for k in range(entry_i, entry_i + 97):
        b = _bar(bars, k)
        if b is None:
            return None
        o, h, l, _ = b
        gap_stop = o <= stop if side == 1 else o >= stop
        if gap_stop:
            px, reason, hours = o, "stop", k - entry_i
        elif k == entry_i + 96:
            px, reason, hours = o, "time", 96
        elif (l <= stop if side == 1 else h >= stop):
            px, reason, hours = stop, "stop", k - entry_i + 1
        elif (h >= tp if side == 1 else l <= tp):
            px, reason, hours = tp, "tp", k - entry_i + 1
        else:
            continue
        # Intrabar exits use the end of the containing hour for conservative
        # funding/exposure. A known open gap/time exit uses elapsed hours.
        gross = side * (px / entry - 1) * 10_000
        friction, funding = execution_cost(hours, mult, spread)
        return dict(entry_time=t0 + entry_i * H, exit_time=t0 + (entry_i + hours) * H,
                    exit_bar=k, side=side, entry=entry, exit=px, stop=stop, tp=tp,
                    exit_reason=reason, hours=hours, notional=1.0,
                    inventory_notional_hours=float(hours), gross_bps=gross,
                    execution_cost_bps=friction, funding_bps=funding,
                    net_bps=gross - friction - funding)
    raise AssertionError("unreachable")


def h5b(bars, t0, mult=1, half_spread_bps=None):
    """Frozen H5b v1 / CLO-258 / existing trial 172, PREPARATION ONLY.

    Implementation written 2026-11-08T03:55:00+02:00 SAST before any tests.
    Registration frozen 2026-11-08T03:45:19+02:00, SHA256
    9ff7dee18ee8a3790beea369f37954b7d8c67a1bf3825024370f49feeb261d9e
    (research/registrations/clo256_h5b_v1.md). One specification, one eventual
    evaluation; no optimization. CEO authorizes synthetic preparation ONLY;
    inherited board gate confirmation remains required before returns evaluation.

    Rules: BTC_USDT/ETH_USDT hourly Binance spot PROXY, earliest available
    2019-01 through 2026-10-12 23:00 UTC; final entries >=2023-04-01.
    Adaptive successor screening, NEVER untouched OOS. Reuse h5_signals
    UNCHANGED: 72h prior range, 3d/14d range ratio <=0.70, ATR over 14 daily
    intervals. At closed signal i freeze prior 72h U/L and ATR A. First
    subsequent close j in i+1..i+4 inside [L,U] confirms failure; otherwise
    expire. Ignore new signals while pending/holding. Enter opposite side at
    open j+1, single full-notional 1x position, no leverage/liquidation claim.
    Short stop=max(high[i..j])+0.25*A; long stop=min(low[i..j])-0.25*A;
    TP=(L+U)/2. Skip invalid next-open stop/entry/TP ordering. Stop/TP active
    immediately, stop wins ambiguous bars, stop gaps fill at worse open,
    TP has no favorable improvement. Time exit open after 96 elapsed hours.
    Missing hours stay missing; incomplete lookbacks/confirmation skip; missing
    open never fills; a gap during an active position halts this coin with an
    explicit unresolved record (never silently discard losses and resume).

    Costs: 8bps/side (6 fee allowance+2 slippage) plus measured half-spread;
    absent measured spread fixed 5bps/side. Funding always charged 1bp/8h on
    full filled notional both directions. Stress all execution friction at
    2x/3x/4x; funding unchanged. Report gross/net, inventory, exit reasons,
    paired same-signal continuation diagnostic in eventual evaluation.

    Frozen screen gates: >=100 trades in full AND final, mean net >0 in both,
    final PF>=1.2, final mean net>0 at 2x execution costs, final mean excluding
    best trade>0, final one-sided 95% three-day block-bootstrap lower bound>0.
    Either era <100 => INSUFFICIENT, otherwise failed gate => FAIL. Reuse
    research.metrics summarize/block_bootstrap_lower with parent default seed
    20260928 and resampling implementation. Also report 0.05/ntrials bound,
    ntrials=max(295,SUM(weight) at eventual run), and 3x/4x stresses; no gate
    changes. Freeze input fingerprints and create-only sentinel before that
    single run; reuse trial 172, no new reservation. FAIL/INSUFFICIENT requires
    WHY/WHAT/NEXT separately registered queued successor. PASS stays open for
    independent CEO-assigned Red Team (maxReviewRounds 2), never live eligibility.
    This module performs no database IO, trial accounting, or gate evaluation.
    """
    execution_cost(0, mult, half_spread_bps)  # validate even if no signals
    trades, events, busy = [], [], -1
    for i, breakout_side, atr in h5_signals(bars):
        if i <= busy:
            continue
        if i < 72 or not math.isfinite(atr) or atr <= 0:
            events.append(dict(signal=i, reason="invalid_lookback"))
            continue
        window = [_bar(bars, k) for k in range(i - 72, i + 1)]
        if any(b is None for b in window):
            events.append(dict(signal=i, reason="missing_lookback"))
            continue
        upper, lower = max(b[1] for b in window[:-1]), min(b[2] for b in window[:-1])
        j = None
        for k in range(i + 1, i + 5):
            busy = k
            b = _bar(bars, k)
            if b is None:
                events.append(dict(signal=i, reason="missing_confirmation"))
                break
            if lower <= b[3] <= upper:
                j = k
                break
        if j is None:
            events.append(dict(signal=i, reason="no_confirmation"))
            continue
        busy = j  # new signals on this confirmation close were pending
        entry_i = j + 1
        b = _bar(bars, entry_i)
        if b is None:
            events.append(dict(signal=i, reason="missing_entry"))
            continue
        side, tp = -breakout_side, (lower + upper) / 2
        excursion = [_bar(bars, k) for k in range(i, j + 1)]
        stop = (max(x[1] for x in excursion) + 0.25 * atr if side == -1
                else min(x[2] for x in excursion) - 0.25 * atr)
        entry = b[0]
        if not (0 < stop < entry < tp if side == 1 else 0 < tp < entry < stop):
            events.append(dict(signal=i, reason="invalid_geometry"))
            continue
        trade = _position(bars, t0, entry_i, side, stop, tp, mult, half_spread_bps)
        if trade is None:
            events.append(dict(signal=i, entry=entry_i, reason="unresolved_position_gap_or_end"))
            break  # unknown inventory: no further positions in this coin
        busy = trade.pop("exit_bar")
        trade.update(signal_time=t0 + i * H, confirmation_time=t0 + j * H,
                     upper=upper, lower=lower, atr=atr)
        trades.append(trade)
    return trades, events
