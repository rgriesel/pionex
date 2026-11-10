"""Research-only H6b preparation. No historical loader, CLI, or order path."""
from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal

from pionex_lab.research.h5b_clo258 import _bar
from research.own_edge_b_clo248 import H, lead_stats

SPEC_SHA256 = "bef1e6277584f4a7985760cbeb30a6213b6631cf5df282248af470197c13f873"
TRIAL_ID = 173


def execution_cost(hours, mult=1, half_spread_bps=None):
    """Passive entry 2+2bps; forced exit 6+2bps; half spread on both legs."""
    spread = 5.0 if half_spread_bps is None else half_spread_bps
    if (mult not in (1, 2, 3, 4) or not math.isfinite(spread) or spread < 0
            or not math.isfinite(hours) or hours < 0):
        raise ValueError("invalid fixed execution assumptions")
    return (12.0 + 2 * spread) * mult, hours / 8.0


def _through(price, limit, tick, side):
    # Decimal comparison avoids counting a sub-tick move due to float epsilon.
    return side * (Decimal(str(limit)) - Decimal(str(price))) >= Decimal(str(tick))


def _position(bars, t0, fill_i, side, entry, gap, sd, mult, spread, at_open):
    stop = entry * math.exp(-side * 1.5 * sd * math.sqrt(8))
    tp = entry * math.exp(side * .5 * gap)
    for k in range(fill_i, fill_i + 9):
        b = _bar(bars, k)
        if b is None:
            return None
        o, h, l, c = b
        # Open prices preceding an intrabar fill cannot be used as stop fills.
        known_open = k > fill_i or at_open
        if known_open and (o <= stop if side == 1 else o >= stop):
            px, reason, hours = o, "stop", k - fill_i
        elif k == fill_i + 8:
            px, reason, hours = o, "time", 8
        elif l <= stop if side == 1 else h >= stop:
            px, reason, hours = stop, "stop", k - fill_i + 1
        elif ((h >= tp if side == 1 else l <= tp)
              and (known_open or (c >= tp if side == 1 else c <= tp))):
            # For intrabar entry a favorable extreme alone could precede entry.
            # Close beyond TP establishes a post-entry crossing; else defer TP.
            px, reason, hours = tp, "tp", k - fill_i + 1
        else:
            continue
        gross = side * (px / entry - 1) * 1e4
        friction, funding = execution_cost(hours, mult, spread)
        return dict(entry_time=t0 + fill_i * H, exit_time=t0 + (fill_i + hours) * H,
                    exit_bar=k, side=side, entry=entry, exit=px, stop=stop, tp=tp,
                    exit_reason=reason, hours=hours, notional=1.0,
                    inventory_notional_hours=float(hours), gross_bps=gross,
                    execution_cost_bps=friction, funding_bps=funding,
                    net_bps=gross - friction - funding)
    raise AssertionError("unreachable")


def h6b(stats, alt, t0, tick, mult=1, half_spread_bps=None):
    """Frozen H6b v1 / CLO-259 / existing trial 173; PREPARATION ONLY.

    Implementation registered 2026-11-10T03:51:00+02:00 SAST before tests.
    Specification frozen 2026-11-08T03:45:19+02:00 SAST, SHA256
    bef1e6277584f4a7985760cbeb30a6213b6631cf5df282248af470197c13f873,
    research/registrations/clo256_h6b_v1.md. ONE eventual evaluation, no tuning.
    Board confirmation under CLO-253 is required before historical evaluation.

    Data: same hourly Binance spot PROXY as CLO-248, each coin from available
    2019-01 history, cutoff 2026-10-12 23:00 UTC. Final entries >=2023-04-01.
    Previously exposed eras: adaptive successor screening, NEVER untouched OOS.
    BTC/ETH same-sign 4h leader; reuse lead_stats unchanged: trailing 720h
    normalization with >=360 valid observations. abs(z)>=3.0. Universe unchanged:
    ADA,AVAX,BNB,DOGE,LINK,LTC,SOL,XRP; direction=sign(leader); alt signed 4h
    return <50% signed leader. Freeze gap and population sd of 168 1h alt log
    returns at signal close. No signal before complete alt lookbacks.

    At open i+1 submit simulated limit at that open. No submission-bar fill.
    Fill only i+2..i+5 inclusive, strict through by >=one verified Pionex tick;
    otherwise expire, never chase. Fill at limit, no favorable gap improvement.
    One pending order/position per coin; signals while busy ignored. Full
    notional 1x. TP=fill*exp(direction*0.5*gap); SL=fill*exp(-direction*1.5*
    sd1h*sqrt(8)); time exit at open after 8 elapsed fill-bar hours. Stop wins
    ambiguous bars, stop gaps fill worse open; TP receives no gap improvement.
    Intrabar fill: no pre-entry open stop, and TP extreme alone is ambiguous;
    only close beyond TP proves a post-entry crossing on that bar. An open
    already through limit fills at limit, then all exit rules are active.
    Intrabar exits reserve the containing hour for funding/exposure, following
    H5b. Missing pending bar or held inventory halts coin as unresolved; never
    silently drop possible losses and resume. Missing submission never fills.

    Costs: verified passive entry 2bps maker+2bps adverse selection/slippage;
    forced exit including TP 6bps fee allowance+2bps slippage. Each leg pays
    measured half-spread or frozen 5bps/side fallback. No spread capture.
    Funding 1bp/8h held full notional both directions; friction stresses
    2x/3x/4x, funding unchanged. Official fee/tick/minimum evidence required.
    Candle strict-through cannot establish queue priority or post-only
    acceptance; separately registered quote-based forward evidence required.

    Frozen gates: >=100 trades full AND final; mean net>0 both; final PF>=1.2;
    final mean net>0 at 2x costs; final mean excluding best>0; final one-sided
    95% three-day block-bootstrap lower bound>0. Either era <100 => INSUFFICIENT;
    otherwise any failed gate => FAIL. Reuse research.metrics summarize and
    block_bootstrap_lower, parent seed 20260928 and bootstrap implementation.
    Report Bonferroni alpha=0.05/ntrials, ntrials=max(295,SUM(weight) at run),
    and 3x/4x diagnostics, no gate changes. Freeze row fingerprints and reserve
    create-only report BEFORE evaluation; reuse trial 173, never add a trial.
    FAIL/INSUFFICIENT: WHY/WHAT/NEXT separately registered queued successor.
    PASS stays open for CEO-assigned independent Red Team, maxReviewRounds 2;
    never live eligibility or proof of profit. This function performs no IO.
    """
    execution_cost(0, mult, half_spread_bps)
    if not math.isfinite(tick) or tick <= 0:
        raise ValueError("positive verified tick required")
    lr, z = stats
    if len(lr) != len(alt) or len(z) != len(alt):
        raise ValueError("aligned leader and alt grids required")
    trades, events, busy = [], [], -1
    for i in range(724, len(alt)):
        if i <= busy or z[i] is None or abs(z[i]) < 3:
            continue
        window = [_bar(alt, k) for k in range(i - 168, i + 1)]
        if any(b is None for b in window):
            events.append(dict(signal=i, reason="missing_lookback"))
            continue
        if lr[i] is None or not math.isfinite(lr[i]) or not math.isfinite(z[i]) or lr[i] == 0:
            raise ValueError("invalid leader statistics")
        side = 1 if lr[i] > 0 else -1
        ra = math.log(window[-1][3] / window[-5][3])
        if side * ra >= .5 * side * lr[i]:
            continue
        gap = side * (lr[i] - ra)
        rets = [math.log(b[3] / a[3]) for a, b in zip(window, window[1:])]
        mu = sum(rets) / 168
        sd = math.sqrt(sum((r - mu)**2 for r in rets) / 168)
        if sd <= 0:
            events.append(dict(signal=i, reason="zero_volatility"))
            continue
        submission = _bar(alt, i + 1)
        busy = i + 1
        if submission is None:
            events.append(dict(signal=i, reason="missing_submission"))
            continue
        entry, fill_i = submission[0], None
        for k in range(i + 2, i + 6):
            busy = k
            b = _bar(alt, k)
            if b is None:
                events.append(dict(signal=i, reason="unresolved_pending_gap_or_end"))
                return trades, events
            if _through(b[2] if side == 1 else b[1], entry, tick, side):
                fill_i = k
                break
        if fill_i is None:
            events.append(dict(signal=i, reason="expired_unfilled"))
            continue
        at_open = _through(b[0], entry, tick, side)
        trade = _position(alt, t0, fill_i, side, entry, gap, sd, mult, half_spread_bps, at_open)
        if trade is None:
            events.append(dict(signal=i, entry=fill_i, reason="unresolved_position_gap_or_end"))
            break
        busy = trade.pop("exit_bar")
        trade.update(signal_time=t0 + i*H, submission_time=t0 + (i+1)*H,
                     gap=gap, sd1h=sd, tick=tick)
        trades.append(trade)
    return trades, events


def row_fingerprint(t0, bars):
    """Hash exact aligned consumed OHLC rows, including missing timestamps."""
    digest = hashlib.sha256()
    for i, b in enumerate(bars):
        row = [t0 + i*H, None if b is None else list(_bar(bars, i))]
        digest.update((json.dumps(row, separators=(",", ":"), allow_nan=False)+"\n").encode())
    return digest.hexdigest()


def run_once(connection, report_path, spec_bytes, fingerprints, evaluate):
    """Create-only harness. Caller supplies board-updated existing trial, never approval by flag.

    No invocation in readiness work. Existing registry must carry CONFIRMED
    gate_status, board_confirmation_comment_id and AUTHORIZED evaluation_state.
    Caller must verify that comment's board authorship and scope under CLO-253.
    On interruption leave EVALUATING/started as evidence; never automatic rerun.
    """
    if hashlib.sha256(spec_bytes).hexdigest() != SPEC_SHA256:
        raise ValueError("frozen specification mismatch")
    if not fingerprints or any(len(v) != 64 or any(c not in '0123456789abcdef' for c in v)
                               for v in fingerprints.values()):
        raise ValueError("frozen row fingerprints required")
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT ref,params,weight FROM trials WHERE id=?", (TRIAL_ID,)).fetchone()
        if row is None or row[0] != 'CLO-256:H6b:v1' or row[2] != 1:
            raise ValueError("existing trial 173 reservation required")
        params = json.loads(row[1])
        if (params.get('sha256') != SPEC_SHA256 or params.get('gate_status') != 'CONFIRMED'
                or not params.get('board_confirmation_comment_id')
                or params.get('evaluation_state') != 'AUTHORIZED'):
            raise PermissionError("CLO-253 board confirmation and one evaluation authorization required")
        # File exclusive-create and DB write lock precede callback; duplicate
        # or interrupted attempts cannot silently evaluate another time.
        with report_path.open('x', encoding='utf-8') as f:
            json.dump(dict(state='started', trial_id=TRIAL_ID, fingerprints=fingerprints), f)
        params['evaluation_state'] = 'EVALUATING'
        connection.execute("UPDATE trials SET params=?,result='EVALUATING' WHERE id=?",
                           (json.dumps(params), TRIAL_ID))
        ntrials = max(295, connection.execute("SELECT SUM(weight) FROM trials").fetchone()[0])
    result = evaluate(ntrials)
    report = dict(state='complete', trial_id=TRIAL_ID, ntrials=ntrials,
                  spec_sha256=SPEC_SHA256, fingerprints=fingerprints, results=result)
    report_path.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    with connection:
        params['evaluation_state'] = 'COMPLETE'
        connection.execute("UPDATE trials SET params=?,result='COMPLETE; see report' WHERE id=?",
                           (json.dumps(params), TRIAL_ID))
    return report
