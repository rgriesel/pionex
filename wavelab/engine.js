/* Wave Lab in-browser engine: a port of pionex_lab/waves/elliott.py and the DemoFeed from
 * pionex_lab/waves/feeds.py, plus the read-only /api routes. Used by the hosted standalone build
 * (tools/build_wavelab_standalone.py), which cannot reach a local server or the Pionex API.
 * Demo prices are SYNTHETIC, not market data. Wave counts are pattern hypotheses. */
"use strict";
(function () {
  /* ---------------------------------------------------------- sha256 (sync, for demo seeds) */
  const K = new Uint32Array([0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2]);
  function sha256(str) {
    const msg = new TextEncoder().encode(str), len = msg.length, bl = ((len + 9 + 63) >> 6) << 6;
    const buf = new Uint8Array(bl); buf.set(msg); buf[len] = 0x80;
    const bits = len * 8; for (let i = 0; i < 4; i++) buf[bl - 1 - i] = (bits >>> (8 * i)) & 0xff;
    const H = new Uint32Array([0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19]), W = new Uint32Array(64);
    const r = (x, n) => (x >>> n) | (x << (32 - n));
    for (let o = 0; o < bl; o += 64) {
      for (let i = 0; i < 16; i++) W[i] = (buf[o+4*i] << 24) | (buf[o+4*i+1] << 16) | (buf[o+4*i+2] << 8) | buf[o+4*i+3];
      for (let i = 16; i < 64; i++) { const s0 = r(W[i-15], 7) ^ r(W[i-15], 18) ^ (W[i-15] >>> 3), s1 = r(W[i-2], 17) ^ r(W[i-2], 19) ^ (W[i-2] >>> 10); W[i] = (W[i-16] + s0 + W[i-7] + s1) >>> 0; }
      let [a, b, c, d, e, f, g, h] = H;
      for (let i = 0; i < 64; i++) {
        const t1 = (h + (r(e, 6) ^ r(e, 11) ^ r(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + W[i]) >>> 0;
        const t2 = ((r(a, 2) ^ r(a, 13) ^ r(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) >>> 0;
        h = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0;
      }
      H[0] += a; H[1] += b; H[2] += c; H[3] += d; H[4] += e; H[5] += f; H[6] += g; H[7] += h;
    }
    return H;
  }
  const seedCache = new Map();
  function seed(s) { // first 8 bytes of sha256, big-endian, as BigInt (matches feeds.DemoFeed._seed)
    let v = seedCache.get(s); if (v !== undefined) return v;
    const H = sha256(s); v = (BigInt(H[0]) << 32n) | BigInt(H[1]);
    if (seedCache.size > 50000) seedCache.clear(); seedCache.set(s, v); return v;
  }

  /* ---------------------------------------------------------- demo feed */
  const IV = {"1M":60000,"5M":300000,"15M":900000,"30M":1800000,"60M":3600000,"4H":14400000,"8H":28800000,"12H":43200000,"1D":86400000};
  const SYMBOL_RE = /^[A-Z0-9]{1,20}_[A-Z0-9]{1,10}$/;
  const DEMO_SYMBOLS = ["BTC_USDT","ETH_USDT","SOL_USDT","XRP_USDT","BNB_USDT","DOGE_USDT","ADA_USDT","AVAX_USDT","LINK_USDT","DOT_USDT","LTC_USDT","TRX_USDT"];
  const PERIODS_H = [0.4, 1.1, 3.0, 8.0, 21.0, 55.0, 144.0, 377.0, 987.0, 2584.0];
  function validate(symbol, interval) {
    if (typeof symbol !== "string" || !SYMBOL_RE.test(symbol)) throw new ApiError(400, "invalid symbol");
    if (!(interval in IV)) throw new ApiError(400, "invalid interval");
  }
  function base(symbol) {
    const known = {BTC_USDT: 60000, ETH_USDT: 3000, SOL_USDT: 150, BNB_USDT: 550};
    return known[symbol] ?? 0.5 + Number(seed(symbol) % 20000n) / 100;
  }
  const phaseCache = new Map();
  function logp(symbol, tMs) {
    let ph = phaseCache.get(symbol);
    if (!ph) { const s = seed(symbol); ph = PERIODS_H.map((_, j) => Number((s >> BigInt(6 * j)) & 0x3Fn) / 63 * 2 * Math.PI); phaseCache.set(symbol, ph); }
    const hours = tMs / 3600000; let x = 0;
    for (let j = 0; j < PERIODS_H.length; j++) x += 0.004 * Math.sqrt(PERIODS_H[j]) * Math.sin(2 * Math.PI * hours / PERIODS_H[j] + ph[j]);
    return x;
  }
  function candles(symbol, interval, limit) {
    validate(symbol, interval);
    const step = IV[interval], now = Date.now(), cur = Math.floor(now / step), b = base(symbol);
    const out = {t: [], o: [], h: [], l: [], c: [], v: []};
    for (let k = cur - limit + 1; k <= cur; k++) {
      const t0 = k * step, t1 = Math.min(now, t0 + step), pts = [];
      for (let f = 0; f < 9; f++) pts.push(logp(symbol, t0 + f * (t1 - t0) / 8));
      const noise = Number(seed(`${symbol}:${interval}:${k}`) % 1000n) / 1000;
      const o = b * Math.exp(pts[0]), cl = b * Math.exp(pts[8]);
      const hi = b * Math.exp(Math.max(...pts)) * (1 + 0.0015 * noise), lo = b * Math.exp(Math.min(...pts)) * (1 - 0.0015 * (1 - noise));
      out.t.push(t0); out.o.push(o); out.h.push(Math.max(hi, o, cl)); out.l.push(Math.min(lo, o, cl)); out.c.push(cl);
      out.v.push(1000 * (step / 3600000) * (1 + noise) * (1 + Math.abs(pts[8] - pts[0]) * 50));
    }
    return out;
  }
  const cache = new Map();
  function bars(symbol, interval, limit) { // short cache: demo bars change only within the current bar
    const key = `${symbol}|${interval}|${limit}`, hit = cache.get(key), now = Date.now();
    if (hit && now - hit.at < 5000) return hit.b;
    const b = candles(symbol, interval, limit); if (cache.size > 200) cache.clear(); cache.set(key, {at: now, b}); return b;
  }

  /* ---------------------------------------------------------- elliott (port of elliott.py) */
  const DEGREES = {minor: 3.0, intermediate: 6.0, primary: 12.0};
  const IMPULSE_LABELS = ["0","1","2","3","4","5"], CORRECTION_LABELS = ["0","A","B","C"];
  function zigzag(h, l, pct) {
    const n = h.length; if (n < 2 || pct <= 0) return [];
    const piv = []; let trend = 0, hi = 0, lo = 0, ext = 0;
    for (let i = 1; i < n; i++) {
      if (trend === 0) {
        if (h[i] > h[hi]) hi = i; if (l[i] < l[lo]) lo = i;
        if (h[hi] >= l[lo] * (1 + pct)) { if (lo < hi) { piv.push({i: lo, price: l[lo], kind: "L", confirmed: true}); trend = 1; ext = hi; } else { piv.push({i: hi, price: h[hi], kind: "H", confirmed: true}); trend = -1; ext = lo; } }
      } else if (trend === 1) {
        if (h[i] >= h[ext]) ext = i; else if (l[i] <= h[ext] * (1 - pct)) { piv.push({i: ext, price: h[ext], kind: "H", confirmed: true}); trend = -1; ext = i; }
      } else {
        if (l[i] <= l[ext]) ext = i; else if (h[i] >= l[ext] * (1 + pct)) { piv.push({i: ext, price: l[ext], kind: "L", confirmed: true}); trend = 1; ext = i; }
      }
    }
    if (trend === 1) piv.push({i: ext, price: h[ext], kind: "H", confirmed: false});
    else if (trend === -1) piv.push({i: ext, price: l[ext], kind: "L", confirmed: false});
    return piv;
  }
  function autoThreshold(h, l, c, degree, lookback = 200) {
    const mult = DEGREES[degree]; if (mult === undefined) throw new ApiError(400, "invalid degree");
    const start = Math.max(0, c.length - lookback), r = [];
    for (let i = start; i < c.length; i++) if (c[i] > 0) r.push((h[i] - l[i]) / c[i]);
    r.sort((a, b) => a - b); const med = r.length ? r[r.length >> 1] : 0.01;
    return Math.min(0.5, Math.max(0.002, med * mult));
  }
  function band(x, lo, hi) { if (!(x > 0) || !isFinite(x)) return 0; if (x >= lo && x <= hi) return 1; const d = x < lo ? Math.log(lo / x) : Math.log(x / hi); return Math.max(0, 1 - d / Math.log(2)); }
  const norm = (p, up) => up ? p.slice() : p.map(x => -x);
  function checkImpulse(prices, up) {
    const q = norm(prices, up), n = q.length, w = [];
    for (let k = 0; k < n - 1; k++) w.push(k % 2 === 0 ? q[k+1] - q[k] : q[k] - q[k+1]);
    const rules = [], guides = [];
    if (n >= 3) { rules.push(["Wave 2 does not retrace beyond the start of wave 1", q[2] > q[0]]); guides.push(["Wave 2 retraces 38.2%-78.6% of wave 1", band(w[1] / w[0], 0.382, 0.786)]); }
    if (n >= 4) { rules.push(["Wave 3 travels beyond the end of wave 1", q[3] > q[1]]); guides.push(["Wave 3 is 1.382-2.618 x wave 1", band(w[2] / w[0], 1.382, 2.618)]); }
    if (n >= 5) { rules.push(["Wave 4 does not overlap wave 1", q[4] > q[1]]); guides.push(["Wave 4 retraces 23.6%-50% of wave 3", band(w[3] / w[2], 0.236, 0.5)]);
      guides.push(["Waves 2 and 4 alternate in depth", Math.min(1, Math.abs(w[1] / w[0] - w[3] / w[2]) / 0.2)]); }
    if (n >= 6) { rules.push(["Wave 3 is not the shortest of waves 1, 3, 5", !(w[2] < w[0] && w[2] < w[4])]); rules.push(["Wave 5 travels beyond the end of wave 3 (no truncation)", q[5] > q[3]]);
      guides.push(["Wave 5 is 0.618-1.618 x wave 1", band(w[4] / w[0], 0.618, 1.618)]); }
    return [rules, guides];
  }
  function checkCorrection(prices, down) {
    const q = norm(prices, down), a = q[0] - q[1], b = q[2] - q[1], rb = b / a;
    const kind = rb < 0.9 ? "zigzag" : rb > 1.0 ? "expanded flat" : "flat", rules = [], guides = [];
    if (kind === "zigzag") { rules.push(["Wave B does not retrace beyond the start of wave A", q[2] < q[0]]); guides.push(["Wave B retraces 38.2%-78.6% of wave A", band(rb, 0.382, 0.786)]); }
    else { rules.push(["Wave B retraces at most 138.2% of wave A", rb <= 1.382]); guides.push(["Wave B retraces 90%-123.6% of wave A", band(rb, 0.9, 1.236)]); }
    if (q.length >= 4) { const c = q[2] - q[3];
      if (kind === "zigzag") { rules.push(["Wave C travels beyond the end of wave A", q[3] < q[1]]); guides.push(["Wave C is 0.618-1.618 x wave A", band(c / a, 0.618, 1.618)]); }
      else { rules.push(["Wave C reaches at least 80% of wave A", c >= 0.8 * a]); guides.push(["Wave C is 1.0-1.618 x wave A", band(c / a, 1.0, 1.618)]); } }
    return [kind, rules, guides];
  }
  const round1 = x => Math.floor(x * 10 + 0.5) / 10;  // same half-up rule as elliott._round
  function score(rules, guides) { if (!rules.every(r => r[1]) || !guides.length) return 0; return round1(100 * guides.reduce((s, g) => s + g[1], 0) / guides.length); }
  const levels = (b, len, ratios, sign, kind, ref) => ratios.map(r => ({ratio: r, price: b + sign * r * len, kind, ref}));
  function targets(kind, labels, p, up) {
    const s = up ? 1 : -1, last = labels[labels.length - 1];
    if (kind === "impulse") {
      const w1 = Math.abs(p[1] - p[0]);
      if (last === "2") return [levels(p[1], w1, [0.5, 0.618, 0.786], -s, "retracement", "wave 1"), p[0], "Wave 2 correcting wave 1; wave 3 expected next"];
      if (last === "3") return [levels(p[2], w1, [1.0, 1.618, 2.618], s, "extension", "wave 1 from end of 2"), p[0], "Wave 3 in progress"];
      if (last === "4") return [levels(p[3], Math.abs(p[3] - p[2]), [0.236, 0.382, 0.5], -s, "retracement", "wave 3"), p[1], "Wave 4 correcting wave 3; wave 5 expected next"];
      if (last === "5") return [levels(p[4], w1, [0.618, 1.0], s, "extension", "wave 1 from end of 4").concat(levels(p[4], Math.abs(p[3] - p[0]), [0.618], s, "extension", "waves 1-3 from end of 4")), p[1], "Wave 5 in progress; an A-B-C correction usually follows"];
    } else {
      const wa = Math.abs(p[1] - p[0]);
      if (last === "B") return [levels(p[1], wa, [0.5, 0.618, 0.786], -s, "retracement", "wave A"), p[0], "Wave B retracing wave A; wave C expected next"];
      if (last === "C") return [levels(p[2], wa, [0.618, 1.0, 1.618], s, "extension", "wave A from end of B"), p[2], "Wave C in progress; the prior trend may resume after it"];
    }
    return [[], null, ""];
  }
  const ZONE_REF = {"2": "1", "3": "1", "4": "2", "5": "1", "B": "A", "C": "A"}, ZONE_TIME = [0.618, 1.618];
  function zone(labels, seg, t, tg) {  // mirror of elliott._zone
    const last = labels[labels.length - 1], ref = ZONE_REF[last];
    if (!tg.length || ref == null || !labels.includes(ref)) return null;
    const j = labels.indexOf(ref); if (j < 1) return null;
    const dur = t[seg[j].i] - t[seg[j - 1].i], start = t[seg[seg.length - 2].i], prices = tg.map(x => x.price);
    return {price_lo: Math.min(...prices), price_hi: Math.max(...prices), t_from: start + ZONE_TIME[0] * dur,
            t_to: start + ZONE_TIME[1] * dur, wave: last, time_ref: ref};
  }
  function channels(kind, pts) {
    const out = [], par = (a, b, th, name) => { const sl = b[0] !== a[0] ? (b[1] - a[1]) / (b[0] - a[0]) : 0; out.push({name, base: [a, b], parallel: [th, [th[0] + (b[0] - a[0]), th[1] + sl * (b[0] - a[0])]]}); };
    if (kind === "impulse") { if (pts.length === 4) par(pts[0], pts[2], pts[1], "0-2 channel"); else if (pts.length >= 5) par(pts[2], pts[4], pts[3], "2-4 channel"); }
    else if (pts.length >= 3) par(pts[0], pts[2], pts[1], "A-C channel");
    return out;
  }
  function candidates(piv, end, minLen) {
    const out = [];
    for (let size = minLen; size < 7; size++) { const st = end - size + 1; if (st < 0) continue; const seg = piv.slice(st, end + 1), up = seg[0].kind === "L";
      const [rules, guides] = checkImpulse(seg.map(p => p.price), up), sc = score(rules, guides); if (sc > 0) out.push({kind: "impulse", sub: null, seg, up, rules, guides, sc}); }
    for (const size of [3, 4]) { const st = end - size + 1; if (st < 0) continue; const seg = piv.slice(st, end + 1), down = seg[0].kind === "H";
      const [sub, rules, guides] = checkCorrection(seg.map(p => p.price), down), sc = score(rules, guides); if (sc > 0) out.push({kind: "correction", sub, seg, up: !down, rules, guides, sc}); }
    return out;
  }
  function countJson(cd, t, cur) {
    const {kind, sub, seg, up, rules, guides, sc} = cd, labels = (kind === "impulse" ? IMPULSE_LABELS : CORRECTION_LABELS).slice(0, seg.length);
    const prices = seg.map(p => p.price), [tg, inv, status] = targets(kind, labels, prices, up);
    const weight = kind === "impulse" ? {3: 0.70, 4: 0.85, 5: 0.93, 6: 1.0}[seg.length] : {3: 0.70, 4: 0.95}[seg.length];
    const last = labels[labels.length - 1], withTrend = ["1","3","5","A","C"].includes(last);
    return {
      type: sub == null ? kind : `${kind} (${sub})`, direction: up ? "bullish" : "bearish", trend: up ? "up" : "down", move: up === withTrend ? "up" : "down",
      complete: seg.length === labels.length && ["5", "C"].includes(last) && seg[seg.length - 1].confirmed, current_wave: last, status,
      waves: labels.map((lab, k) => ({label: lab, i: seg[k].i, t: t[seg[k].i], price: seg[k].price, confirmed: seg[k].confirmed})),
      rules: rules.map(([text, ok]) => ({text, ok: !!ok})), guidelines: guides.map(([text, v]) => ({text, fit: Math.floor(v * 100 + 0.5) / 100})),
      score: round1(sc * weight), targets: tg, zone: zone(labels, seg, t, tg), invalidation: inv, invalidated: inv != null && (up ? cur < inv : cur > inv),
      channels: channels(kind, seg.map(p => [p.i, p.price])).map(ch => ({name: ch.name, base: ch.base.map(a => ({t: t[a[0]], i: a[0], price: a[1]})), parallel: ch.parallel.map(a => ({i: a[0], price: a[1]}))})),
    };
  }
  function supportResistance(h, l, c, maxLevels = 8) {
    if (c.length < 10) return [];
    const seen = new Map();
    for (const deg in DEGREES) for (const p of zigzag(h, l, autoThreshold(h, l, c, deg))) if (p.confirmed) seen.set(`${p.i}|${p.kind}`, [p.price, p.kind]);
    const prices = [...seen.values()]; if (!prices.length) return [];
    const tol = autoThreshold(h, l, c, "minor") / 6; prices.sort((a, b) => a[0] - b[0] || (a[1] < b[1] ? -1 : 1));
    const cl = [];
    for (const [price] of prices) { const z = cl[cl.length - 1]; if (z && price <= z.hi * (1 + tol)) { z.sum += price; z.n++; z.hi = price; } else cl.push({sum: price, n: 1, hi: price}); }
    const last = c[c.length - 1];
    const out = cl.filter(z => z.n >= 2).map(z => ({price: z.sum / z.n, touches: z.n, kind: z.sum / z.n > last ? "resistance" : "support"}));
    out.sort((a, b) => b.touches - a.touches || Math.abs(a.price - last) - Math.abs(b.price - last));
    return out.slice(0, maxLevels).sort((a, b) => a.price - b.price);
  }
  function waveOscillator(h, l, fast = 5, slow = 35) {
    const m = h.map((x, i) => (x + l[i]) / 2), out = []; let sf = 0, ss = 0;
    for (let i = 0; i < m.length; i++) { sf += m[i]; ss += m[i]; if (i >= fast) sf -= m[i - fast]; if (i >= slow) ss -= m[i - slow]; out.push(i + 1 >= slow ? sf / fast - ss / slow : null); }
    return out;
  }
  function postTargets(cj) { const w = cj.waves, s = w[0].price, e = w[w.length - 1].price; return levels(e, Math.abs(e - s), [0.382, 0.5, 0.618], e > s ? -1 : 1, "retracement", "completed structure"); }
  function history(piv, t, last, primary) {
    const taken = primary ? [[primary.waves[0].i, primary.waves[primary.waves.length - 1].i]] : [], cands = [];
    for (let end = 3; end < piv.length - 1; end++) for (const cd of candidates(piv, end, 4)) if ((cd.kind === "impulse" && cd.seg.length === 6) || (cd.kind === "correction" && cd.seg.length === 4)) cands.push(cd);
    cands.sort((a, b) => b.sc - a.sc);
    const out = [];
    for (const cd of cands) { const a = cd.seg[0].i, b = cd.seg[cd.seg.length - 1].i;
      if (taken.some(([x0, x1]) => !(b <= x0 || a >= x1))) continue; taken.push([a, b]);
      const cj = countJson(cd, t, last); out.push({type: cj.type, direction: cj.direction, waves: cj.waves, score: cj.score}); if (out.length >= 8) break; }
    return out.sort((a, b) => a.waves[0].i - b.waves[0].i);
  }
  function analyze(t, o, h, l, c, degree = "intermediate", pct = null, maxAlt = 3, hist = true) {
    if (c.length < 20) return {degree, threshold: null, pivots: [], primary: null, alternates: [], history: [], levels: [], note: "not enough bars"};
    const thr = pct || autoThreshold(h, l, c, degree), piv = zigzag(h, l, thr), last = c[c.length - 1], counts = [];
    if (piv.length >= 3) for (const cd of candidates(piv, piv.length - 1, 3)) counts.push(countJson(cd, t, last));
    if (piv.length >= 5) for (const cd of candidates(piv, piv.length - 2, 4)) {
      if (!((cd.kind === "impulse" && cd.seg.length === 6) || (cd.kind === "correction" && cd.seg.length === 4))) continue;
      const cj = countJson(cd, t, last), done5 = cd.kind === "impulse";
      cj.status = done5 ? "Five waves complete; the latest swing may be wave A of a correction" : "A-B-C complete; the latest swing may start a new trend";
      cj.current_wave = done5 ? "A" : "1"; cj.move = cj.trend === "up" ? "down" : "up";
      cj.targets = postTargets(cj); cj.zone = null; cj.invalidation = null; cj.invalidated = false; cj.channels = []; cj.score = round1(cj.score * 0.97);
      counts.push(cj);
    }
    const valid = counts.filter(x => !x.invalidated).sort((a, b) => b.score - a.score), seen = new Set(), ranked = [];
    for (const x of valid) { const k = `${x.type}|${x.waves[0].i}|${x.waves.length}`; if (!seen.has(k)) { seen.add(k); ranked.push(x); } }
    const primary = ranked[0] || null;
    return {degree, threshold: thr, pivots: piv.map(p => ({i: p.i, t: t[p.i], price: p.price, kind: p.kind, confirmed: p.confirmed})),
      primary, alternates: ranked.slice(1, 1 + maxAlt), history: hist ? history(piv, t, last, primary) : [], levels: supportResistance(h, l, c),
      note: "Wave counts are pattern hypotheses, not forecasts or evidence of an edge."};
  }
  function scanSummary(symbol, interval, a, last) {
    const p = a.primary, row = {symbol, interval, degree: a.degree, last, pattern: null, direction: null, move: null, current_wave: null, status: "no valid count", score: 0, next_target: null, invalidation: null, risk_pct: null};
    if (!p) return row;
    Object.assign(row, {pattern: p.type, direction: p.direction, move: p.move, current_wave: p.current_wave, status: p.status, score: p.score, invalidation: p.invalidation});
    const up = p.move === "up", ahead = p.targets.map(x => x.price).filter(x => up ? x > last : x < last);
    if (ahead.length) row.next_target = ahead.reduce((m, v) => Math.abs(v - last) < Math.abs(m - last) ? v : m);
    if (p.invalidation) row.risk_pct = Math.floor(Math.abs(last - p.invalidation) / last * 100 * 100 + 0.5) / 100;
    return row;
  }

  /* ---------------------------------------------------------- api routes (mirror server.py) */
  class ApiError extends Error { constructor(status, msg) { super(msg); this.status = status; } }
  const FEED = {name: "demo", label: "DEMO: synthetic prices, not market data"};
  function csv(q, name, maxn = 40) { const items = (q.get(name) || "").split(",").map(x => x.trim().toUpperCase()).filter(Boolean); if (!items.length || items.length > maxn) throw new ApiError(400, `${name}: 1-${maxn} items`); return items; }
  const clampLimit = v => Math.max(20, Math.min(1000, parseInt(v, 10) || 500));
  function route(path) {
    const u = new URL(path, "http://wavelab.local"), q = u.searchParams;
    switch (u.pathname) {
      case "/api/meta": return {feed: FEED.name, feed_label: FEED.label, fallback_reason: "hosted page: the Pionex API is not reachable from here", hosted: true,
        intervals: Object.keys(IV), degrees: Object.keys(DEGREES), disclaimer: "Wave counts are pattern hypotheses, not forecasts or evidence of profitability."};
      case "/api/symbols": return {feed: FEED.name, symbols: DEMO_SYMBOLS.slice()};
      case "/api/candles": case "/api/analysis": {
        const sym = (q.get("symbol") || "").toUpperCase(), iv = q.get("interval") || "60M"; validate(sym, iv);
        const b = bars(sym, iv, clampLimit(q.get("limit")));
        if (u.pathname === "/api/candles") return {feed: FEED.name, symbol: sym, interval: iv, ...b};
        const deg = q.get("degree") || "intermediate"; if (!(deg in DEGREES)) throw new ApiError(400, "invalid degree");
        const pct = q.get("pct") ? parseFloat(q.get("pct")) : null; if (pct !== null && !(pct >= 0.001 && pct <= 0.5)) throw new ApiError(400, "pct must be within 0.001-0.5");
        const a = analyze(b.t, b.o, b.h, b.l, b.c, deg, pct); a.ewo = waveOscillator(b.h, b.l);
        const out = {feed: FEED.name, symbol: sym, interval: iv, ...a}; if (q.get("bars") === "1") out.bars = b; return out;
      }
      case "/api/quotes": { const quotes = {};
        for (const s of csv(q, "symbols")) { validate(s, "60M"); const b = bars(s, "60M", 25), last = b.c[b.c.length - 1], ref = b.c[0];
          quotes[s] = {last, change_pct: (last / ref - 1) * 100, high: Math.max(...b.h), low: Math.min(...b.l), spark: b.c}; }
        return {feed: FEED.name, quotes}; }
      case "/api/scan": { const syms = csv(q, "symbols"), ivs = (q.get("intervals") || "").split(",").filter(Boolean);
        if (!ivs.length || ivs.length > 6) throw new ApiError(400, "intervals: 1-6 items");
        syms.forEach(s => ivs.forEach(iv => validate(s, iv)));
        const deg = q.get("degree") || "intermediate"; if (!(deg in DEGREES)) throw new ApiError(400, "invalid degree");
        const rows = []; for (const s of syms) for (const iv of ivs) { if (rows.length >= 60) break; const b = bars(s, iv, 500);
          rows.push(scanSummary(s, iv, analyze(b.t, b.o, b.h, b.l, b.c, deg, null, 3, false), b.c[b.c.length - 1])); }
        return {feed: FEED.name, degree: deg, rows}; }
    }
    throw new ApiError(404, "not found");
  }
  window.WaveEngine = {
    route(path) { return new Promise((res, rej) => { try { res(JSON.parse(JSON.stringify(route(path)))); } catch (e) { rej(e); } }); },
    analyze, zigzag, scanSummary, candles, seed,
  };
})();
