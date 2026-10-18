"""CLO-58: pre-registered 2026-10-18 11:14:33 SAST, before execution results.

One fixed paired implementation-shortfall test, not a portfolio CAGR backtest.
Replay v1.1 tsmom_vote/vol baseline buy/increase weights with 1000 USDT capital,
10 USDT minimum, 2% band. Baseline unchanged, sells unchanged. Fixed baseline
orders isolate execution costs; alternate fills do not feed back into targets.
Chronological walk-forward evaluation 2023-04-01 through 2026-10-11 inclusive,
with baseline warmed on all earlier daily history; no fitting in any window.
These are previously used Binance PROXY prices, not untouched strategy OOS.

Limit is 00:00 open less half measured spread, rounded DOWN to Pionex tick.
Rest fixed for six hours (no intra-hour repricing). Do NOT use the submission
hour: only hours 01..05 qualify, and BOTH low AND close must be <= limit-tick.
Order must be <=1% of that hour's base volume times limit. No wick-only fills.
Otherwise chase at 06:00 OPEN with full taker costs. Every chase is counted,
including >3% next-day rallies. Require all hours 00..06 and next daily open;
any missing order data => INSUFFICIENT, never silently drop or assume fill.
Hourly 00 open must match daily open to 1e-8 relative. OHLC must be valid.

Pionex spot fees 5bps maker AND taker (official /en/fees checked 2026-10-18).
Market cost 5bps fee +2bps slippage +half spread; maker fee 5bps, no slippage.
Spread/ticks from timestamped public Pionex snapshots taken before this test;
using today's spread/tick historically is an explicit proxy limitation.
Savings = baseline buy weight * (market all-in price - alternative all-in
price)/00-open. Thus chase price increases and adverse selection enter net
implementation shortfall; this is NOT a full compounded alternate strategy.

PASS iff >=0.005 annual net saving; maker fills >=60% by count; saving positive
outside BTC/ETH; positive at 4x costs; and 30-day circular block-bootstrap lower
bound of annual saving >0 at Bonferroni alpha .05/(firm N+3). 20,000 draws,
seed 20261018. Run same fixed schedule at 1x,2x,4x costs; count all three trials.
Otherwise FAIL. Data missing => INSUFFICIENT. Report yearly cuts, missed/chased
cost, count/weight fill rates, >3% missed rallies.
No eligibility or live changes. A PASS still needs Pionex forward validation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path

from . import cta
from ..paths import Paths
from ..research.luck import record_trial, trial_count

HOUR = 3_600_000
START = int(datetime(2023, 4, 1, tzinfo=timezone.utc).timestamp()*1000)
END = int(datetime(2026, 10, 12, tzinfo=timezone.utc).timestamp()*1000)


def fill(open_price, hours, tick, spread, notional):
    """Conservative six-hour resting bid proxy; hours keyed by offset 0..6."""
    if set(range(7)) - hours.keys():
        raise ValueError('missing execution hour')
    for row in hours.values():
        if not (0 < row['l'] <= min(row['o'], row['c']) <= max(row['o'], row['c']) <= row['h'] and row['v'] >= 0):
            raise ValueError('invalid OHLCV')
    if abs(hours[0]['o']/open_price-1) > 1e-8:
        raise ValueError('daily/hourly open mismatch')
    limit = float((Decimal(str(open_price)) * (1-Decimal(str(spread))/20000)
                   / Decimal(str(tick))).to_integral_value(rounding=ROUND_FLOOR)*Decimal(str(tick)))
    for h in range(1, 6):
        row = hours[h]
        if row['l'] <= limit-tick and row['c'] <= limit-tick and notional <= .01*row['v']*limit:
            return limit, True, h
    return hours[6]['o'], False, 6


def bootstrap(daily, n_trials, draws=20000):
    """Circular block bootstrap of annualised paired savings, including zero days."""
    rng = random.Random(20261018)
    n, block = len(daily), 30
    if n < block:
        raise ValueError('less than one bootstrap block')
    blocks = [sum(daily[(i+j) % n] for j in range(block)) for i in range(n)]
    full, rem = divmod(n, block)
    tails = [sum(daily[(i+j) % n] for j in range(rem)) for i in range(n)]
    samples = sorted((sum(blocks[rng.randrange(n)] for _ in range(full)) +
                      tails[rng.randrange(n)])*365.25/n for _ in range(draws))
    alpha = .05/max(1,n_trials)
    return {'lower': samples[max(0, math.floor(alpha*draws)-1)], 'alpha': alpha,
            'draws': draws, 'block_days': block, 'seed': 20261018}


def hourly(var, symbols):
    out = {s:{} for s in symbols}
    for path in [var/'proxy_market.db', var/'alpha/alts_1h.db']:
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True) as db:
            for s in symbols:
                for t,o,h,l,c,v in db.execute('SELECT open_time,open,high,low,close,volume FROM klines WHERE symbol=? AND interval=? AND complete=1 AND open_time>=? AND open_time<?', (s,'60M',START,END)):
                    row = dict(zip(('o','h','l','c','v'),map(float,(o,h,l,c,v))))
                    if t in out[s] and out[s][t] != row:
                        raise ValueError('conflicting hourly source')
                    out[s][t]=row
    return out


def run(var):
    var = Path(var)
    report = var/'reports/clo58-maker-entries-2026-10-18.json'
    marker = var/'reports/clo58-maker-entries-2026-10-18.started'
    # Atomic one-shot guard: interruption requires audit, never silently re-run.
    with marker.open('x') as f:
        f.write(datetime.now(timezone.utc).isoformat())
    symbols_path = var/'reports/clo58-symbols-2026-10-18.json'
    book_path = var/'reports/clo58-book-2026-10-18.json'
    symbols = json.loads(symbols_path.read_text())['data']['symbols']
    tick = {r['symbol']:10**-int(r['quotePrecision']) for r in symbols}
    books = json.loads(book_path.read_text())
    quotes = {r['symbol']:r for r in books['response']['data']['tickers']}
    spreads = {}
    for s in cta.UNIVERSE:
        q = quotes[s]
        bid,ask = float(q['bidPrice']),float(q['askPrice'])
        if not (0 < bid <= ask):raise ValueError('invalid spread')
        spreads[s] = (ask-bid)/((ask+bid)/2)*10000
    costs = {s:.0007+spreads[s]/20000 for s in cta.UNIVERSE}
    data = cta.load(Paths(var))
    orders = []
    base = cta.simulate(data,'tsmom_vote','vol',capital=1000,cost=costs,order_trace=orders)
    no_trace = cta.simulate(data,'tsmom_vote','vol',capital=1000,cost=costs)
    if base != no_trace:raise AssertionError('order trace changed baseline')
    hrs = hourly(var,cta.UNIVERSE)
    days = list(range(START,END,cta.DAY))
    n_before = trial_count(var/'trials.db')
    records, errors = [], []
    for order in orders:
        t=order['t']
        if not START <= t < END:continue
        for s,w in sorted(order['after'].items()):
            delta=w-order['before'].get(s,0)
            if delta<=1e-12:continue
            try:
                p=data[s][t]['o']
                rows={h:hrs[s][t+h*HOUR] for h in range(7) if t+h*HOUR in hrs[s]}
                price,filled,h=fill(p,rows,tick[s],spreads[s],delta*order['equity'])
                next_open=data[s][t+cta.DAY]['o']
                records.append({'t':t,'symbol':s,'weight':delta,'open':p,'price':price,
                                'maker':filled,'hour':h,'next_open':next_open})
            except (ValueError,KeyError) as exc:
                errors.append({'t':t,'symbol':s,'error':str(exc)})
    results = {}
    for mult in (1,2,4):
        daily={t:0.0 for t in days}
        other, chases = 0.0, 0.0
        yearly={}
        for r in records:
            s,p=r['symbol'],r['open']
            market=p*(1+mult*costs[s])
            alt=r['price']*(1+mult*(.0005 if r['maker'] else costs[s]))
            saving=r['weight']*(market-alt)/p
            daily[r['t']]+=saving
            if s not in ('BTC_USDT','ETH_USDT'):other+=saving
            if not r['maker']:chases+=saving
            year=str(datetime.fromtimestamp(r['t']/1000,timezone.utc).year)
            yearly[year]=yearly.get(year,0)+saving
        results[str(mult)]={'annual_saving':sum(daily.values())*365.25/len(days),
                            'non_btc_eth_saving_sum':other,'chase_saving_sum':chases,
                            'year_saving_sum':yearly}
        if mult==1:results['1']['bootstrap']=bootstrap(list(daily.values()),n_before+3)
    rate=sum(r['maker'] for r in records)/len(records) if records else 0
    checks={'annual_saving_ge_half_point':results['1']['annual_saving']>=.005,
            'fill_rate_ge_60pct':rate>=.6,
            'non_btc_eth_positive':results['1']['non_btc_eth_saving_sum']>0,
            '4x_positive':results['4']['annual_saving']>0,
            'corrected_bootstrap_positive':results['1']['bootstrap']['lower']>0}
    verdict='INSUFFICIENT' if errors or not records else ('PASS' if all(checks.values()) else 'FAIL')
    rep={'issue':'CLO-58','verdict':verdict,'checks':checks,'method':__doc__,
         'created_at':datetime.now(timezone.utc).isoformat(),'venue':'Binance PROXY, not Pionex execution',
         'start':'2023-04-01','end_inclusive':'2026-10-11','days':len(days),'orders':len(records),
         'fill_rate_count':rate,'fill_rate_weight':sum(r['weight'] for r in records if r['maker'])/sum(r['weight'] for r in records) if records else 0,
         'chased_orders':sum(not r['maker'] for r in records),
         'missed_rallies_gt3pct':sum(not r['maker'] and r['next_open']/r['open']>1.03 for r in records),
         'results':results,'errors':errors,'n_trials_before':n_before,'n_trials_for_correction':n_before+3,
         'spread_bps':spreads,'ticks':{s:tick[s] for s in cta.UNIVERSE},
         'baseline_trace_regression':'exact equality','fee_source':'https://www.pionex.com/en/fees',
         'input_hashes':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (symbols_path,book_path)},
         'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'execution_records':records}
    report.write_text(json.dumps(rep,indent=2))
    for mult in (1,2,4):
        record_trial(var/'trials.db','maker_entries',f'CLO-58:{mult}x','cta-maker-entry',
                     {'cost_mult':mult,'capital':1000},'2023-04-01..2026-10-11',verdict)
    print(json.dumps({k:v for k,v in rep.items() if k not in ('execution_records','method')},indent=2))
    return rep


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--var',type=Path,required=True)
    run(parser.parse_args().var)
