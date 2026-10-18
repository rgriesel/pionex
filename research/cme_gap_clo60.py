"""CLO-60 offline, single frozen PROXY experiment. Never imports execution code.

Run from repository root: py research/cme_gap_clo60.py
Rules: research/cme_gap_clo60_prereg.md. Existing output forbids re-execution.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
HOUR = 3_600_000
UTC = timezone.utc
COST = 0.0007


def ms(d):
    return int(d.timestamp() * 1000)


def iso(t):
    return datetime.fromtimestamp(t / 1000, UTC).isoformat()


def net(entry, exit_price, multiple=1):
    c = COST * multiple
    return exit_price * (1 - c) / (entry * (1 + c)) - 1


def times(sunday):
    # US Central post-2007 rule, valid for this study's 2019+ dates. These local
    # 16:00/17:00 timestamps are after the 02:00 DST transition on Sundays.
    def local(day, hour):
        march = day.replace(month=3, day=1)
        start = march + timedelta(days=(6 - march.weekday()) % 7 + 7)
        november = day.replace(month=11, day=1)
        end = november + timedelta(days=(6 - november.weekday()) % 7)
        offset = -5 if start <= day < end else -6
        return datetime(day.year, day.month, day.day, hour,
                        tzinfo=timezone(timedelta(hours=offset)))
    reopen = local(sunday, 17)
    friday = local(sunday - timedelta(days=2), 16)
    return ms(friday), ms(reopen), ms(reopen + timedelta(hours=1))


def trade(bars, entry_t, target):
    entry = bars[entry_t][0]
    for held in range(4, 121):
        close = bars[entry_t + (held - 1) * HOUR][3]
        reason = ('stop' if close <= entry * .95 else
                  'target' if close >= target else 'time' if held == 120 else None)
        if reason:
            exit_t = entry_t + held * HOUR
            exit_price = bars[exit_t][0]
            return dict(entry_t=entry_t, exit_t=exit_t, entry=entry, exit=exit_price,
                        hours=held, reason=reason,
                        **{f'net_{k}x': net(entry, exit_price, k) for k in (1, 2, 4)})
    raise AssertionError('missing time exit')


def load():
    bars, provenance = {}, []
    for name in ('var/alpha/early_1h.db', 'var/proxy_market.db'):
        path = ROOT / name
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as con:
            rows = con.execute("SELECT open_time,open,high,low,close FROM klines "
                               "WHERE symbol='BTC_USDT' AND interval='60M' AND complete=1 "
                               "AND open_time>=1546300800000 AND open_time<1780012800000 "
                               "ORDER BY open_time").fetchall()
        digest = hashlib.sha256()
        conflicts = 0
        for raw in rows:
            t, *values = raw
            v = tuple(map(float, values))
            o, h, l, c = v
            if t % HOUR or not all(math.isfinite(x) and x > 0 for x in v) or not l <= min(o, c) <= max(o, c) <= h:
                raise ValueError(f'invalid hourly bar at {t}')
            digest.update(json.dumps([t, *v], separators=(',', ':')).encode())
            if t in bars and bars[t] != v:
                conflicts += 1
            bars[t] = v
        provenance.append(dict(path=name, rows=len(rows), sha256=digest.hexdigest(), conflicts=conflicts))
        if conflicts:
            raise ValueError('conflicting overlapping hourly observations')
    return bars, provenance


def opportunities(bars):
    rows, skipped = [], []
    day = datetime(2019, 1, 6).date()
    end = ms(datetime(2026, 5, 29, tzinfo=UTC))
    split = ms(datetime(2023, 4, 1, tzinfo=UTC))
    while day < datetime(2026, 5, 29).date():
        friday, reopen, entry_t = times(day)
        exit_t = entry_t + 120 * HOUR
        if exit_t >= end:
            skipped.append(dict(week=str(day), reason='end purge'))
        elif entry_t < split <= exit_t:
            skipped.append(dict(week=str(day), reason='split purge'))
        elif any(t not in bars for t in range(friday - HOUR, exit_t + HOUR, HOUR)):
            skipped.append(dict(week=str(day), reason='missing hourly observation'))
        else:
            target = bars[friday - HOUR][3]
            gap = bars[reopen][3] / target - 1
            row = dict(week=str(day), entry_t=entry_t, gap=gap, selected=gap <= -.01,
                       control=net(bars[entry_t][0], bars[exit_t][0]),
                       era='final' if entry_t >= split else 'context')
            if row['selected']:
                row.update(trade(bars, entry_t, target))
            rows.append(row)
        day += timedelta(days=7)
    return rows, skipped


def bootstrap(rows, ntrials):
    n = len(rows)
    blocks = []
    for start in range(n):
        b = [rows[(start + j) % n] for j in range(8)]
        blocks.append((sum(r.get('net_1x', 0) for r in b),
                       sum(r['selected'] for r in b), sum(r['control'] for r in b)))
    rng = random.Random(60018)
    samples, advantages = [], []
    selected = [r['net_1x'] for r in rows if r['selected']]
    observed = mean(selected) if selected else 0
    # Exactly n weeks in each draw, including the final partial block.
    for _ in range(50_000):
        s = k = c = 0
        for _ in range(n // 8):
            a, b, d = rng.choice(blocks)
            s += a; k += b; c += d
        start = rng.randrange(n)
        for j in range(n % 8):
            r = rows[(start + j) % n]
            s += r.get('net_1x', 0); k += r['selected']; c += r['control']
        if k:
            samples.append(s / k)
            advantages.append(s / k - c / n)
    samples.sort(); advantages.sort()
    def quantile(xs, q):
        return xs[int(q * (len(xs) - 1))] if xs else None
    p = (1 + sum(x - observed >= observed for x in samples)) / (1 + len(samples))
    return dict(draws=len(samples), block_weeks=8, seed=60018, trials=ntrials,
                lower95=quantile(samples, .05), lower_adjusted=quantile(samples, .05 / ntrials),
                advantage_lower95=quantile(advantages, .05),
                centered_bootstrap_p=p, bonferroni_p=min(1, p * ntrials))


def summarize(rows, ntrials):
    ts = [r for r in rows if r['selected']]
    xs = [r['net_1x'] for r in ts]
    if not ts:
        return dict(events=0, historical_verdict='FAIL: INSUFFICIENT')
    equity = peak = 1
    dd = 0
    for x in xs:
        equity *= 1 + x; peak = max(peak, equity); dd = max(dd, 1 - equity / peak)
    losses = -sum(min(0, x) for x in xs)
    boot = bootstrap(rows, ntrials)
    stats = dict(weeks=len(rows), events=len(ts), mean=mean(xs),
                 mean_2x=mean(r['net_2x'] for r in ts), mean_4x=mean(r['net_4x'] for r in ts),
                 unconditional_mean=mean(r['control'] for r in rows),
                 matched_control_mean=mean(r['control'] for r in ts),
                 advantage=mean(xs) - mean(r['control'] for r in rows),
                 win_rate=sum(x > 0 for x in xs) / len(xs),
                 profit_factor=sum(max(0, x) for x in xs) / losses if losses else None,
                 closed_trade_max_dd=dd, min_hours=min(r['hours'] for r in ts),
                 max_hours=max(r['hours'] for r in ts),
                 mean_without_best=(sum(xs) - max(xs)) / (len(xs) - 1) if len(xs) > 1 else None,
                 yearly={y: dict(events=sum(r['week'][:4] == y for r in ts),
                                 sum_net=sum(r['net_1x'] for r in ts if r['week'][:4] == y))
                         for y in sorted({r['week'][:4] for r in ts})}, bootstrap=boot)
    return stats


def main():
    out = ROOT / 'var/reports/cme_gap_clo60.json'
    # A sentinel is created BEFORE reading price values; failed attempts stay visible.
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('x', encoding='utf-8') as f:
        json.dump(dict(state='started', at=datetime.now(UTC).isoformat()), f)
    con = sqlite3.connect(ROOT / 'var/trials.db')
    with con:
        con.execute('INSERT INTO trials(ts,source,ref,strategy_id,params,data_span,result,weight) '
                    'VALUES(?,?,?,?,?,?,?,1)',
                    (int(datetime.now(UTC).timestamp() * 1000), 'cme_gap', 'CLO-60:v1',
                     'cme_gap_clo60', json.dumps(dict(gap=-.01, min_hours=4, max_hours=120, stop=-.05)),
                     '2019-01..2026-05-28 PROXY', 'STARTED'))
    ntrials = max(247, con.execute('SELECT SUM(weight) FROM trials').fetchone()[0])
    bars, provenance = load()
    rows, skipped = opportunities(bars)
    full = summarize(rows, ntrials)
    final = summarize([r for r in rows if r['era'] == 'final'], ntrials)
    gates = dict(full_sample=full['events'] >= 30, final_sample=final['events'] >= 30,
                 full_adjusted_lb=full['bootstrap']['lower_adjusted'] > 0,
                 final_adjusted_lb=final['bootstrap']['lower_adjusted'] > 0,
                 full_advantage=full['advantage'] >= .003, final_advantage=final['advantage'] >= .003,
                 final_pf=final['profit_factor'] is not None and final['profit_factor'] >= 1.2,
                 final_2x=final['mean_2x'] > 0, final_4x=final['mean_4x'] > 0,
                 final_ex_best=final['mean_without_best'] is not None and final['mean_without_best'] >= 0)
    thirds = []
    span = rows[-1]['entry_t'] - rows[0]['entry_t'] + 1
    for k in range(3):
        ts = [r for r in rows if r['selected'] and min(2, int((r['entry_t'] - rows[0]['entry_t']) * 3 / span)) == k]
        thirds.append(dict(events=len(ts), mean=mean(r['net_1x'] for r in ts) if ts else None))
    report = dict(state='complete', at=datetime.now(UTC).isoformat(), mode='RESEARCH PROXY',
                  historical_verdict='PASS' if all(gates.values()) else 'FAIL',
                  applicability_verdict='FAIL: CME regular weekend closure ended 2026-05-29',
                  gates=gates, full=full, final=final, thirds=thirds, skipped=skipped,
                  provenance=provenance,
                  hashes={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in (Path(__file__), ROOT / 'research/cme_gap_clo60_prereg.md')},
                  caveats=['No current weekend closure; candidate retired',
                           'Spot/time proxy; holidays not modeled; not CME futures observations',
                           'Lab-used history is not globally untouched; no fresh forward proof',
                           'Closed-bar stop can overshoot; first 4h no exit; drawdown excludes intratrade',
                           'Costs estimated from prior Pionex measurement, not historical executable quotes',
                           'Not eligible for live; no full promotion luck-suite on rejected candidate'])
    out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    with (out.parent / 'cme_gap_clo60_trades.csv').open('x', newline='', encoding='utf-8') as f:
        ts = [r for r in rows if r['selected']]
        writer = csv.DictWriter(f, fieldnames=list(ts[0]))
        writer.writeheader(); writer.writerows(ts)
    with con:
        # The registry is append-only. Preserve STARTED and append the disposition
        # with zero additional trial weight; this is bookkeeping, not a new test.
        con.execute('INSERT INTO trials(ts,source,ref,strategy_id,params,data_span,result,weight) '
                    'VALUES(?,?,?,?,?,?,?,0)',
                    (int(datetime.now(UTC).timestamp() * 1000), 'cme_gap', 'CLO-60:v1:verdict',
                     'cme_gap_clo60', '{}', '2019-01..2026-05-28 PROXY', report['historical_verdict']))
    print(json.dumps({k: report[k] for k in ('historical_verdict', 'applicability_verdict', 'gates', 'full', 'final')}))


if __name__ == '__main__':
    main()
