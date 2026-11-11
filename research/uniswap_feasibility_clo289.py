"""Read-only CLO-289 data feasibility; no strategy, signal, returns or trial registration."""
import concurrent.futures as cf
import datetime as dt
import json
from pathlib import Path
import time
import urllib.request
import urllib.error

POOL = '0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640'
FACTORY = '0x1f98431c8ad98523631ae4a59f267346ea31f984'
USDC = '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48'
WETH = '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2'
MINT = '0x7a53080ba414158be7ec69b987b5fb7d07dee101fe85488f0853ae16239d0bde'
BURN = '0x0c396cd989a39f4459b5fa1aed6a9a8dcdbc45908acfd67e028cd568da98982c'

def word(n):
    return format(n % (1 << 256), '064x')

def signed(n, bits=256):
    n &= (1 << bits) - 1
    return n - (1 << bits) if n >= (1 << (bits-1)) else n

def words(data):
    if not isinstance(data, str) or not data.startswith('0x') or (len(data)-2)%64:
        raise ValueError('malformed ABI result')
    return [int(data[i:i+64],16) for i in range(2,len(data),64)]

def apply_event(book, event):
    """Apply only positive Mint/Burn liquidity; fee-only Burns do nothing."""
    topic=event['topics'][0].lower()
    if topic not in (MINT,BURN):
        return
    lo,hi=[signed(int(v,16),24) for v in event['topics'][2:4]]
    amount=words(event['data'])[1 if topic == MINT else 0]
    delta=amount if topic == MINT else -amount
    for tick,net in ((lo,delta),(hi,-delta)):
        gross,oldnet=book.get(tick,(0,0))
        gross += delta
        if gross < 0:
            raise ValueError('negative liquidityGross')
        if gross:
            book[tick]=(gross,oldnet+net)
        else:
            if oldnet+net:
                raise ValueError('nonzero net at deleted tick')
            book.pop(tick,None)

class RPC:
    def __init__(self, url, out):
        self.url,self.out=url,out
    def request(self,method,params):
        started=time.monotonic()
        row={'method':method,'params':params,'requested_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
        try:
            req=urllib.request.Request(self.url,json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params}).encode(),{'Content-Type':'application/json','User-Agent':'Mozilla/5.0'})
            with urllib.request.urlopen(req,timeout=15) as response:
                body=json.load(response)
            row['response']=body
            if 'error' in body or 'result' not in body:
                raise ValueError(str(body))
            return body['result']
        except urllib.error.HTTPError as exc:
            row['error']={'http_status':exc.code,'body':exc.read().decode()[:2000]}
            raise
        except Exception as exc:
            row.setdefault('error',str(exc))
            raise
        finally:
            row['seconds']=time.monotonic()-started
            row['received_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
            self.out.append(row)
    def call(self, data, block, address=POOL):
        return self.request('eth_call',[{'to':address,'data':data},hex(block)])
    def header(self, block):
        return self.request('eth_getBlockByNumber',[hex(block) if isinstance(block,int) else block,False])

def snapshot(rpc,block):
    """Exhaust the entire legal bitmap, then read every initialized tick."""
    t=time.monotonic()
    slot=words(rpc.call('0x3850c7bd',block))
    spacing=words(rpc.call('0xd0c93a7c',block))[0]
    if spacing != 10:
        raise ValueError('unexpected spacing')
    positions=range((-887272//spacing)>>8, (887272//spacing>>8)+1)
    def bitmap(pos):
        return pos,words(rpc.call('0x5339c296'+word(pos),block))[0]
    ticks=[]
    with cf.ThreadPoolExecutor(max_workers=8) as executor:
        for pos,bits in executor.map(bitmap,positions):
            ticks.extend((pos*256+bit)*spacing for bit in range(256) if bits>>bit&1)
    def tick_read(tick):
        w=words(rpc.call('0xf30dba93'+word(tick),block))
        if not w[0] or not w[7]:
            raise ValueError('bitmap/tick inconsistency')
        return tick,(w[0],signed(w[1]))
    with cf.ThreadPoolExecutor(max_workers=8) as executor:
        book=dict(executor.map(tick_read,ticks))
    liquidity=words(rpc.call('0x1a686502',block))[0]
    current_tick=signed(slot[1],24)
    active=sum(n for tick,(g,n) in book.items() if tick<=current_tick)
    if sum(n for g,n in book.values()) != 0 or active != liquidity:
        raise ValueError('state reconciliation failed')
    return {'block':block,'slot0':slot,'tick':current_tick,'liquidity':liquidity,'active_from_ticks':active,'bitmap_words':len(positions),'book':book,'seconds':time.monotonic()-t}

def run(output):
    """Operational plan written 2026-11-11 03:49:38 SAST BEFORE reconstruction.
    Timestamp corrected after run: original 03:55 was a transcription error;
    the executed original docstring is retained verbatim in the raw report.

    One fixed feasibility pilot, NOT a registered strategy test. Ethereum chain 1;
    factory WETH/USDC fee500 only. Historical E=20,007,200; S=max block timestamp
    <=E.timestamp-86400. Eight workers, 100-block contiguous log pages. Enumerate
    every legal bitmap word and initialized tick independently at S and E.
    Sort Mint/Burn by block/transaction/log index; reject removed/duplicates and
    hash conflicts; replay gross/net liquidity and require exact equality to E.
    Reconcile net cumulative liquidity at slot0.tick to pool liquidity at S/E.
    Check block hashes again after reads, metadata and historical archive samples.
    Record raw reads/receipt clocks. YES needs complete pool-state equivalent
    interval books, daily ordered event reconciliation, archive samples and
    observed pilot duration <=600s. Actual midnight availability and sustained
    quotas remain unproven; owner/range pairing is not identifiable from ticks.
    No capacity integral, activation count, price return or trading trial.
    """
    rows=[];rpc=RPC('https://eth.drpc.org',rows)
    report={'scope':'DATA FEASIBILITY ONLY; Ethereum non-Pionex venue; no returns or trial','started_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'url':rpc.url,'criteria':run.__doc__}
    start=time.monotonic()
    try:
        assert int(rpc.request('eth_chainId',[]),16)==1
        E=20007200
        getpool='0x1698ee82'+WETH[2:].zfill(64)+USDC[2:].zfill(64)+word(500)
        assert '0x'+rpc.call(getpool,E,FACTORY)[-40:]==POOL
        metadata={}
        for key,selector in [('token0','0x0dfe1681'),('token1','0xd21220a7'),('fee','0xddca3f43')]:
            metadata[key]=rpc.call(selector,E)
        assert '0x'+metadata['token0'][-40:]==USDC
        assert '0x'+metadata['token1'][-40:]==WETH
        assert words(metadata['fee'])==[500]
        assert words(rpc.call('0x313ce567',E,USDC))==[6]
        assert words(rpc.call('0x313ce567',E,WETH))==[18]
        report['metadata']=metadata
        eh=rpc.header(E);cutoff=int(eh['timestamp'],16)-86400
        low,high=E-9000,E
        assert int(rpc.header(low)['timestamp'],16)<=cutoff
        while low+1<high:
            middle=(low+high)//2
            if int(rpc.header(middle)['timestamp'],16)<=cutoff: low=middle
            else: high=middle
        S=low;sh=rpc.header(S)
        report['headers']={'S':sh,'E':eh,'S_next':rpc.header(S+1)}
        report['snapshots']={}
        for name,block in [('S',S),('E',E)]:
            snap=snapshot(rpc,block);report['snapshots'][name]=snap
            print(name,'ticks',len(snap['book']),'seconds',round(snap['seconds'],2),flush=True)
        def logs(a):
            return rpc.request('eth_getLogs',[{'address':POOL,'fromBlock':hex(a),'toBlock':hex(min(a+99,E)),'topics':[[MINT,BURN]]}])
        with cf.ThreadPoolExecutor(max_workers=8) as executor:
            events=[event for page in executor.map(logs,range(S+1,E+1,100)) for event in page]
        events.sort(key=lambda e:tuple(int(e[k],16) for k in ('blockNumber','transactionIndex','logIndex')))
        identities=set();hashes={}
        for event in events:
            identity=(event['blockHash'],event['logIndex'])
            assert identity not in identities and not event.get('removed',False)
            assert event['address'].lower()==POOL and S<int(event['blockNumber'],16)<=E
            identities.add(identity)
            bn=int(event['blockNumber'],16)
            assert hashes.setdefault(bn,event['blockHash'])==event['blockHash']
        with cf.ThreadPoolExecutor(max_workers=8) as executor:
            for bn,header in zip(hashes,executor.map(rpc.header,hashes)):
                assert header['hash']==hashes[bn]
        replay=dict(report['snapshots']['S']['book'])
        for event in events: apply_event(replay,event)
        assert replay==report['snapshots']['E']['book']
        assert rpc.header(S)['hash']==sh['hash'] and rpc.header(E)['hash']==eh['hash']
        report['events']=events
        report['exact_replay_match']=True
        report['pilot_seconds']=time.monotonic()-start
        report['pilot_operational_gate']=report['pilot_seconds']<=600
        report['archive_samples']={}
        for block in [13000000,17000000,24000000]:
            try:report['archive_samples'][str(block)]={'slot0':rpc.call('0x3850c7bd',block),'header':rpc.header(block)}
            except Exception as exc:report['archive_samples'][str(block)]={'error':str(exc)}
        report['verdict']='YES_PILOT' if report['pilot_operational_gate'] and all('error' not in v for v in report['archive_samples'].values()) else 'NO_NOT_DEMONSTRATED'
    except Exception as exc:
        report['verdict']='NO_NOT_DEMONSTRATED';report['failure']=str(exc)
    finally:
        report['seconds']=time.monotonic()-start
        report['request_count']=len(rows)
        report['finished_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
        Path(output).write_text(json.dumps(report,indent=2))
        Path(str(output)+'.rpc.json').write_text(json.dumps(rows,indent=2))
        print(json.dumps({k:v for k,v in report.items() if k not in ('snapshots','headers','events','metadata','criteria','archive_samples')},indent=2),flush=True)

if __name__=='__main__':
    import sys
    run(sys.argv[1])
