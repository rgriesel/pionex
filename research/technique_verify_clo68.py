"""CLO-68 technique verifier (PROXY BTC_USDT 60M, var/proxy_market.db). Research only; no order path.

PRE-REGISTERED 2026-10-18 10:15 SAST, before the first run. Run ONCE: py research/technique_verify_clo68.py
Existing var/reports/technique_verify_clo68.json forbids a re-run. A changed definition is a new test.

Data: BTC_USDT 60M closed bars (PROXY archive), ATR14 on the same bars. All levels point-in-time (bars <= t).
Sample points: every 6th bar after a 400-bar warm-up, up to n-80.
Techniques (fixed settings, no grid):
  SWING_SR   nearest unbroken fractal swing low (support) / high (resistance), k=12 bars each side, confirmed k bars later
  AVWAP_LOW  AVWAP (typical price x volume) anchored at the last confirmed swing low (k=24); AVWAP_HIGH likewise at the swing high
  VP_POC/VP_VAL/VP_VAH  trailing 168-bar volume profile, bins 0.25% of price, POC and 70% value-area edges
  OB         order block: impulse = close[i+3]-close[i] >= 2 ATR (up) or <= -2 ATR (down) with max volume of bars i+1..i+3
             >= 1.5 x median volume of prior 20 bars; zone = candle i if it is the opposite colour (down candle before up
             impulse); level = zone top (bullish, support) / zone bottom (bearish, resistance); confirmed at i+3; dead when
             a close crosses the far side of the zone; only the latest 500 bars.
  NOT TESTED (INSUFFICIENT, stated up front): liquidation heatmap (no historical liquidation data), Elliott count / WL
  oscillator (hindsight-prone counts; needs its own pre-registration).
Event: at a sample bar t each technique gives its nearest support below and nearest resistance above close, kept only if
  0.5 <= distance/ATR <= 4. Level frozen at t. Touch = first bar j in t+1..t+48 whose low (support) / high (resistance) reaches
  it. Entry at the level; then 24 bars (including bar j): loss R=-1 if price goes 1 ATR through the level (also if both
  barriers hit in one bar), win R=+1 if price goes 1 ATR away in favour, else R=(close_end-L)/ATR (timeout). win flag = R>0.
  Cost 14 bps round trip of price (0.05% x2 fee + 2 bps slippage) converted to R; also 2x.
Placebo (random levels at the same distance): each event gets 30 placebos: same signed offset (L-close)/ATR applied to a random
  sample bar of the same half of history. Lift = real win rate (given touch) - pooled placebo win rate.
Statistics: 1,000-resample week-cluster bootstrap, one-sided 0.5% bound (Bonferroni 0.05 / 10 technique-sides).
Verdicts per technique-side:
  INFORMATIVE  lift bound > 0, lift > 0 in both halves of history and in both regimes (close above/below 30-day SMA),
               and n_touch >= 200.
  TRADEABLE    INFORMATIVE and net expectancy (R after 1x cost) bound > 0 and mean net R > 0 at 2x cost and in both halves.
  else FAIL (INSUFFICIENT if n_touch < 200).
Claims: the analysts' zones (var/guidance/btc_calls.jsonl) -> research/owner_method/claims_zones_clo68.jsonl (amended before the first run, 10:40 SAST: the Scout's claims.jsonl must not be overwritten; only 8 calls exist; far below 100).
  For each claim: do our computed levels (any technique, unbroken, at publication bar) fall inside the zone widened by 0.5 ATR;
  did price touch the zone edge within 48 h and win (same R rule). Descriptive only; ranking uses the technique test.
"""
from __future__ import annotations
import json, random, sqlite3, statistics, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "var" / "reports" / "technique_verify_clo68.json"
HT, HA, STEP, WARM, NPL = 48, 24, 6, 400, 30
COST = 0.0014
random.seed(68)


def load(sym="BTC_USDT"):
    c = sqlite3.connect(ROOT / "var" / "proxy_market.db")
    rows = c.execute("select open_time,open,high,low,close,volume from klines where symbol=? and interval='60M' "
                     "and complete=1 order by open_time", (sym,)).fetchall()
    return [tuple(float(x) if i else int(x) for i, x in enumerate(r)) for r in rows]


def prep(rows):
    t = [r[0] for r in rows]; o = [r[1] for r in rows]; h = [r[2] for r in rows]; l = [r[3] for r in rows]
    c = [r[4] for r in rows]; v = [r[5] for r in rows]
    tr = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    atr = [0.0] * len(c); s = 0.0
    for i in range(len(c)):
        s += tr[i]
        if i >= 14:
            s -= tr[i - 14]
        atr[i] = s / min(i + 1, 14)
    tp = [(h[i] + l[i] + c[i]) / 3 for i in range(len(c))]
    P = [0.0]; V = [0.0]
    for i in range(len(c)):
        P.append(P[-1] + tp[i] * v[i]); V.append(V[-1] + v[i])
    return dict(t=t, o=o, h=h, l=l, c=c, v=v, atr=atr, P=P, V=V, n=len(c))


def swings(D, k, t):
    """confirmed swing lows/highs (index lists) as of bar t."""
    lo, hi = [], []
    for i in range(max(k, t - 600), t - k + 1):
        w = range(i - k, i + k + 1)
        if D["l"][i] == min(D["l"][j] for j in w):
            lo.append(i)
        if D["h"][i] == max(D["h"][j] for j in w):
            hi.append(i)
    return lo, hi


def levels(D, t):
    """-> list of (tech, L) for bar t (all unbroken, causal)."""
    c, h, l, o, v, atr = D["c"], D["h"], D["l"], D["o"], D["v"], D["atr"]
    out = []
    lo, hi = swings(D, 12, t)
    for i in lo:
        if min(l[i + 1:t + 1] or [1e18]) >= l[i]:
            out.append(("SWING_SR", l[i]))
    for i in hi:
        if max(h[i + 1:t + 1] or [0]) <= h[i]:
            out.append(("SWING_SR", h[i]))
    lo2, hi2 = swings(D, 24, t)
    for name, idx in (("AVWAP_LOW", lo2), ("AVWAP_HIGH", hi2)):
        if idx:
            a = idx[-1]; dv = D["V"][t + 1] - D["V"][a]
            if dv > 0:
                out.append((name, (D["P"][t + 1] - D["P"][a]) / dv))
    step = c[t] * 0.0025
    prof = {}
    for j in range(t - 167, t + 1):
        b = int(((h[j] + l[j]) / 2) // step); prof[b] = prof.get(b, 0) + v[j]
    if prof:
        poc = max(prof, key=prof.get); tot = sum(prof.values()); acc = prof[poc]; lo_b = hi_b = poc
        while acc < 0.7 * tot:
            up = prof.get(hi_b + 1, 0); dn = prof.get(lo_b - 1, 0)
            if up == dn == 0 and (hi_b - lo_b) > 200:
                break
            if up >= dn:
                hi_b += 1; acc += up
            else:
                lo_b -= 1; acc += dn
        out += [("VP_POC", (poc + .5) * step), ("VP_VAL", lo_b * step), ("VP_VAH", (hi_b + 1) * step)]
    for i in range(max(25, t - 500), t - 2):
        mv = c[i + 3] - c[i]
        if abs(mv) < 2 * atr[i]:
            continue
        if max(v[i + 1:i + 4]) < 1.5 * statistics.median(v[i - 20:i]):
            continue
        if mv > 0 and c[i] < o[i]:
            if min(c[i + 1:t + 1]) >= l[i]:
                out.append(("OB", h[i]))
        elif mv < 0 and c[i] > o[i]:
            if max(c[i + 1:t + 1]) <= h[i]:
                out.append(("OB", l[i]))
    return out


def sim(D, s, t, L, A):
    """side s=+1 support/long, -1 resistance/short. Returns None (no touch) or (R, mae, mfe)."""
    h, l, c, n = D["h"], D["l"], D["c"], D["n"]
    hh, ll = (h, l) if s > 0 else ([-x for x in l], [-x for x in h])
    Lx = L if s > 0 else -L
    for j in range(t + 1, min(t + HT, n - 1) + 1):
        if ll[j] <= Lx:
            break
    else:
        return None
    end = min(j + HA - 1, n - 1); mae = mfe = 0.0
    for m in range(j, end + 1):
        mae = max(mae, (Lx - ll[m]) / A); mfe = max(mfe, (hh[m] - Lx) / A)
        if ll[m] <= Lx - A:
            return (-1.0, mae, mfe)
        if hh[m] >= Lx + A:
            return (1.0, mae, mfe)
    cc = c[end] if s > 0 else -c[end]
    return ((cc - Lx) / A, mae, mfe)


def regime(D, t):
    c = D["c"]
    return 1 if c[t] > sum(c[t - 719:t + 1]) / 720 else -1


def main():
    if OUT.exists():
        sys.exit("already run; a changed idea is a new test")
    D = prep(load()); n = D["n"]
    grid = list(range(WARM, n - HT - HA - 2, STEP)); half = grid[len(grid) // 2]
    gh = {0: [g for g in grid if g < half], 1: [g for g in grid if g >= half]}
    ev = []
    for t in grid:
        A = D["atr"][t]; px = D["c"][t]; best = {}
        for tech, L in levels(D, t):
            d = (px - L) / A
            if 0.5 <= abs(d) <= 4:
                key = (tech, 1 if d > 0 else -1)
                if key not in best or abs(d) < abs(best[key][0]):
                    best[key] = (d, L)
        hf = 0 if t < half else 1; rg = regime(D, t)
        for (tech, s), (d, L) in best.items():
            r = sim(D, s, t, L, A)
            pl = []
            for _ in range(NPL):
                u = random.choice(gh[hf]); Ap = D["atr"][u]
                pl.append(sim(D, s, u, D["c"][u] - d * Ap, Ap))
            ev.append(dict(tech=tech, s=s, t=t, wk=D["t"][t] // 604800000, hf=hf, rg=rg, A=A, L=L, r=r, pl=pl))

    def agg(es, mult=1.0):
        w = ts = 0; R = 0.0; pw = pt = 0; pR = 0.0; nR = 0.0; mae = mfe = 0.0
        for e in es:
            cst = COST * e["L"] / e["A"]
            if e["r"]:
                ts += 1; w += e["r"][0] > 0; R += e["r"][0]; nR += e["r"][0] - cst * mult
                mae += e["r"][1]; mfe += e["r"][2]
            for p in e["pl"]:
                if p:
                    pt += 1; pw += p[0] > 0; pR += p[0]
        return dict(n=len(es), touch=ts, touch_rate=ts / len(es) if es else 0, win=w / ts if ts else 0,
                    plc_win=pw / pt if pt else 0, lift=(w / ts - pw / pt) if ts and pt else 0,
                    gross_R=R / ts if ts else 0, net_R=nR / ts if ts else 0, plc_R=pR / pt if pt else 0,
                    mae=mae / ts if ts else 0, mfe=mfe / ts if ts else 0)

    def boot(es, f, B=1000):
        wks = {}
        for e in es:
            wks.setdefault(e["wk"], []).append(e)
        ks = list(wks)
        if len(ks) < 8:
            return float("nan")
        vals = sorted(f([e for k in (random.choice(ks) for _ in ks) for e in wks[k]]) for _ in range(B))
        return vals[int(0.005 * B)]

    res = {}
    for tech in sorted({e["tech"] for e in ev}):
        for s in (1, -1):
            es = [e for e in ev if e["tech"] == tech and e["s"] == s]
            if not es:
                continue
            a = agg(es); h0 = agg([e for e in es if e["hf"] == 0]); h1 = agg([e for e in es if e["hf"] == 1])
            r1 = agg([e for e in es if e["rg"] > 0]); r2 = agg([e for e in es if e["rg"] < 0]); a2 = agg(es, 2.0)
            lb_lift = boot(es, lambda x: agg(x)["lift"]); lb_net = boot(es, lambda x: agg(x)["net_R"])
            inf = (a["touch"] >= 200 and lb_lift > 0 and h0["lift"] > 0 and h1["lift"] > 0
                   and r1["lift"] > 0 and r2["lift"] > 0)
            tr = inf and lb_net > 0 and a2["net_R"] > 0 and h0["net_R"] > 0 and h1["net_R"] > 0
            verdict = ("TRADEABLE" if tr else "INFORMATIVE" if inf else
                       "INSUFFICIENT" if a["touch"] < 200 else "FAIL")
            res[f"{tech}|{'support' if s > 0 else 'resistance'}"] = dict(
                all=a, half1=h0, half2=h1, bull=r1, bear=r2, cost2x=a2, lift_lb=lb_lift, net_lb=lb_net, verdict=verdict)
    claims = claim_check(D)
    rank = sorted(res.items(), key=lambda kv: (-{"TRADEABLE": 2, "INFORMATIVE": 1}.get(kv[1]["verdict"], 0), -kv[1]["lift_lb"]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    json.dump(dict(registered="2026-10-18 10:15 SAST", data="PROXY BTC_USDT 60M var/proxy_market.db", bars=n,
                   events=len(ev), results=res, ranking=[k for k, _ in rank], claims=claims), open(OUT, "w"), indent=1)
    print(f"{'tech|side':24}{'touch':>6}{'win':>7}{'plc':>7}{'lift':>7}{'lbLift':>8}{'netR':>7}{'lbNet':>7}  verdict")
    for k, r in rank:
        a = r["all"]
        print(f"{k:24}{a['touch']:6}{a['win']:7.3f}{a['plc_win']:7.3f}{a['lift']:7.3f}{r['lift_lb']:8.3f}"
              f"{a['net_R']:7.3f}{r['net_lb']:7.3f}  {r['verdict']}")
    print(json.dumps(claims["summary"], indent=1))


def claim_check(D):
    calls = [json.loads(x) for x in open(ROOT / "var" / "guidance" / "btc_calls.jsonl")]
    cl = []
    for c in calls:
        base = dict(source=c["source"], published=c["published"], video=c["video_id"])
        for z in c.get("long_zones", []):
            cl.append(dict(base, kind="long_zone", lo=z[0], hi=z[1]))
        for z in c.get("short_zones", []):
            cl.append(dict(base, kind="short_zone", lo=z[0], hi=z[1]))
    odir = ROOT / "research" / "owner_method"; odir.mkdir(parents=True, exist_ok=True)
    with open(odir / "claims_zones_clo68.jsonl", "w") as f:
        for i, x in enumerate(cl):
            f.write(json.dumps(dict(x, id=i + 1)) + "\n")
    T = D["t"]; summ = {}; rows = []
    for x in cl:
        ms = int(datetime.fromisoformat(x["published"].replace("Z", "+00:00")).timestamp() * 1000)
        idx = [i for i in range(D["n"]) if T[i] + 3600000 <= ms]
        if not idx:
            continue
        t = idx[-1]; A = D["atr"][t]
        coin = sorted({tech for tech, L in levels(D, t) if x["lo"] - .5 * A <= L <= x["hi"] + .5 * A})
        s = 1 if x["kind"] == "long_zone" else -1
        r = sim(D, s, t, x["hi"] if s > 0 else x["lo"], A) if t + HT + HA < D["n"] else "pending"
        rows.append(dict(source=x["source"], kind=x["kind"], lo=x["lo"], hi=x["hi"], coincide=coin, result=r))
        g = summ.setdefault(x["source"], dict(zones=0, coincide=0, touched=0, win=0, pending=0))
        g["zones"] += 1; g["coincide"] += bool(coin)
        if r == "pending":
            g["pending"] += 1
        elif r:
            g["touched"] += 1; g["win"] += r[0] > 0
    return dict(summary=summ, n_claims=len(cl), rows=rows)


if __name__ == "__main__":
    main()
