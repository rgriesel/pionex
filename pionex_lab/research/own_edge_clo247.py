"""CLO-247 research specifications and causal signal builders; no order path.

Registered 2026-11-07 23:31:28 SAST BEFORE market-return evaluation. One fixed
configuration per hypothesis. Gates below are PROPOSED, awaiting board confirmation
on CLO-247. Calling a signal builder is not authorization to evaluate performance.
Only synthetic fixtures may be evaluated until that confirmation is recorded.

Common proposed protocol: Binance PROXY completed 4h OHLCV, 2023-01-01 through
2026-10-01 exclusive; split at 2025-01-01, neither half used for selection.
This history has been used by other firm tests: it is NOT untouched OOS.
Confirmatory forward interval: 2026-11-08 through 2027-05-08 exclusive, Pionex
prices and symbol rules, timestamped original events. No trading authority implied.
Spot long/cash, $10 notional per position (the firm's $10 minimum, not $10 risk),
no leverage, one position per symbol, maximum $100 aggregate exposure. Fees 5 bps
plus 2 bps slippage plus half measured spread per side; unmeasured spread uses
10 bps full spread for historical SCREENING ONLY. Stress all costs at 2x and 4x.
Signals on completed bars, enter next contiguous open, stop 1.5 ATR14, TP 3 ATR14,
time exit after six 4h bars at next open. Intrabar gaps fill at open; simultaneous
stop/TP is stop-first. Hard barriers can close before 4h; planned hold is 24h.
Missing/gapped/invalid bars invalidate the input, never bridge a gap. No forced
close at last close: an unresolved terminal position makes evidence incomplete.

Proposed screen gates, fixed for all three: >=100 closed trades, >=25 independent
UTC exit weeks, positive net expectancy and PF>=1.1, positive net sum in BOTH
fixed halves, daily-block bootstrap lower bound >0 at alpha=0.05 / firm-wide
trial count (including these three), blocks 7 days, fixed seed 20261107, 200000
resamples; net expectancy >0 at 2x and 4x cost. Missing required event vintages,
coverage or sample size => INSUFFICIENT. A screen PASS cannot establish firm
qualification: independent Red Team, unchanged luck/risk gates and untouched
Pionex forward evidence remain required. No function writes eligibility reports.

No performance evaluation or parameter selection has been performed by this file.
"""
from __future__ import annotations

import math
from statistics import median

from ..swing import zoo
from ..swing.factors import Series

BAR_MS = 4 * 3_600_000
REGISTERED_SAST = "2026-11-07 23:31:28 SAST"
GATE_STATUS = "PROPOSED_REQUIRES_BOARD_CONFIRMATION"
IDS = ("clo247_h1_listing", "clo247_h2_funding_liquidations", "clo247_h3_capitulation")


def validate_bars(b):
    """Require complete, contiguous positive 4h bars; callers exclude partial bars."""
    if set(b) != set("tohlcv") or len({len(x) for x in b.values()}) != 1:
        raise ValueError("expected equal-length t/o/h/l/c/v arrays")
    for i, t in enumerate(b["t"]):
        vals = [b[k][i] for k in "ohlcv"]
        if (not isinstance(t, int) or t % BAR_MS or
                not all(math.isfinite(x) for x in vals) or
                min(vals[:4]) <= 0 or vals[4] < 0 or
                b["h"][i] < max(b["o"][i], b["c"][i]) or
                b["l"][i] > min(b["o"][i], b["c"][i]) or
                b["h"][i] < b["l"][i]):
            raise ValueError("invalid OHLCV or timestamp")
        if i and t - b["t"][i - 1] != BAR_MS:
            raise ValueError("duplicate, unordered or missing bar")


def h1_listing(b, events):
    """Pre-registered 2026-11-07 23:31:28 SAST; H1 single listing-breakout test.

    Use each USDT spot listing's FIRST eighteen full 4h bars after actual open_time.
    At the eighteenth close, long iff close > highs of the first seventeen bars and quote
    turnover (sum close*base-volume) >= $1m. Announcement must have original
    published_at <= received_at <= open_time, and source URL + stable event id.
    Delisting/relisting events excluded: no causal short execution is assumed.
    Events are per-symbol and venue-matched to b. Include failed/delisted listings
    in the input universe; present-day symbol lists cannot define this sample.
    One signal/event. Entry, ATR exits, size and common proposed gates above.
    Distinct from old price-only screens: causal initial listing event required.
    """
    validate_bars(b)
    sig = [0] * len(b["t"])
    seen = set()
    for e in events:
        if e["id"] in seen:
            raise ValueError("duplicate event id")
        seen.add(e["id"])
        if (not e.get("source_url") or e["published_at"] > e["received_at"] or
                e["received_at"] > e["open_time"]):
            raise ValueError("missing causal listing vintage")
        if e["kind"] != "listing":
            continue
        start = ((e["open_time"] + BAR_MS - 1) // BAR_MS) * BAR_MS
        j = next((i for i, t in enumerate(b["t"]) if t == start), None)
        if j is None or j + 17 >= len(sig):
            raise ValueError("listing price coverage incomplete")
        k = j + 17
        if (b["c"][k] > max(b["h"][j:k]) and
                sum(b["c"][i] * b["v"][i] for i in range(j, k + 1)) >= 1_000_000):
            sig[k] = 1
    return sig


def h2_funding_liquidations(b, observations):
    """Pre-registered 2026-11-07 23:31:28 SAST; H2 one BTC/ETH squeeze test.

    Each observation covers a completed 4h interval, event_end and received_at
    in UTC ms, funding_rate = latest settled 8h rate (not predicted), funding_at,
    long_liquidation_usd = executed long liquidations in that interval.
    Require complete non-sampled source coverage and source URL. At the first
    decision close after receipt, max age one bar, settled funding <= -0.0003,
    liquidations >=3x median of PRIOR 42 intervals, current green candle. Require
    strictly positive prior median. Seven-bar cooldown between signals (28h).
    Missing coverage is an error, never zero liquidations. Source sampling and
    receive-time provenance must be audited externally before evaluation.
    Entry, ATR exits, size and common proposed gates above. Not the old standalone
    funding extreme or OI-flush rule: both funding and actual liquidations required.
    """
    validate_bars(b)
    rows = sorted(observations, key=lambda e: e["event_end"])
    if not rows:
        raise ValueError("liquidation observations required")
    for i, e in enumerate(rows):
        if (not e.get("source_url") or not e.get("complete") or
                not e["event_end"] <= e["received_at"] <= e["event_end"] + BAR_MS or
                e["funding_at"] > e["event_end"] or
                e["event_end"] - e["funding_at"] > 8 * 3_600_000 or
                not math.isfinite(e["funding_rate"]) or
                not math.isfinite(e["long_liquidation_usd"]) or
                e["long_liquidation_usd"] < 0 or
                (i and e["event_end"] - rows[i - 1]["event_end"] != BAR_MS)):
            raise ValueError("invalid or incomplete funding/liquidation history")
    ready = []
    for i in range(42, len(rows)):
        e = rows[i]
        base = median(x["long_liquidation_usd"] for x in rows[i - 42:i])
        active = (base > 0 and e["long_liquidation_usd"] >= 3 * base and
                  e["funding_rate"] <= -0.0003)
        ready.append((e["received_at"], float(active)))
    if len({t for t, _ in ready}) != len(ready):
        raise ValueError("ambiguous receive-time ordering")
    # Only last received event may activate; a later stale event cannot be backdated.
    signal = Series(ready)
    sig, last = [0] * len(b["t"]), -7
    for i, t in enumerate(b["t"]):
        if (i - last >= 7 and signal.at(t + BAR_MS, max_age=BAR_MS) == 1 and
                b["c"][i] > b["o"][i]):
            sig[i], last = 1, i
    return sig


def h3_capitulation(b):
    """Pre-registered 2026-11-07 23:31:28 SAST; H3 one BTC/ETH spot rebound test.

    Capitulation on prior completed 4h bar: close down >=8% versus six bars ago,
    base volume >=2x PRIOR 20-bar mean. Confirmation on current closed 4h bar:
    green candle AND close above capitulation bar high. Enter next open.
    Seven-bar signal cooldown (28h). Planned 24h hold, minimum ordinary decision
    interval 4h; hard stop/TP always active. Common ATR exits, size and proposed
    gates above. This adds delayed confirmation to the already-rejected intraday
    capitulation family; it is a new hypothesis, not a retest or tuned rescue.
    """
    validate_bars(b)
    sig, last = [0] * len(b["t"]), -7
    for i in range(21, len(sig)):
        k = i - 1
        base = sum(b["v"][k - 20:k]) / 20
        if (i - last >= 7 and base > 0 and
                b["c"][k] / b["c"][k - 6] - 1 <= -0.08 and
                b["v"][k] >= 2 * base and b["c"][i] > b["o"][i] and
                b["c"][i] > b["h"][k]):
            sig[i], last = 1, i
    return sig


def replay(b, signals, spread_bps=10.0, cost_multiplier=1):
    """Frozen common execution, synthetic verification only until gates confirmed.

    Reuse zoo ATR14; stop-first resolves OHLC ambiguity conservatively. Return
    research-metrics compatible records, terminal-open flag and warmup skips.
    No capital compounding: each trade is $10 notional, costs charged both sides.
    """
    validate_bars(b)
    if len(signals) != len(b["t"]) or any(s not in (0, 1) for s in signals):
        raise ValueError("expected one long/cash signal per bar")
    if not math.isfinite(spread_bps) or spread_bps < 0 or cost_multiplier not in (1, 2, 4):
        raise ValueError("invalid costs")
    atr = zoo.atr(b["h"], b["l"], b["c"], 14)
    pos, trades, skipped = None, [], 0
    cost = 2 * (5 + 2 + spread_bps / 2) * cost_multiplier
    for i in range(1, len(signals)):
        o, h, l = (b[k][i] for k in "ohl")
        if pos is None and signals[i - 1]:
            a = atr[i - 1]
            if not zoo.fin(a) or a <= 0 or o - 1.5 * a <= 0:
                skipped += 1
            else:
                pos = (i, o, o - 1.5 * a, o + 3 * a)
        if pos is None:
            continue
        j, entry, stop, target = pos
        px, why = None, None
        if o <= stop:
            px, why = o, "stop_gap"
        elif o >= target:
            px, why = o, "target_gap"
        elif i - j >= 6:
            px, why = o, "time"
        elif l <= stop:
            px, why = stop, "stop"
        elif h >= target:
            px, why = target, "target"
        if px is not None:
            gross = (px / entry - 1) * 10000
            trades.append({"entry_time": b["t"][j], "exit_time": b["t"][i],
                           "gross_bps": gross, "net_bps": gross - cost,
                           "net_usdt": 10 * (gross - cost) / 10000,
                           "exit_reason": why})
            pos = None
    return {"trades": trades, "terminal_open": pos is not None, "warmup_skips": skipped}
