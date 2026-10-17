"""Luck-proofing suite (CLO-44). Research only: no order path, no network, stdlib only.

Pre-registered 2026-10-17 18:20 SAST, BEFORE any real-data run. Everything below is frozen; a changed
threshold is a new suite version (bump SUITE) and the old verdicts stay in docs/STRATEGY_LOG.md.

Question answered: could this strategy's backtest look this good by luck, given how many things the firm
has already tried? A strategy is luck-ELIGIBLE only if EVERY test below passes. The proof gate
(live/gate.py) reads var/reports/luck_<id>.json through verify_report() and refuses anything else.

Trial registry: var/trials.db, append-only (UPDATE/DELETE blocked by triggers). Every test and variant ever
run is one or more rows (backfilled from docs/STRATEGY_LOG.md rows, a row naming "N tests" counts N, the
"Lab research cycles" row counts 15, plus every var/reports/*.json that no log row names; each luck run adds
its own parameter-grid configurations AFTER computing its report). N = SUM(weight). N is a lower bound
(research.db lab cycles of 2026-09 and unlogged variants are not all countable); an undercount favours
passing, so it is stated, not hidden. `py -m pionex_lab trials` prints N.

Tightening with the count: L = max(0, floor(log2(N / 100))).
  deflated Sharpe probability >= min(0.99, 0.95 + 0.01 L)
  PBO (CSCV, 16 partitions)    <= max(0.05, 0.20 - 0.025 L)
  permutation p                <= max(0.001, 0.01 / (1 + L))
A report is only valid while L of the current registry equals the L it was computed at.

Tests (daily series from swing/cta.simulate on the 10-coin Binance PROXY daily archive 2017-12 -> now,
base = the strategy's own frozen rules; configuration grid G = lookback sets {(15,45,90),(20,60,120),
(30,90,180)} x target {0.30,0.40,0.50} x band {0.01,0.02,0.05}; Donchian has no lookback axis, equal
sizing has no target axis):
  T1 history       >= 750 daily observations.
  T2 deflated Sharpe (Bailey & Lopez de Prado 2014): SR0 = sqrt(V) * ((1-g) Z(1-1/N) + g Z(1-1/(N e))),
       V = max(variance of per-period Sharpe over G, 1/(T-1)), N = max(registry count, |G|);
       DSR = Phi((SR - SR0) sqrt(T-1) / sqrt(1 - skew SR + (kurt-1)/4 SR^2)); pass if DSR >= threshold.
  T3 PBO by combinatorially symmetric cross-validation over G (16 equal time partitions, all 12,870
       splits; logit of the out-of-sample relative rank of the in-sample best); pass if PBO <= threshold.
  T4 timing null: for each coin the strategy's in/out weight series is circularly shifted by a random
       offset (>= 30 days), which keeps exposure and every holding time exactly and destroys the timing;
       statistic = mean pre-cost weight x next-day return per coin-day; 10,000 shifts; one-sided p; pass
       if p <= threshold.
  T5 parameter sensitivity: every one-step neighbour of the base in G (adjacent lookback set, target
       +-0.10, band 0.01/0.05) must have CAGR > 0 and Sharpe >= 0.6 x base Sharpe.
  T6 block bootstrap: circular blocks of 20 days, 2,000 resamples; the 2.5% lower bound of the mean daily
       net return must be > 0.
  T7 regimes (defined on BTC, point in time, from the close before the day): crash = 30-day return
       <= -25%; else bear = 90-day return <= -15%; else bull = 90-day return >= +15%; else sideways.
       Each regime needs >= 30 days (else FAIL: untested) and a mean daily net return of at least
       bull 0, sideways -3, bear -3, crash -15 basis points.
  T8 cost stress: costs x2 -> CAGR > 0 and Sharpe >= 0.70; costs x4 -> CAGR > 0 and Sharpe >= 0.50.
  T9 Monte Carlo at the owner's 100 USDT capital (10 USDT minimum buy, allocation capped at 100): the
       capital-constrained daily net returns are resampled in circular 5-day blocks into 10,000 30-day
       paths; P(equity touches <= 50% of start within the path) must be <= 1% and the 5th percentile of
       the 30-day return must be >= -30%. The expected 30-day return distribution is reported.
All random draws use fixed seeds. Backtests are not proof of profit: this suite can only fail a strategy,
and forward results on live Pionex prices remain the real test.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import operator
import random
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist

SUITE = "luck-1 (2026-10-17 18:20 SAST)"
ND = NormalDist()
DAY = 86_400_000
EULER = 0.5772156649015329

MIN_DAYS = 750
N_PERM = 10_000
PERM_MIN_SHIFT = 30
PBO_PARTS = 16
BOOT_BLOCK, BOOT_N = 20, 2_000
NEIGHBOUR_SHARPE_FRAC = 0.6
COST_BOUNDS = {2: 0.70, 4: 0.50}                     # cost multiplier -> minimum Sharpe (CAGR must be > 0)
REGIME_FLOOR_BPS = {"bull": 0.0, "sideways": -3.0, "bear": -3.0, "crash": -15.0}
REGIME_MIN_DAYS = 30
MC_CAPITAL, MC_PATHS, MC_DAYS, MC_BLOCK = 100.0, 10_000, 30, 5
MC_RUIN_LEVEL, MC_RUIN_MAX, MC_P05_MIN = 0.50, 0.01, -0.30
LB_SETS = ((15, 45, 90), (20, 60, 120), (30, 90, 180))
TARGETS = (0.30, 0.40, 0.50)
BANDS = (0.01, 0.02, 0.05)
MAX_REPORT_AGE_DAYS = 30
SEED = 20261017

# strategy id -> frozen base rules. gate ids map to these through GATE_TO_LUCK (forward book ids).
SPECS = {
    "cta_v1_1": {"rule": "tsmom_vote", "sizing": "vol", "coins": None, "lb": 1, "target": 0.40, "band": 0.02,
                 "regression": (0.358, 0.263, 1.37)},
    "cta_growth": {"rule": "tsmom_vote", "sizing": "equal", "coins": None, "lb": 1, "target": None, "band": 0.02},
    "cta_canary": {"rule": "tsmom_vote", "sizing": "vol", "coins": ("BTC_USDT", "ETH_USDT"), "lb": 1,
                   "target": 0.40, "band": 0.02},
    "donchian_c1": {"rule": "donchian", "sizing": "vol", "coins": None, "lb": None, "target": 0.40, "band": 0.02,
                    "regression": (0.223, 0.205, 1.36)},
}
GATE_TO_LUCK = {"defensive": "cta_v1_1", "growth": "cta_growth", "canary": "cta_canary", "donchian_c1": "donchian_c1"}


# --------------------------------------------------------------------------- thresholds
def level(n: int) -> int:
    return max(0, int(math.floor(math.log2(max(int(n), 1) / 100.0))))


def thresholds(n: int) -> dict:
    lv = level(n)
    return {"suite": SUITE, "level": lv, "dsr_prob_min": min(0.99, 0.95 + 0.01 * lv),
            "pbo_max": max(0.05, 0.20 - 0.025 * lv), "perm_p_max": max(0.001, 0.01 / (1 + lv)),
            "min_days": MIN_DAYS, "neighbour_sharpe_frac": NEIGHBOUR_SHARPE_FRAC, "cost_min_sharpe": COST_BOUNDS,
            "regime_floor_bps": REGIME_FLOOR_BPS, "regime_min_days": REGIME_MIN_DAYS,
            "mc_ruin_max": MC_RUIN_MAX, "mc_p05_min": MC_P05_MIN}


def thresholds_sha(n: int) -> str:
    return hashlib.sha256(json.dumps(thresholds(n), sort_keys=True, default=str).encode()).hexdigest()


# --------------------------------------------------------------------------- trial registry
_SCHEMA = """
CREATE TABLE IF NOT EXISTS trials(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, source TEXT NOT NULL,
  ref TEXT NOT NULL, strategy_id TEXT, params TEXT, data_span TEXT, result TEXT, weight INTEGER NOT NULL DEFAULT 1,
  UNIQUE(source, ref));
CREATE TRIGGER IF NOT EXISTS trials_no_update BEFORE UPDATE ON trials BEGIN SELECT RAISE(ABORT, 'trials is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trials_no_delete BEFORE DELETE ON trials BEGIN SELECT RAISE(ABORT, 'trials is append-only'); END;
"""
_ROW_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_N_TESTS = re.compile(r"(\d+)\s+tests")
_LOG_WEIGHTS = {"Lab research cycles": 15}
_NOT_TESTS = ("luck_", "live_gate", "forward_shadow", "shadow_grid", "btc_guidance")


def open_registry(path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path))
    db.executescript(_SCHEMA)
    return db


def record_trial(path, source, ref, strategy_id="", params=None, data_span="", result="", weight=1, ts=None) -> bool:
    """Append one trial; False if (source, ref) is already registered (backfill and luck runs are idempotent)."""
    db = open_registry(path)
    try:
        cur = db.execute("INSERT OR IGNORE INTO trials(ts,source,ref,strategy_id,params,data_span,result,weight) VALUES(?,?,?,?,?,?,?,?)",
                         (int(ts if ts is not None else time.time() * 1000), source, str(ref), strategy_id,
                          json.dumps(params, sort_keys=True, default=str) if params is not None else None,
                          data_span, str(result)[:300], int(weight)))
        db.commit()
        return cur.rowcount == 1
    finally:
        db.close()


def trial_count(path) -> int:
    if not Path(path).exists():
        return 0
    db = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    try:
        return int(db.execute("SELECT COALESCE(SUM(weight),0) FROM trials").fetchone()[0])
    except sqlite3.Error:
        return 0
    finally:
        db.close()


def _log_rows(text: str):
    section = ""
    for line in text.splitlines():
        if line.startswith("## "):
            section = line
        elif section and not section.startswith(("## Being tracked", "## Red Team")) and line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 3 and _ROW_DATE.match(cells[0].replace("*", "")):
                yield cells


def backfill(registry, log_path, reports_dir) -> dict:
    """Idempotent. Returns {"log_rows": n_new, "reports": n_new, "count": N}."""
    text = Path(log_path).read_text(encoding="utf-8")
    new_log = 0
    for cells in _log_rows(text):
        date = _ROW_DATE.match(cells[0].replace("*", "")).group(0)
        label = re.sub(r"[*`]", "", cells[1])
        weight = next((w for k, w in _LOG_WEIGHTS.items() if k in label), None)
        if weight is None:
            m = _N_TESTS.search(label)
            weight = int(m.group(1)) if m else 1
        ts = int(datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
        verdict = re.sub(r"[*`]", "", cells[-1])[:80]
        if record_trial(registry, "strategy_log", f"{date}|{label[:120]}", label[:60], None, "", verdict, weight, ts):
            new_log += 1
    new_rep = 0
    for f in sorted(Path(reports_dir).glob("*.json")):
        if f.stem in text or f.name in text or any(f.name.startswith(p) for p in _NOT_TESTS):
            continue
        ts = int(f.stat().st_mtime * 1000)
        if record_trial(registry, "report", f.name, f.stem, None, "", "report file not named in STRATEGY_LOG", 1, ts):
            new_rep += 1
    return {"log_rows": new_log, "reports": new_rep, "count": trial_count(registry)}


# --------------------------------------------------------------------------- statistics
def _moments(xs):
    n = len(xs)
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / n)
    if sd == 0:
        return m, 0.0, 0.0, 3.0
    skew = sum((x - m) ** 3 for x in xs) / n / sd ** 3
    kurt = sum((x - m) ** 4 for x in xs) / n / sd ** 4
    return m, sd, skew, kurt


def sharpe_period(xs) -> float:
    m, sd, _s, _k = _moments(xs)
    return m / sd if sd else 0.0


def expected_max_sr(n_trials: int, var_sr: float) -> float:
    if n_trials <= 1:
        return 0.0
    return math.sqrt(var_sr) * ((1 - EULER) * ND.inv_cdf(1 - 1 / n_trials) + EULER * ND.inv_cdf(1 - 1 / (n_trials * math.e)))


def deflated_sharpe(returns, n_trials: int, var_sr: float | None = None) -> dict:
    t = len(returns)
    m, sd, skew, kurt = _moments(returns)
    sr = m / sd if sd else 0.0
    v = max(var_sr or 0.0, 1.0 / (t - 1))
    sr0 = expected_max_sr(n_trials, v)
    denom = 1 - skew * sr + (kurt - 1) / 4 * sr * sr
    z = (sr - sr0) * math.sqrt(t - 1) / math.sqrt(denom) if denom > 0 else float("-inf")
    return {"obs": t, "sr_daily": sr, "sr_annual": sr * math.sqrt(365.25), "sr0_daily": sr0, "sr0_annual": sr0 * math.sqrt(365.25),
            "n_trials": n_trials, "var_sr": v, "skew": skew, "kurtosis": kurt, "prob": ND.cdf(z) if z != float("-inf") else 0.0}


def pbo_cscv(series: dict, parts: int = PBO_PARTS) -> dict:
    """series: config -> equal-length list of period returns. Probability that the in-sample best config ranks
    in the bottom half out of sample (CSCV, Bailey et al.)."""
    names = list(series)
    m = len(names)
    if m < 4:
        raise ValueError("PBO needs >= 4 configurations")
    t = min(len(series[k]) for k in names) // parts * parts
    size = t // parts
    agg = {k: [(sum(v), sum(x * x for x in v)) for v in (series[k][i * size:(i + 1) * size] for i in range(parts))] for k in names}
    tot = {k: (sum(a for a, _ in agg[k]), sum(b for _, b in agg[k])) for k in names}

    def sr(s, q, n):
        mean = s / n
        var = q / n - mean * mean
        return mean / math.sqrt(var) if var > 1e-18 else 0.0

    logits = []
    for combo in itertools.combinations(range(parts), parts // 2):
        n_is = size * (parts // 2)
        is_sr, oos_sr = [], []
        for k in names:
            s = sum(agg[k][i][0] for i in combo)
            q = sum(agg[k][i][1] for i in combo)
            is_sr.append(sr(s, q, n_is))
            oos_sr.append(sr(tot[k][0] - s, tot[k][1] - q, t - n_is))
        best = max(range(m), key=is_sr.__getitem__)
        rank = 1 + sum(1 for x in oos_sr if x < oos_sr[best])          # 1 = worst OOS
        w = rank / (m + 1)
        logits.append(math.log(w / (1 - w)))
    return {"configs": m, "splits": len(logits), "pbo": sum(1 for x in logits if x <= 0) / len(logits),
            "logit_mean": sum(logits) / len(logits)}


def timing_null(weights: list, rets: list, n_perm: int = N_PERM, seed: int = SEED, min_shift: int = PERM_MIN_SHIFT) -> dict:
    """weights/rets: per coin, aligned lists (weight decided before the day, that day's return). Circular shifts keep
    each coin's exposure and holding times exactly. Statistic: mean weight x return per coin-day."""
    pairs = [(w, r) for w, r in zip(weights, rets) if len(w) > 2 * min_shift + 1]
    if not pairs:
        raise ValueError("no coin with enough bars")
    cnt = sum(len(w) for w, _ in pairs)
    mul = operator.mul
    actual = sum(sum(map(mul, w, r)) for w, r in pairs) / cnt
    rng = random.Random(seed)
    nulls = []
    for _ in range(n_perm):
        tot = 0.0
        for w, r in pairs:
            k = rng.randrange(min_shift, len(w) - min_shift)
            tot += sum(map(mul, w[k:] + w[:k], r))
        nulls.append(tot / cnt)
    ge = sum(1 for x in nulls if x >= actual)
    mean = sum(nulls) / n_perm
    sd = math.sqrt(sum((x - mean) ** 2 for x in nulls) / n_perm)
    return {"perms": n_perm, "actual_bps_per_coin_day": actual * 1e4, "null_mean_bps": mean * 1e4, "null_sd_bps": sd * 1e4,
            "p": (1 + ge) / (1 + n_perm), "exposure": sum(sum(w) for w, _ in pairs) / cnt, "coin_days": cnt}


def block_bootstrap(xs, block: int = BOOT_BLOCK, n_boot: int = BOOT_N, seed: int = SEED, q: float = 0.025) -> dict:
    n = len(xs)
    rng = random.Random(seed)
    x2, s2 = xs + xs[:block], [x * x for x in xs]
    s2 = s2 + s2[:block]
    means, sharpes = [], []
    nb = -(-n // block)
    for _ in range(n_boot):
        a = b = 0.0
        for _j in range(nb):
            s = rng.randrange(n)
            a += sum(x2[s:s + block])
            b += sum(s2[s:s + block])
        cnt = nb * block
        m = a / cnt
        var = b / cnt - m * m
        means.append(m)
        sharpes.append(m / math.sqrt(var) * math.sqrt(365.25) if var > 1e-18 else 0.0)
    means.sort()
    sharpes.sort()
    i = int(q * n_boot)
    return {"mean_lower_bps": means[i] * 1e4, "sharpe_lower": sharpes[i], "block": block, "resamples": n_boot, "q": q}


def monte_carlo(xs, capital: float = MC_CAPITAL, paths: int = MC_PATHS, days: int = MC_DAYS, block: int = MC_BLOCK,
                seed: int = SEED, ruin: float = MC_RUIN_LEVEL) -> dict:
    n = len(xs)
    x2 = xs + xs[:block]
    rng = random.Random(seed)
    nb = -(-days // block)
    finals, ruined = [], 0
    for _ in range(paths):
        eq, lo, k = 1.0, 1.0, 0
        for _j in range(nb):
            s = rng.randrange(n)
            for r in x2[s:s + block]:
                if k >= days:
                    break
                eq *= 1 + r
                lo = min(lo, eq)
                k += 1
        finals.append(eq - 1)
        ruined += lo <= ruin
    finals.sort()
    pct = lambda p: finals[min(paths - 1, int(p * paths))]
    return {"capital_usdt": capital, "paths": paths, "days": days, "p_lose_50pct": ruined / paths,
            "return_30d": {"p05": pct(0.05), "p25": pct(0.25), "p50": pct(0.50), "p75": pct(0.75), "p95": pct(0.95)},
            "expected_30d_return": sum(finals) / paths, "usdt_30d": {k: round(capital * v, 2) for k, v in
                                                                       (("p05", pct(0.05)), ("p50", pct(0.5)), ("p95", pct(0.95)))},
            "note": "block-resampled history (bull-heavy sample); a distribution of the past, not a forecast"}


def regime_labels(btc_closes: dict) -> dict:
    """day (ms) -> regime, from BTC closes strictly before that day (no look-ahead). Days without history are omitted."""
    out = {}
    for t in btc_closes:
        c1, c30, c90 = btc_closes.get(t - DAY), btc_closes.get(t - 31 * DAY), btc_closes.get(t - 91 * DAY)
        if c1 is None or c30 is None or c90 is None:
            continue
        r30, r90 = c1 / c30 - 1, c1 / c90 - 1
        out[t] = "crash" if r30 <= -0.25 else "bear" if r90 <= -0.15 else "bull" if r90 >= 0.15 else "sideways"
    return out


# --------------------------------------------------------------------------- strategy runs
def _with_lookbacks(data, lb):
    """Copy of the cta data with r20/r60/r120 recomputed at the lookbacks lb (the signal reads those three keys)."""
    out = {}
    for s, rows in data.items():
        ts = sorted(rows)
        c = [rows[t]["c"] for t in ts]
        new = {}
        for i, t in enumerate(ts):
            row = dict(rows[t])
            for key, n in zip(("r20", "r60", "r120"), lb):
                row[key] = c[i] / c[i - n] - 1 if i >= n else float("nan")
            new[t] = row
        out[s] = new
    return out


def grid_configs(spec) -> list:
    lbs = range(len(LB_SETS)) if spec["lb"] is not None else (None,)
    tgts = TARGETS if spec["target"] is not None else (None,)
    return [(lb, tg, bd) for lb in lbs for tg in tgts for bd in BANDS]


def neighbours(spec, cfg) -> list:
    lb, tg, bd = cfg
    out = []
    if lb is not None:
        out += [(x, tg, bd) for x in (lb - 1, lb + 1) if 0 <= x < len(LB_SETS)]
    if tg is not None:
        i = TARGETS.index(tg)
        out += [(lb, TARGETS[j], bd) for j in (i - 1, i + 1) if 0 <= j < len(TARGETS)]
    i = BANDS.index(bd)
    out += [(lb, tg, BANDS[j]) for j in (i - 1, i + 1) if 0 <= j < len(BANDS)]
    return out


def base_config(spec):
    return (spec["lb"], spec["target"], spec["band"])


def load_data(paths, rule):
    from ..swing import cta, donchian
    data = cta.load(paths)
    return donchian.add_dc(data) if rule == "donchian" else data


def _run_config(data_by_lb, spec, cfg, coins, cost=None, capital=None):
    from ..swing import cta
    lb, tg, bd = cfg
    data = data_by_lb[lb]
    return cta.simulate(data, spec["rule"], spec["sizing"], 0, band=bd, target=tg if tg is not None else 0.40,
                        capital=capital, cost=cost, coins=coins)


def _timing_inputs(data, rule, coins):
    from ..swing import cta
    ws, rs = [], []
    for s in coins:
        rows = data[s]
        days = sorted(rows)
        w, r = [], []
        for i in range(1, len(days) - 1):
            t = days[i]
            if days[i - 1] != t - DAY or days[i + 1] != t + DAY or rows[days[i - 1]]["age"] < 120:
                continue
            row = rows[t - DAY]
            on = cta.signal(row, rule)
            w.append((row["dc"] if rule == "donchian" else 1.0) if on else 0.0)
            r.append(rows[t + DAY]["o"] / rows[t]["o"] - 1)
        ws.append(w)
        rs.append(r)
    return ws, rs


def luck_report(strategy_id: str, paths=None, registry=None, n_perm: int = N_PERM, record: bool = True, write: bool = True,
                now_ms: int | None = None, data=None) -> dict:
    """Run all nine tests for one strategy id; save var/reports/luck_<id>.json. `data` (tests) replaces the archive load."""
    from ..paths import Paths
    from ..swing import cta
    if strategy_id not in SPECS:
        raise KeyError(f"unknown strategy {strategy_id!r}; luck-testable ids: {sorted(SPECS)}")
    paths = paths or Paths.default()
    registry = Path(registry) if registry else paths.root / "trials.db"
    spec = SPECS[strategy_id]
    coins = spec["coins"] or cta.UNIVERSE
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    n_reg = trial_count(registry)
    th = thresholds(n_reg)
    data = data if data is not None else load_data(paths, spec["rule"])
    data_by_lb = {None: data}
    if spec["lb"] is not None:
        data_by_lb = {i: _with_lookbacks(data, lb) for i, lb in enumerate(LB_SETS)}
    base = base_config(spec)
    cfgs = grid_configs(spec)
    runs = {c: _run_config(data_by_lb, spec, c, coins) for c in cfgs}
    ser = runs[base]
    rets = [x[1] for x in ser]
    st = cta.stats(ser)
    tests = {}

    tests["T1_history"] = {"pass": len(rets) >= th["min_days"], "days": len(rets), "need": f">= {th['min_days']}"}

    grid_sr = {c: sharpe_period([x[1] for x in s]) for c, s in runs.items()}
    gm = sum(grid_sr.values()) / len(grid_sr)
    var_grid = sum((v - gm) ** 2 for v in grid_sr.values()) / (len(grid_sr) - 1)
    d = deflated_sharpe(rets, max(n_reg, len(cfgs)), var_grid)
    d.update({"pass": d["prob"] >= th["dsr_prob_min"], "need": f"prob >= {th['dsr_prob_min']}"})
    tests["T2_deflated_sharpe"] = d

    common = sorted(set.intersection(*[{x[0] for x in s} for s in runs.values()]))
    aligned = {}
    for c, s in runs.items():
        m = {x[0]: x[1] for x in s}
        aligned[str(c)] = [m[t] for t in common]
    p = pbo_cscv(aligned)
    p.update({"pass": p["pbo"] <= th["pbo_max"], "need": f"PBO <= {th['pbo_max']}"})
    tests["T3_pbo_cscv"] = p

    ws, rs = _timing_inputs(data, spec["rule"], coins)
    n = timing_null(ws, rs, n_perm=n_perm)
    n.update({"pass": n["p"] <= th["perm_p_max"], "need": f"p <= {th['perm_p_max']}"})
    tests["T4_timing_null"] = n

    neigh = []
    for c in neighbours(spec, base):
        s = cta.stats(runs[c])
        ok = s["cagr"] > 0 and s["sharpe"] >= NEIGHBOUR_SHARPE_FRAC * st["sharpe"]
        neigh.append({"cfg": str(c), "cagr": s["cagr"], "sharpe": s["sharpe"], "pass": ok})
    tests["T5_sensitivity"] = {"pass": bool(neigh) and all(x["pass"] for x in neigh), "base_sharpe": st["sharpe"],
                               "neighbours": neigh, "need": f"CAGR > 0 and Sharpe >= {NEIGHBOUR_SHARPE_FRAC} x base"}

    b = block_bootstrap(rets)
    b.update({"pass": b["mean_lower_bps"] > 0, "need": "2.5% lower bound of mean daily net return > 0"})
    tests["T6_block_bootstrap"] = b

    labels = regime_labels({t: r["c"] for t, r in data["BTC_USDT"].items()})
    by = {k: [] for k in REGIME_FLOOR_BPS}
    for t, r, *_ in ser:
        if t in labels:
            by[labels[t]].append(r)
    reg, ok = {}, True
    for k, floor in REGIME_FLOOR_BPS.items():
        xs = by[k]
        mean_bps = sum(xs) / len(xs) * 1e4 if xs else None
        good = len(xs) >= REGIME_MIN_DAYS and mean_bps >= floor
        reg[k] = {"days": len(xs), "mean_bps_per_day": mean_bps, "floor_bps": floor, "pass": good,
                  "total_return": math.prod(1 + x for x in xs) - 1 if xs else None}
        ok = ok and good
    tests["T7_regimes"] = {"pass": ok, "regimes": reg, "need": f">= {REGIME_MIN_DAYS} days and mean above the floor in each"}

    cs, ok = {}, True
    for mult, need in COST_BOUNDS.items():
        s = cta.stats(_run_config(data_by_lb, spec, base, coins, cost={k: mult * v for k, v in cta.COST.items()}))
        good = s["cagr"] > 0 and s["sharpe"] >= need
        cs[f"x{mult}"] = {"cagr": s["cagr"], "sharpe": s["sharpe"], "max_drawdown": s["max_drawdown"], "need_sharpe": need, "pass": good}
        ok = ok and good
    tests["T8_cost_stress"] = {"pass": ok, "runs": cs}

    cap = _run_config(data_by_lb, spec, base, coins, capital=MC_CAPITAL)
    mc = monte_carlo([x[1] for x in cap])
    mc.update({"pass": mc["p_lose_50pct"] <= MC_RUIN_MAX and mc["return_30d"]["p05"] >= MC_P05_MIN,
               "need": f"P(lose 50% in 30d) <= {MC_RUIN_MAX} and p05 30d return >= {MC_P05_MIN}",
               "capital_sim": {"cagr": cta.stats(cap)["cagr"], "avg_exposure": cta.stats(cap)["avg_exposure"]}})
    tests["T9_monte_carlo_100usd"] = mc

    body = {"strategy_id": strategy_id, "suite": SUITE, "at_ms": now_ms, "venue": "PROXY: Binance spot daily klines, not Pionex",
            "registry_count": n_reg, "level": th["level"], "thresholds": th, "thresholds_sha256": thresholds_sha(n_reg),
            "base_config": str(base), "base_stats": st, "grid_size": len(cfgs), "tests": tests,
            "failed": [k for k, v in tests.items() if not v["pass"]],
            "luck_eligible": all(v["pass"] for v in tests.values()),
            "note": "backtests are not proof of profit; the registry count is a lower bound"}
    if "regression" in spec:
        cagr, dd, sh = spec["regression"]
        body["regression_ok"] = abs(st["cagr"] - cagr) < 0.0006 and abs(st["max_drawdown"] - dd) < 0.0006 and abs(st["sharpe"] - sh) < 0.006
    body["sha256"] = _body_sha(body)
    if write:
        (paths.reports / f"luck_{strategy_id}.json").write_text(json.dumps(body, indent=1, default=str), encoding="utf-8")
    if record:
        for c, s in runs.items():
            record_trial(registry, "luck", f"{strategy_id}|{c}", strategy_id, {"cfg": str(c), "rule": spec["rule"]},
                         "2017-12..now PROXY", f"sharpe {cta.stats(s)['sharpe']:.2f}", 1, now_ms)
    return body


def _body_sha(body: dict) -> str:
    b = {k: v for k, v in body.items() if k != "sha256"}
    return hashlib.sha256(json.dumps(b, sort_keys=True, default=str).encode()).hexdigest()


def verify_report(var, gate_id: str, now_ms: int | None = None) -> tuple[bool, str]:
    """Used by live/gate.py. Fail-closed: (True, summary) only for an intact, current report in which every test
    passed; the tests are re-read one by one, the stored flag is not trusted. Stdlib only, reads var/reports and
    var/trials.db (the luck report is the one report file the gate is allowed to read)."""
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    sid = GATE_TO_LUCK.get(gate_id)
    if sid is None:
        return False, "no luck-testable backtest series for this strategy"
    f = Path(var) / "reports" / f"luck_{sid}.json"
    try:
        rep = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, f"no luck report luck_{sid}.json"
    if not isinstance(rep, dict) or rep.get("sha256") != _body_sha(rep):
        return False, "luck report altered or malformed (hash mismatch)"
    if rep.get("strategy_id") != sid or rep.get("suite") != SUITE:
        return False, "luck report is for another strategy or suite version"
    n = trial_count(Path(var) / "trials.db")
    if n <= 0:
        return False, "trial registry empty or missing"
    if rep.get("level") != level(n) or rep.get("thresholds_sha256") != thresholds_sha(rep.get("registry_count", -1)) \
            or thresholds_sha(n) != rep.get("thresholds_sha256"):
        return False, f"luck report is stale: registry grew to {n} trials, tightening level changed (re-run luck)"
    age_d = (now_ms - int(rep.get("at_ms", 0))) / DAY
    if not 0 <= age_d <= MAX_REPORT_AGE_DAYS:
        return False, f"luck report age {age_d:.1f} d (limit {MAX_REPORT_AGE_DAYS})"
    tests = rep.get("tests") or {}
    if len(tests) != 9:
        return False, "luck report incomplete"
    bad = [k for k, v in tests.items() if v.get("pass") is not True]
    if bad:
        return False, "luck tests failed: " + ", ".join(sorted(bad))
    return True, f"all 9 luck tests pass (N={rep['registry_count']})"


def render(rep: dict) -> str:
    lines = [f"Luck report {rep['strategy_id']} ({rep['suite']}), registry N={rep['registry_count']} level {rep['level']}"]
    for k, v in rep["tests"].items():
        lines.append(f"  {'PASS' if v['pass'] else 'FAIL'}  {k}")
    lines.append("LUCK-ELIGIBLE" if rep["luck_eligible"] else "NOT eligible: " + ", ".join(rep["failed"]))
    return "\n".join(lines)
