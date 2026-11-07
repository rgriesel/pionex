"""CLO-237 research only: owner-inspired short-hold long grid, no order path."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import random
import statistics
from pathlib import Path

from ..exchange.pionex_public import PionexPublic
from ..swing import grid, zoo, cta
from . import luck, metrics

HOUR, DAY = 3_600_000, 86_400_000
CONFIGS = {'base': (40, .02, 8), 'lev30': (30, .02, 8),
           'tp4pct': (40, .04, 8), 'hold12': (40, .02, 12)}


def collect(destination):
    """Unsigned public PERP archive, independent of strategy evaluation."""
    client = PionexPublic()
    rules = client.get('/api/v1/common/symbols', {'type': 'PERP', 'symbols': 'BTC_USDT_PERP'})
    book = client.get('/api/v1/market/bookTickers', {'symbol': 'BTC_USDT_PERP'})
    end, seen, receipts = 1794038400000, {}, []  # fixed 2026-11-07 08:00 UTC
    for _ in range(20):
        env = client.get('/api/v1/market/klines', {'symbol': 'BTC_USDT_PERP', 'interval': '60M',
                                                 'limit': 500, 'endTime': end})
        rows = env.data['klines']
        receipts.append({'server_ms': env.server_ts, 'received_ms': env.recv_ms, 'rows': len(rows)})
        for b in rows:
            t = int(b['time'])
            if t + HOUR <= env.server_ts:
                seen[t] = [t] + [float(b[k]) for k in ('open', 'high', 'low', 'close', 'volume')]
        if not rows:
            break
        end = min(int(b['time']) for b in rows) - 1
    payload = {'venue': 'Pionex BTC_USDT_PERP public 60M trade candles; NOT mark-price history',
               'bars': sorted(seen.values()), 'rules': rules.data, 'rules_at': rules.server_ts,
               'book': book.data, 'book_at': book.server_ts, 'receipts': receipts}
    Path(destination).write_text(json.dumps(payload, indent=1), encoding='utf-8')
    return {'bars': len(seen), 'span': [min(seen), max(seen)]}


class Ledger:
    """Isolated linear inventory ledger; negative cash represents financed notional.

    Reuses grid.levels; liquidation is recalculated on current equity/inventory.
    This is a conservative research model, not an exchange matching engine.
    """
    def __init__(self, price, margin, leverage, rules, cost=1):
        self.margin, self.rows = margin, 60
        lv = grid.levels(price*(1-1/15), price*(1+1/15), self.rows, 'arithmetic')
        tick = float(rules['quoteStep'])
        self.levels = [math.floor(p/tick)*tick for p in lv]
        self.held = [self.levels[i] >= price for i in range(self.rows)]
        self.initial = list(self.held)
        step = float(rules['baseStep'])
        self.q = math.floor(margin*leverage/sum(self.levels[:-1])/step)*step
        self.valid = self.q >= float(rules['minSizeLimit']) and self.q*self.levels[0] >= max(10, float(rules['minNotional']))
        self.qty, self.cash = 0., margin
        self.fees = self.slippage = self.funding = self.turnover = self.grid_gross = 0.
        self.fills = self.trips = 0
        self.fee, self.slip, self.market_slip = .0005*cost, .0002*cost, .0005*cost
        self.half_spread = float(rules['_half_spread'])*cost
        self.mmr, self.liq_fee, self.cost = .005, float(rules['liquidationFeeRate']), cost
        self.closed, self.reason, self.trough, self.peak = False, None, margin, margin
        if self.valid:
            self.fill(sum(self.held)*self.q, price, True)

    def fill(self, quantity, price, market=False):
        slip = abs(quantity)*price*((self.market_slip if market else self.slip)+self.half_spread)
        fee = abs(quantity)*price*self.fee
        self.cash -= quantity*price+slip+fee
        self.qty += quantity
        if abs(self.qty)<1e-10:
            self.qty = 0.
        self.slippage += slip
        self.fees += fee
        self.turnover += abs(quantity)*price
        self.fills += 1

    def equity(self, price):
        return self.cash+self.qty*price

    def flatten_equity(self, price):
        return self.equity(price)-self.qty*price*(self.fee+self.market_slip+self.half_spread)

    def mark(self, price):
        self.trough = min(self.trough,self.flatten_equity(price))
        self.peak = max(self.peak,self.equity(price))
        mark = price*.999  # adverse mark/trade basis assumption
        if self.qty and self.equity(mark) <= self.qty*mark*(self.mmr+self.liq_fee):
            self.cash, self.qty, self.closed, self.reason, self.trough = 0., 0., True, 'liquidation', 0.

    def close(self, price, reason):
        if not self.closed:
            self.fill(-self.qty,price,True)
            self.cash = max(0.,self.cash)
            self.closed, self.reason = True, reason
            self.trough = min(self.trough,self.cash)

    def move(self, start, end):
        events=[]
        for i,held in enumerate(self.held):
            p=self.levels[i+1] if held else self.levels[i]
            if held and start<p<=end:
                events.append((p,i,-1))
            elif not held and end<=p<start:
                events.append((p,i,1))
        for price,i,sign in sorted(events,reverse=end<start):
            self.mark(price)
            if self.closed:
                return
            self.fill(sign*self.q,price)
            self.held[i]=sign==1
            if sign==-1:
                if not self.initial[i]:
                    self.trips+=1
                    self.grid_gross+=self.q*(self.levels[i+1]-self.levels[i])
                self.initial[i]=False
            self.mark(price)
            if self.closed:
                return
        self.mark(end)

    def candle(self, bar, plain=False):
        _,o,h,l,c,*_=bar
        self.trough, self.peak = self.flatten_equity(o), self.equity(o)
        self.mark(o)  # gaps mark BEFORE any fills or pending exits
        if self.closed:
            return
        paths=[]
        for middle in ((l,h),(h,l)):
            candidate=copy.deepcopy(self)
            a=o
            for b in (*middle,c):
                candidate.mark(b) if plain else candidate.move(a,b)
                if candidate.closed:
                    break
                a=b
            paths.append(candidate)
        worst=min(paths,key=lambda s:(s.trough,s.equity(c)))
        self.__dict__.update(worst.__dict__)
        if not self.closed:
            fund=self.qty*c*.0003/24*self.cost
            self.cash-=fund
            self.funding+=fund
            self.mark(c)


def signals(bars):
    """Causal trend proxy; no fabricated analyst or discretionary target input."""
    cl=[b[4] for b in bars]
    ema=zoo.ema(cl,50)
    return [i>=168 and cl[i]>cl[i-168] and cl[i]>ema[i] for i in range(len(bars))]


def run_path(bars,rules,config,cost=1,entry_signals=None,plain=False):
    """PRE-REGISTERED 2026-11-07 11:46 SAST, before any historical evaluation.

    CLO-237: one frozen owner-inspired long-only research test, never an exact
    discretionary replay. Existing CLO-46/CLO-63 are different rules. Owner
    calibration: saved 58-bot audit; ~+/-6.67% arithmetic band, 60 rows, 40x,
    median hold ~9h, frequent early cash-out. No parameter selection permitted.
    Every 8h UTC: prior CLOSED hourly close > EMA50 and > close 168h earlier;
    enter next open, one isolated bot, margin min($50, half available equity),
    total starting capital $100, zero topups, cash reserve cannot fund bot losses.
    Grid levels +/-1/15, 60 rows; quantities rounded down to public contract step;
    each row >=max($10, public min notional), minimum size enforced. No entry
    below $2 capital. Initial upper rows held; financed linear inventory ledger.
    Closed-bar exits execute next open: net flatten profit >=max($1,2% margin)
    (capped $50), net loss >=25% margin, profitable six-bar stall, or 8h hold.
    Range break closes next open. Gaps marked before exits. Liquidation checked
    on inventory at every path node using adverse mark basis -10bp, assumed
    maintenance 0.5% plus public liquidation fee; full isolated margin lost.
    Both OHLC paths simulated, worse equity trough retained; no queue guarantee.
    Fees 5bp/side, limit slip 2bp, market slip 5bp, half current observed spread
    on every fill; funding debit 3bp notional/day. All costs stressed 2x/4x.
    These are conservative assumptions, not verified historical mark/funding.
    Neighbours fixed: leverage30, take-profit4%, hold12h, counted as 4 trials.
    Controls: same-entry initial-inventory hold; unfiltered grid; 99 circular
    signal shifts, descriptive random-entry replay only, no qualification claim.
    Data: public Pionex PERP 60M, end 2026-11-07 08:00 UTC, max 10,000 bars;
    no proxy substitution. Last third chronological holdout, first 168h warmup;
    evaluation is retrospective and not globally untouched. No re-fitting.
    PASS requires existing luck-1 T1..T9 thresholds with registry including
    4 configurations, >=100 trades, mean rolling30 return >=100%, intrabar
    DD <=35%, zero liquidation, bootstrap trade LB(alpha=.05/4)>0,
    final-third net profit>0, and outperform same-entry initial hold.
    T1 >=750 days; DSR, CSCV16, circular timing null10000, neighbours,
    bootstrap20day/2000, all four regimes >=30days, cost stress and MC10000
    exactly use research/luck.py. Hourly causal entry-notional timing diagnostic
    is reported separately; it cannot certify the nonlinear grid timing gate.
    Missing historical marks, exact bot mechanics, untouched OOS or forward
    Pionex fills means no live qualification regardless of numeric results.
    FAIL/INSUFFICIENT requires WHY/WHAT/NEXT; next variant is a NEW test.
    """
    leverage,take,hold=config
    signal=signals(bars) if entry_signals is None else entry_signals
    capital,state,pending,entered,trades=100.,None,None,None,[]
    daily, weights,underlying={},{},{}
    hourly_weights, hourly_returns = [], []
    peak,dd,last_equity,rejected=100.,0.,100.,0

    def book_trade(t):
        trades.append({'entry_time':entered,'exit_time':t,'net_usdt':state.cash-state.margin,
                       'net_bps':(state.cash-state.margin)/state.margin*1e4,'margin':state.margin,
                       'exit_reason':state.reason, 'fees':state.fees,'slippage':state.slippage,
                       'funding':state.funding,'turnover':state.turnover,'grid_gross':state.grid_gross,
                       'trips':state.trips,'fills':state.fills})

    for i in range(169,len(bars)):
        t,o,h,l,c,*_=bars[i]
        if bars[i-168][0]!=t-168*HOUR:
            raise ValueError('gapped data')
        day=t//DAY*DAY
        if day not in daily:
            daily[day]=[last_equity,last_equity]
            weights[day]=state.qty*o/last_equity if state else 0.
            underlying[day]=[o,c]
        underlying[day][1]=c
        if state and pending:
            state.mark(o)
            state.close(o,pending)
        if state and state.closed:
            capital+=state.cash
            book_trade(t)
            state,pending=None,None
        if state is None and t%(8*HOUR)==0 and signal[i-1] and capital>=2:
            candidate=Ledger(o,min(50.,capital/2),leverage,rules,cost)
            if candidate.valid:
                state,entered=candidate,t
                capital-=state.margin
            else:
                rejected+=1
        hourly_weights.append(state.qty*o/last_equity if state else 0.)
        hourly_returns.append(c/o-1)
        if state:
            state.candle(bars[i],plain)
            peak=max(peak,capital+state.peak)
            dd=max(dd,1-(capital+max(0,state.trough))/peak)
            equity=capital+max(0,state.equity(c))
            if not state.closed:
                net=state.flatten_equity(c)-state.margin
                held=(t+HOUR-entered)/HOUR
                if c<state.levels[0] or c>state.levels[-1]:
                    pending='range_break'
                elif net<=-.25*state.margin:
                    pending='loss25pct'
                elif net>=max(1.,min(50.,take*state.margin)):
                    pending='bank_profit'
                elif net>0 and i>=6 and max(b[2] for b in bars[i-5:i+1])<=bars[i-6][2]:
                    pending='stall6'
                elif held>=hold:
                    pending='time'
        else:
            equity=capital
        if i==len(bars)-1 and state:
            state.close(c,'dataset_end')
            capital+=state.cash
            book_trade(t+HOUR)
            equity=capital
        peak=max(peak,equity)
        dd=max(dd,1-equity/peak)
        daily[day][1]=equity
        last_equity=equity
    days=sorted(daily)
    returns=[daily[d][1]/daily[d][0]-1 for d in days]
    stats=cta.stats([(d,r,weights[d]) for d,r in zip(days,returns)])
    stats['avg_exposure']=statistics.mean(hourly_weights)
    stats.pop('turnover_per_year',None)
    stats['turnover_per_year_initial_capital']=sum(t['turnover'] for t in trades)/100*365.25/len(days)
    roll=[math.prod(1+r for r in returns[i:i+30])-1 for i in range(len(returns)-29)]
    return {'stats':stats,'max_intrabar_drawdown':dd,'final_usdt':last_equity,
            'hourly_weights':hourly_weights,'hourly_returns':hourly_returns,
            'days':days,'returns':returns,'weights':[weights[d] for d in days],
            'underlying':[underlying[d][1]/underlying[d][0]-1 for d in days],
            'trades':trades,'rejected_entries':rejected,
            'rolling30_mean':statistics.mean(roll) if roll else None,
            'rolling30_hit_target':sum(x>=1 for x in roll)/len(roll) if roll else None,
            'rolling30_worst':min(roll) if roll else None}


def evaluate_once(input_path, registry, output):
    """Run frozen CLO-237 protocol once; refuse an existing result or reserved trial."""
    import sqlite3
    if Path(output).exists():
        raise RuntimeError('CLO-237 already evaluated; read the existing report')
    if Path(registry).exists():
        with sqlite3.connect(f'file:{Path(registry).as_posix()}?mode=ro', uri=True) as db:
            if db.execute("SELECT 1 FROM trials WHERE source='clo237' LIMIT 1").fetchone():
                raise RuntimeError('CLO-237 trials already reserved; recover, never rerun')
    raw = Path(input_path).read_bytes()
    source = json.loads(raw)
    bars = source['bars']
    if any(b[0]-a[0] != HOUR for a,b in zip(bars,bars[1:])):
        raise ValueError('non-contiguous candles')
    if any(not (0 < b[3] <= min(b[1],b[4]) <= max(b[1],b[4]) <= b[2]) for b in bars):
        raise ValueError('invalid OHLC')
    rules = dict(source['rules']['symbols'][0])
    tick = source['book']['tickers'][0]
    bid,ask = float(tick['bidPrice']),float(tick['askPrice'])
    if not 0 < bid <= ask:
        raise ValueError('invalid quote')
    rules['_half_spread'] = (ask-bid)/(ask+bid)
    for name,cfg in CONFIGS.items():
        luck.record_trial(registry,'clo237',name,'owner_grid_clo237',cfg,
                          str([bars[0][0],bars[-1][0]]),'RESERVED before evaluation')
    count = luck.trial_count(registry)
    th = luck.thresholds(count)
    runs = {name:run_path(bars,rules,cfg) for name,cfg in CONFIGS.items()}
    base = runs['base']
    controls = {'initial_inventory_hold':run_path(bars,rules,CONFIGS['base'],plain=True),
                'unfiltered_grid':run_path(bars,rules,CONFIGS['base'],entry_signals=[True]*len(bars))}
    dsr = luck.deflated_sharpe(base['returns'],count,
                              statistics.pvariance(luck.sharpe_period(r['returns']) for r in runs.values()))
    pbo = luck.pbo_cscv({k:v['returns'] for k,v in runs.items()})
    timing = luck.timing_null([base['hourly_weights']],[base['hourly_returns']],min_shift=30*24)
    timing.update({'pass':False,'status':'NOT_EVALUABLE for nonlinear grid qualification',
                   'note':'Causal hourly notional x open-close return diagnostic; does not preserve nonlinear grid P&L'})
    neighbours = {k:{**v['stats'],'pass':v['stats']['cagr']>0 and
                    (v['stats']['sharpe'] or 0)>=.6*(base['stats']['sharpe'] or 0)}
                  for k,v in runs.items() if k!='base'}
    boot = luck.block_bootstrap(base['returns'])
    labels = luck.regime_labels({b[0]//DAY*DAY:b[4] for b in bars})
    regimes = {}
    for name,floor in luck.REGIME_FLOOR_BPS.items():
        xs = [r for d,r in zip(base['days'],base['returns']) if labels.get(d)==name]
        mean = statistics.mean(xs)*1e4 if xs else None
        regimes[name] = {'days':len(xs),'mean_bps':mean,
                         'pass':len(xs)>=30 and mean>=floor}
    costs = {str(k):run_path(bars,rules,CONFIGS['base'],cost=k) for k in (2,4)}
    mc = luck.monte_carlo(base['returns'])
    mc['pass'] = mc['p_lose_50pct']<=.01 and mc['return_30d']['p05']>=-.30
    tests = {'T1_history':{'pass':len(base['returns'])>=750,'days':len(base['returns'])},
             'T2_DSR':{**dsr,'pass':dsr['prob']>=th['dsr_prob_min']},
             'T3_PBO':{**pbo,'pass':pbo['pbo']<=th['pbo_max']},
             'T4_timing':timing,
             'T5_sensitivity':{'pass':all(v['pass'] for v in neighbours.values()),'neighbours':neighbours},
             'T6_bootstrap':{**boot,'pass':boot['mean_lower_bps']>0},
             'T7_regimes':{'pass':all(v['pass'] for v in regimes.values()),'regimes':regimes},
             'T8_cost_stress':{'pass':all(v['stats']['cagr']>0 and (v['stats']['sharpe'] or 0)>=luck.COST_BOUNDS[int(k)]
                                        for k,v in costs.items()),'stats':{k:v['stats'] for k,v in costs.items()}},
             'T9_MC':mc}
    signal = signals(bars)
    random_runs = []
    rng = random.Random(237)
    for _ in range(99):
        shift = rng.randrange(30*24,len(signal)-30*24)
        r = run_path(bars,rules,CONFIGS['base'],entry_signals=signal[shift:]+signal[:shift])
        random_runs.append(r['final_usdt'])
    holdout_start = bars[len(bars)*2//3][0]
    holdout_bars = [b for b in bars if b[0]>=holdout_start-169*HOUR]
    holdout = run_path(holdout_bars,rules,CONFIGS['base'])
    trade_lb = metrics.block_bootstrap_lower(base['trades'],.05/4)
    gates = {'sample100':len(base['trades'])>=100,'target100per30':base['rolling30_mean'] is not None and base['rolling30_mean']>=1,
             'drawdown35':base['max_intrabar_drawdown']<=.35,
             'zero_liquidations':all(t['exit_reason']!='liquidation' for t in base['trades']),
             'trade_bootstrap':trade_lb is not None and trade_lb>0,
             'last_third_positive':holdout['final_usdt']>100,
             'beats_hold':base['final_usdt']>controls['initial_inventory_hold']['final_usdt']}
    eligible = all(gates.values()) and all(t['pass'] for t in tests.values())
    failed = [k for k,v in gates.items() if not v]+[k for k,v in tests.items() if not v['pass']]
    rep = {'issue':'CLO-237','verdict':'PASS' if eligible else 'FAIL', 'live_eligible':False,
           'preregistration':run_path.__doc__,'input_sha256':hashlib.sha256(raw).hexdigest(),
           'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           'venue':source['venue'],'span':[bars[0][0],bars[-1][0]],'rules':rules,
           'registry_count':count,'thresholds':th,'gates':gates,'luck_tests':tests,
           'trade_summary':metrics.summarize(base['trades']),'trade_bootstrap_lower_bps':trade_lb,
           'runs':runs,'costs':costs,'controls':controls,'last_third':holdout,
           'random_entry':{'n':99,'final_usdt':random_runs,'p_descriptive':(1+sum(v>=base['final_usdt'] for v in random_runs))/100,
                           'qualification':False},
           'failed':failed,'WHY':'Failed frozen gates: '+', '.join(failed),
           'WHAT':'A causal direction/exit edge must overcome turnover, adverse inventory and liquidation while meeting unchanged gates.',
           'NEXT':'NEW test CLO-237-v2: same band60 and entry clock; direction sign of prior 168h return, 5x, margin min(25,cash/4), TP $1, stop25%, hold8h; full firm gates, not run here.',
           'limitations':['Historical mark prices/funding and exact bot queue mechanics missing; adverse basis/MMR are assumptions.',
                          'Retrospective evaluation, no globally untouched OOS or forward fill ledger.',
                          'Public hourly history is shorter than the unchanged 750-day requirement.',
                          'MC uses daily close returns; intraday ruin is separately reported by intrabar drawdown.',
                          'Bot product minimum investment not certified by public symbol minimum.',
                          'No proof of future profit; report is deliberately not registered with the live gate.']}
    Path(output).write_text(json.dumps(rep,indent=1,allow_nan=False),encoding='utf-8')
    return {k:rep[k] for k in ('verdict','failed','trade_summary','WHY','WHAT','NEXT')}


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--inputs',required=True)
    parser.add_argument('--registry',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    print(json.dumps(evaluate_once(args.inputs,args.registry,args.output),indent=1))
