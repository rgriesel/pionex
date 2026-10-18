"""CLO-57 research only. Frozen protocol: research/staggered_clo57_prereg.md."""
from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
from datetime import datetime, timezone
from pathlib import Path

from . import cta
from ..paths import Paths
from ..research import luck


def simulate(data, weekday=None, cost=None, capital=None):
    """CTA v1.1 bookkeeping, optionally allowing rebalances on one UTC weekday."""
    if weekday is not None and weekday not in range(7):
        raise ValueError('weekday must be 0..6 or None')
    coins = tuple(data)
    days = sorted(set().union(*(set(data[s]) for s in coins)))
    w, mark, out, eq, pending = {}, {}, [], 1.0, None
    for t in days:
        rets = {}
        for s in w:
            if t in data[s]:
                rets[s] = data[s][t]['o'] / mark[s] - 1
                mark[s] = data[s][t]['o']
        w, port = cta.drift(w, rets)
        if pending is not None:
            t0, paid, gross, traded = pending
            r = (1 - paid) * (1 + port) - 1
            eq *= 1 + r
            out.append((t0, r, gross, traded))
            pending = None
        avail = [s for s in coins if t in data[s] and t - cta.DAY in data[s]
                 and data[s][t - cta.DAY]['age'] >= 120]
        if not avail:
            if w:
                pending = (t, 0.0, sum(w.values()), 0.0)
            continue
        active = weekday is None or datetime.fromtimestamp(t / 1000, timezone.utc).weekday() == weekday
        paid, traded = 0.0, 0.0
        if active:
            targets = {}
            for s in avail:
                row = data[s][t - cta.DAY]
                if cta.signal(row, 'tsmom_vote'):
                    vol = row['vol']
                    targets[s] = (0.40 / len(avail)) / vol if vol == vol and vol > 0 else 1 / len(avail)
            gross = sum(targets.values())
            if gross > 1:
                targets = {s: v / gross for s, v in targets.items()}
            tradable = {s for s in coins if t in data[s]}
            usdt = None if capital is None else capital * min(eq, 1.0)
            w, paid, traded = cta.rebalance(w, targets, tradable, equity=usdt, cost=cost)
            for s in w:
                if s in tradable:
                    mark[s] = data[s][t]['o']
        pending = (t, paid, sum(w.values()), traded)
    return out


def combine(books):
    """Equal INITIAL capital, subsequently NAV weighted without cross-sleeve transfers."""
    if not books or not books[0]:
        raise ValueError('empty books')
    dates = [row[0] for row in books[0]]
    if any([row[0] for row in book] != dates for book in books):
        raise ValueError('unaligned sleeves')
    nav = [1.0 / len(books)] * len(books)
    out = []
    for rows in zip(*books):
        total = sum(nav)
        weights = [v / total for v in nav]
        out.append((rows[0][0], *(sum(w * row[k] for w, row in zip(weights, rows)) for k in (1, 2, 3))))
        nav = [v * (1 + row[1]) for v, row in zip(nav, rows)]
    return out


def bootstrap_difference(a, b):
    if [x[0] for x in a] != [x[0] for x in b]:
        raise ValueError('unaligned comparison')
    xs = [x[1] - y[1] for x, y in zip(a, b)]
    n, block = len(xs), 20
    rng = random.Random(20261018)
    means = []
    for _ in range(2000):
        sample = []
        while len(sample) < n:
            start = rng.randrange(n)
            sample.extend(xs[(start + j) % n] for j in range(min(block, n - len(sample))))
        means.append(statistics.fmean(sample))
    means.sort()
    return {'mean_bps': statistics.fmean(xs) * 1e4, 'lower_bps': means[50] * 1e4,
            'upper_bps': means[1949] * 1e4, 'block_days': block, 'resamples': 2000, 'seed': 20261018}


def verdict(base, combined, base4, combined4):
    return 'PASS' if abs(combined - base) <= 0.10 and combined4 - base4 >= -0.15 else 'FAIL'


def run(paths=None):
    paths = paths or Paths.default()
    dst = paths.reports / 'staggered_clo57.json'
    # Exclusive creation also guards against concurrent or repeated real-data runs.
    with dst.open('x', encoding='utf-8') as handle:
        root = Path(__file__).resolve().parents[2]
        prereg = root / 'research/staggered_clo57_prereg.md'
        registry = paths.root / 'trials.db'
        before = luck.trial_count(registry)
        for name in [*(f'weekday_{k}' for k in range(7)), 'combined', 'capital_100', 'capital_1000']:
            luck.record_trial(registry, 'clo57', name, 'staggered_clo57',
                              params={'protocol_sha256': hashlib.sha256(prereg.read_bytes()).hexdigest()},
                              result='pre-registered one-shot; see staggered_clo57.json')
        count = luck.trial_count(registry)
        data = cta.load(paths)
        coverage = {}
        for s, rows in data.items():
            days = sorted(rows)
            if not days:
                raise ValueError(f'empty symbol {s}')
            if any(not math.isfinite(row['o']) or row['o'] <= 0 for row in rows.values()):
                raise ValueError(f'invalid open {s}')
            coverage[s] = {'rows': len(rows), 'first_ms': days[0], 'last_ms': days[-1],
                           'missing_calendar_days': sum((b - a) // cta.DAY - 1 for a, b in zip(days, days[1:]))}
        # Reject incomplete current UTC daily bars, independent of data snapshot age.
        today = int(datetime.now(timezone.utc).timestamp() * 1000) // cta.DAY * cta.DAY
        if any(max(rows) >= today for rows in data.values()):
            raise ValueError('incomplete current daily bar in source')
        fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True, allow_nan=True).encode()).hexdigest()
        rep = {'issue': 'CLO-57', 'timestamp_utc': datetime.now(timezone.utc).isoformat(),
               'venue': 'PROXY Binance daily; not Pionex proof or live eligibility',
               'protocol_sha256': hashlib.sha256(prereg.read_bytes()).hexdigest(),
               'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'cta_sha256': hashlib.sha256(Path(cta.__file__).read_bytes()).hexdigest(),
               'data_sha256': fingerprint, 'coverage': coverage,
               'trials_before': before, 'trials_after': count, 'costs': {}, 'series': {}}
        for multiple in (1, 2, 4):
            cost = {s: multiple * v for s, v in cta.COST.items()}
            baseline = cta.simulate(data, 'tsmom_vote', 'vol', cost=cost)
            regression = simulate(data, cost=cost)
            if len(baseline) != len(regression) or any(a[0] != b[0] or any(abs(x-y)>1e-12 for x,y in zip(a[1:],b[1:]))
                                                     for a,b in zip(baseline,regression)):
                raise AssertionError('daily simulator does not reproduce v1.1')
            books = [simulate(data, weekday=k, cost=cost) for k in range(7)]
            combined = combine(books)
            if [x[0] for x in baseline] != [x[0] for x in combined]:
                raise AssertionError('baseline and combined dates differ')
            bs, cs = cta.stats(baseline), cta.stats(combined)
            weekdays = [cta.stats(book) for book in books]
            sharpes = [x['sharpe'] for x in weekdays]
            folds = []
            remaining = len(baseline) - 730
            for k in range(3):
                start = 730 + k * remaining // 3
                end = 730 + (k+1) * remaining // 3
                folds.append({'baseline': cta.stats(baseline[start:end]),
                              'combined': cta.stats(combined[start:end])})
            rep['costs'][str(multiple)] = {'baseline': bs, 'combined': cs, 'weekdays': weekdays,
                    'weekday_sharpe_range': [min(sharpes), max(sharpes)],
                    'weekday_sharpe_sd': statistics.pstdev(sharpes),
                    'sharpe_difference': cs['sharpe'] - bs['sharpe'],
                    'historical_expanding_origin_folds_not_untouched': folds}
            rep['series'][str(multiple)] = {'baseline': baseline, 'combined': combined, 'weekdays': books}
        primary = rep['costs']['1']
        rep['bootstrap_difference'] = bootstrap_difference(rep['series']['1']['combined'], rep['series']['1']['baseline'])
        rep['deflated_sharpe_diagnostic'] = luck.deflated_sharpe([x[1] for x in rep['series']['1']['combined']], count)
        rep['capital_diagnostics'] = {}
        for capital in (100, 1000):
            rep['capital_diagnostics'][str(capital)] = {
                'baseline': cta.stats(simulate(data, capital=capital)),
                'combined': cta.stats(combine([simulate(data, k, capital=capital/7) for k in range(7)]))}
        rep['verdict'] = verdict(primary['baseline']['sharpe'], primary['combined']['sharpe'],
                                 rep['costs']['4']['baseline']['sharpe'], rep['costs']['4']['combined']['sharpe'])
        rep['limitations'] = ['All history previously available to researchers; folds are not untouched OOS.',
            'Fixed surviving 10-coin universe; stale historical Pionex spread estimates; daily bar proxy fills.',
            'No hourly timing study or Pionex tracking check; no live promotion authorized by this test.',
            'Combined sleeves have equal initial allocation and drift thereafter; no free daily redistribution.',
            'DSR diagnostic is not the full luck suite; PASS still needs independent review and forward proof.']
        json.dump(rep, handle, indent=1, allow_nan=False)
    return rep


if __name__ == '__main__':
    result = run()
    print(json.dumps({k: result[k] for k in ('verdict', 'costs', 'bootstrap_difference', 'capital_diagnostics',
                                             'deflated_sharpe_diagnostic', 'trials_before', 'trials_after')}, indent=1))
