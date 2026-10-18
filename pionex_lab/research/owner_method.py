"""CLO-64 owner-method v1; research signals only, no execution or network.

FROZEN 2026-10-18T09:53:29Z, before evaluation. Changed definitions are new
trials. Entry features belong to CLO-65; missing features mean STAND_ASIDE.
S/R = confirmed 2-left/2-right hourly pivots in the last 168 closed bars plus
the three largest 48-bin typical-price volume-profile nodes (OHLCV proxy).
OB = last opposite candle within 6 bars preceding a >=2 ATR(14) directional
close displacement within 3 bars; known only after that displacement closes.
Big OB = originating volume >=1.5 times prior 20-bar mean. Active until a
closed bar invalidates its far edge. Touch = price within 0.5 ATR of zone.
Long: support touch + bullish OB + big bullish OB below; veto resistance or
bearish OB within 1 ATR above. Short: resistance touch + bearish OB + big
bearish OB above; veto support or bullish OB within 1 ATR below. Require
point-in-time analyst consensus in that direction, >=2 distinct analysts,
published AND ingested in last 24h. Otherwise STAND_ASIDE. Heatmap = Wave
Lab's estimated OI liquidation levels, NOT observed positions; require an
active target cluster in trade direction, frozen at entry. News veto +/-60m
around known FOMC/CPI/NFP, or absolute 1h move >=3 prior ATRs. No fabricated
historical heatmap/news/analyst features. CLO-65 must version these contracts.

MARKET-READ EXIT, symmetric long/short, hourly CLOSED bars, next-open fill:
(a) stall: after >=N+1 bars, no favorable high/low exceeding the best prior
    favorable high/low during N=6 consecutive bars (neighbours N=4,8).
(b) failed retest: last two confirmed 1-left/1-right favorable pivots within
    0.5 ATR of target are falling (long) / rising (short), close below/above.
(c) fade: within 1 ATR of target, 3-bar signed momentum <=0 and last 3 mean
    volume <50% of preceding 12; OR new 3-bar favorable extreme with smaller
    signed 3-bar momentum than the preceding 3 (divergence).
(d) frozen target cluster's model mass <=25% of entry mass, OR its matched
    price moves >=0.5 entry ATR farther away. Require same cluster identity,
    timestamp <=decision, age <=1h; absent history is UNKNOWN, never true.
(e) time: elapsed hours >=training-only Kaplan-Meier median time-to-target;
    >=5 observed hits required; unhit episodes right-censored, unresolved
    episodes excluded until their horizon ends strictly before entry. No
    median crossing -> UNKNOWN. No fitting on this bot or later bots.
(f) known FOMC/CPI/NFP in next 60m, publication and ingestion <=decision.
Any trigger proposes CLOSE_RESEARCH_ONLY only if supplied reconciled net
flatten P&L (all fees/funding and exit cost included) >0. No trailing stop.
No target -> no exit inference. Missing/stale/nonfinite state -> UNKNOWN.
There is no OPEN, ADD, sizing, mandate, signer or live-monitor integration.

TEST PROTOCOL: audit all 65 expected owner bots; deduplicate by bot id, keep
running/censored/missing-target records in denominators. Actual close reason
is a label, not inferred from grid bounds. Targets require snapshots before
the decision; latest post-close settings are descriptive only. All source
bars must be complete, gap-free, symbol matched; spot for perp is a PROXY.
Compare exit vs target-or-24h hold on identical state/fills at 3/5/10/20/40x;
liquidation first on ambiguous candles; pending exit fills at next open and
must still bank positive net P&L. Fee 0.05%/side + measured spread + 0.05%
market slippage; 2x/4x all-cost stresses. Missing grid inventory/fills means
actual net holding counterfactual and ruin are UNAVAILABLE, not zero.
Use chronological day-clustered 60/20/20 train/validation/test, purge 24h,
three rolling-origin folds and final untouched test; overlapping owner bots
are not independent observations. No retrospective target can qualify OOS.
Apply CLO-44's unchanged T1..T9 thresholds; unavailable tests fail eligibility.
Also require >=200 OOS exits/60 days, positive paired benefit lower bound
(20-day blocks), benefit timing-null p <= registry-adjusted limit, positive
2x/4x costs, all neighbouring settings, walk-forward and Pionex forward
record. Trial budget: base plus stall4/stall8/fade0.4/fade0.6 =5; no tuning.
Absent causal owner labels/features, report INCOMPLETE, never PASS.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import mean

HOUR = 3_600_000
NEWS = frozenset(("FOMC", "CPI", "NFP"))


@dataclass(frozen=True)
class Bar:
    time: int  # opening time; closed/available at time + HOUR
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Event:
    kind: str
    time: int
    published: int
    ingested: int


@dataclass(frozen=True)
class Cluster:
    identity: str
    time: int
    price: float
    mass: float


@dataclass(frozen=True)
class Position:
    direction: str
    entry_time: int
    target: float
    target_known_at: int
    entry_atr: float
    cluster: Cluster | None = None


@dataclass(frozen=True)
class FlattenMark:
    time: int
    net_pnl: float  # supplied by reconciled ledger incl. flatten costs


@dataclass(frozen=True)
class TargetOutcome:
    entry: int
    resolved: int  # target hit or censoring horizon, not current snapshot time
    hours: float
    hit: bool


@dataclass(frozen=True)
class ReplayFrame:
    """Caller-supplied, fee-reconciled ledger for an identical frozen grid path.

    NO inventory model is invented here. Open/close P&L include flatten costs;
    target/liq values include their respective exit costs and funding. Missing
    settlement when its barrier is touched invalidates the replay.
    """
    bar: Bar
    open_net_pnl: float
    close_net_pnl: float
    liquidated_at_open: bool = False
    liquidation_touched: bool = False
    liquidation_net_pnl: float | None = None
    target_net_pnl: float | None = None
    cluster: Cluster | None = None


def median_target_hours(outcomes, before):
    """Training-only KM median; censoring is retained, not dropped as losers."""
    rows = [r for r in outcomes if r.entry < r.resolved < before
            and math.isfinite(r.hours) and r.hours > 0]
    if sum(r.hit for r in rows) < 5:
        return None
    at_risk, survival = len(rows), 1.0
    for hours in sorted(set(r.hours for r in rows)):
        group = [r for r in rows if r.hours == hours]
        survival *= 1 - sum(r.hit for r in group) / at_risk
        if survival <= 0.5:
            return hours
        at_risk -= len(group)
    return None


def valid_bars(bars, now):
    if not bars:
        return False
    for i, b in enumerate(bars):
        values = (b.open, b.high, b.low, b.close, b.volume)
        if (not all(math.isfinite(v) for v in values) or min(values[:4]) <= 0
                or b.volume < 0 or not b.low <= min(b.open, b.close) <= max(b.open, b.close) <= b.high
                or b.time + HOUR > now or (i and b.time - bars[i - 1].time != HOUR)):
            return False
    return True


def exit_signal(bars, position, now, mark, *, events=(), cluster=None,
                training=(), stall=6, fade_ratio=0.5):
    """Pure research proposal. Input bars are completed hourly observations only."""
    if stall < 1 or not 0 < fade_ratio < 1:
        raise ValueError("invalid frozen-rule parameters")
    def unknown(reason):
        return {"action": "UNKNOWN", "reasons": [], "unknown": [reason]}
    if not valid_bars(bars, now) or now - (bars[-1].time + HOUR) >= HOUR:
        return unknown("invalid_or_stale_bars")
    p = position
    if (p.direction not in ("long", "short") or not math.isfinite(p.target) or p.target <= 0
            or not math.isfinite(p.entry_atr) or p.entry_atr <= 0
            or p.entry_time > now or p.target_known_at > p.entry_time):
        return unknown("missing_causal_target_or_position")
    if (mark is None or mark.time > now or now - mark.time > 5_000
            or not math.isfinite(mark.net_pnl)):
        return unknown("missing_fresh_reconciled_flatten_mark")
    life = [b for b in bars if b.time >= p.entry_time]
    if not life:
        return unknown("no_post_entry_closed_bars")
    sign = 1 if p.direction == "long" else -1
    favorable = [b.high if sign == 1 else -b.low for b in life]
    closes = [sign * b.close for b in life]
    target = sign * p.target
    reasons, missing = [], []
    if len(life) >= stall + 1 and max(favorable[-stall:]) <= max(favorable[:-stall]):
        reasons.append("stall")
    pivots = [favorable[i] for i in range(1, len(life) - 1)
              if favorable[i] > favorable[i - 1] and favorable[i] > favorable[i + 1]
              and abs(favorable[i] - target) <= 0.5 * p.entry_atr]
    if len(pivots) >= 2 and pivots[-1] < pivots[-2] and closes[-1] < target:
        reasons.append("failed_retests")
    if len(life) >= 16 and 0 < target - closes[-1] <= p.entry_atr:
        momentum = closes[-1] - closes[-4]
        previous_momentum = closes[-4] - closes[-7]
        volume_fade = (momentum <= 0 and mean(b.volume for b in life[-3:])
                       < fade_ratio * mean(b.volume for b in life[-15:-3]))
        divergence = (max(favorable[-3:]) > max(favorable[-6:-3])
                      and momentum < previous_momentum)
        if volume_fade or divergence:
            reasons.append("momentum_volume_fade" if volume_fade else "divergence")
    initial = p.cluster
    if (initial is not None and cluster is not None and cluster.identity == initial.identity
            and initial.time <= p.entry_time and 0 <= p.entry_time - initial.time <= HOUR
            and initial.time <= cluster.time <= now and 0 <= now - cluster.time <= HOUR
            and all(math.isfinite(x) for x in (initial.mass, initial.price, cluster.mass, cluster.price))
            and initial.mass > 0 and cluster.mass >= 0 and min(initial.price, cluster.price) > 0):
        if cluster.mass <= 0.25 * initial.mass:
            reasons.append("cluster_consumed")
        elif sign * (cluster.price - initial.price) >= 0.5 * p.entry_atr:
            reasons.append("cluster_moved_away")
    else:
        missing.append("heatmap_cluster")
    median = median_target_hours(training, p.entry_time)
    if median is None:
        missing.append("training_median")
    elif (now - p.entry_time) / HOUR >= median:
        reasons.append("time_stop")
    for e in events:
        if e.kind in NEWS and max(e.published, e.ingested) <= now and 0 <= e.time - now <= HOUR:
            reasons.append("news_ahead")
            break
    return {"action": "CLOSE_RESEARCH_ONLY" if reasons and mark.net_pnl > 0 else "HOLD",
            "reasons": reasons, "unknown": missing, "net_flatten_pnl": mark.net_pnl,
            "median_target_hours": median, "decision_time": now,
            "fill_policy": "next_open_recheck_net_profit_and_liquidation"}


def paired_replay(frames, position, *, events=(), training=(), stall=6, fade_ratio=0.5):
    """Paired exit-vs-hold replay, <=24h horizon, supplied net grid ledgers.

    A next-open exit precedes that candle's later extremes. A liquidation gap
    at that open precedes the pending exit. Hold settles at target, liquidation
    or the 24h horizon, and needs the corresponding ledger value.
    """
    if not frames:
        raise ValueError("missing ledger frames")
    bars = [f.bar for f in frames]
    if not valid_bars(bars, bars[-1].time + HOUR):
        raise ValueError("invalid or gapped replay bars")
    p = position
    if (p.direction not in ("long", "short") or p.target_known_at > p.entry_time
            or not math.isfinite(p.target) or p.target <= 0
            or bars[0].time != p.entry_time or p.entry_time % HOUR):
        raise ValueError("replay requires causal target and hour-aligned entry")
    if any(not math.isfinite(v) for f in frames for v in (f.open_net_pnl, f.close_net_pnl)):
        raise ValueError("nonfinite ledger")
    market, hold, pending, reason = None, None, False, None
    consumed = []
    for f in frames:
        b = f.bar
        if b.time >= p.entry_time + 24 * HOUR:
            break
        # Open liquidation beats pending exit; later intrabar liquidation does
        # not retroactively beat an executable, profitable next-open close.
        if f.liquidated_at_open and hold is None:
            if f.liquidation_net_pnl is None or not math.isfinite(f.liquidation_net_pnl):
                raise ValueError("missing liquidation settlement")
            hold = f.liquidation_net_pnl
            if market is None:
                market, reason = hold, "liquidation_gap"
        if pending and market is None:
            if f.open_net_pnl > 0:
                market, reason = f.open_net_pnl, "market_read_exit"
            pending = False
        reached = b.high >= p.target if p.direction == "long" else b.low <= p.target
        if hold is None and (f.liquidation_touched or reached):
            settlement = f.liquidation_net_pnl if f.liquidation_touched else f.target_net_pnl
            if settlement is None or not math.isfinite(settlement):
                raise ValueError("missing target/liquidation settlement")
            hold = settlement
            if market is None:
                market, reason = settlement, "liquidation" if f.liquidation_touched else "target"
        consumed.append(b)
        if b.time + HOUR == p.entry_time + 24 * HOUR and hold is None:
            hold = f.close_net_pnl
            if market is None:
                market, reason = hold, "horizon"
        if hold is not None:
            break
        if market is None:
            decision = exit_signal(consumed, p, b.time + HOUR,
                                   FlattenMark(b.time + HOUR, f.close_net_pnl),
                                   events=events, training=training, cluster=f.cluster,
                                   stall=stall, fade_ratio=fade_ratio)
            pending = decision["action"] == "CLOSE_RESEARCH_ONLY"
    return {"market_exit_net_pnl": market, "hold_net_pnl": hold,
            "paired_net_benefit": market - hold if market is not None and hold is not None else None,
            "exit_reason": reason, "complete_pair": market is not None and hold is not None,
            "research_only": True}


def entry_signal(features):
    """CLO-65 integration boundary: only complete, causal feature sets qualify."""
    required = ("causal_complete", "news_safe", "analyst_count", "analyst_bias", "target_cluster",
                "support_touch", "bullish_ob", "big_ob_below", "overhead_veto",
                "resistance_touch", "bearish_ob", "big_ob_above", "underfoot_veto")
    if any(k not in features or features[k] is None for k in required):
        return "STAND_ASIDE"
    if (features["causal_complete"] is not True or features["news_safe"] is not True
            or features["analyst_count"] < 2 or not features["target_cluster"]):
        return "STAND_ASIDE"
    if (features["analyst_bias"] == "long" and features["support_touch"]
            and features["bullish_ob"] and features["big_ob_below"] and not features["overhead_veto"]):
        return "LONG_RESEARCH_ONLY"
    if (features["analyst_bias"] == "short" and features["resistance_touch"]
            and features["bearish_ob"] and features["big_ob_above"] and not features["underfoot_veto"]):
        return "SHORT_RESEARCH_ONLY"
    return "STAND_ASIDE"
