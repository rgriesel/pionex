"""CLO-100 feasibility only (2026-10-22 SAST): collect causal daily ETH base-fee series, count activation clusters.
No returns computed. Observation for day D = baseFeePerGas of last block with timestamp <= D 00:05 UTC minus 20 min
(>= 1.5 finality epochs post-Merge; ~100 confirmations pre-Merge), uniform across eras. Public archive headers via PublicNode."""
import json, sys, time, datetime as dt, urllib.request
from concurrent.futures import ThreadPoolExecutor
URL = "https://ethereum-rpc.publicnode.com"
err=None
def rpc(m, p):
    for i in range(6):
        try:
            r = urllib.request.Request(URL, json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p}).encode(), {"content-type":"application/json","user-agent":"curl/8"})
            return json.load(urllib.request.urlopen(r, timeout=30))["result"]
        except Exception as e: err=e; time.sleep(1+i)
    raise RuntimeError(repr(err))
def blk(n):
    b = rpc("eth_getBlockByNumber", [hex(n), False]); return int(b["timestamp"],16), b.get("baseFeePerGas")
def at(ts, guess):
    n = guess
    for _ in range(40):
        t,_f = blk(n)
        d = (ts - t)
        if 0 <= d < 12 or (0 <= d < 30 and False): break
        n += int(d/12.5) if abs(d)>=12 else (1 if d>0 else -1)
        if d<0 and abs(d)<12: n -= 1
    # ensure last block with timestamp<=ts
    while blk(n+1)[0] <= ts: n += 1
    while blk(n)[0] > ts: n -= 1
    return n
def main():
    start = dt.datetime(2022,10,1,tzinfo=dt.timezone.utc); end = dt.datetime(2026,10,22,tzinfo=dt.timezone.utc)
    ref_t, ref_n = blk(17000000)[0], 17000000
    days=[]; d=start
    while d<end: days.append(d); d+=dt.timedelta(days=1)
    def one(d):
        ts = int(d.timestamp())+300-1200
        g = ref_n + int((ts-ref_t)/12.1)
        n = at(ts, g); t,f = blk(n)
        return d.date().isoformat(), n, t, int(f,16) if f else None
    with ThreadPoolExecutor(4) as ex: rows = list(ex.map(one, days))
    json.dump(rows, open("var/reports/eth_basefee_daily_clo100.json","w"))
    print(len(rows))

def activations(f):
    """Card rule: B>=3*median(prev 30) on two consecutive days -> activate; 7-day hold; rearm after 2 days <=1.5*M."""
    import statistics as st
    act = []; armed = True; ok = 0; until = None
    for i in range(31, len(f)):
        M = st.median(f[i-30:i]); M1 = st.median(f[i-31:i-1])
        if until is not None and i >= until: until = None
        if until is not None: continue
        if armed:
            if f[i] >= 3*M and f[i-1] >= 3*M1: act.append(i); until = i+7; armed = False; ok = 0
        else:
            ok = ok+1 if f[i] <= 1.5*M else 0
            if ok >= 2: armed = True
    return act

if __name__ == "__main__":
    main()
