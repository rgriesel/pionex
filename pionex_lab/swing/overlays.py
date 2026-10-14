"""Risk overlays on the CTA trend basket v1.1 (research only: no order path; paper books and cta rules untouched).

PRE-REGISTERED 2026-10-14 10:04 SAST, before either test was run (nothing below changes after a result).
Two cards chosen by the lead from research/ideas/2026-10-14.md; one test per card, run once. Status of the
base: v1.1 is itself an in-sample backtest, so these are overlays on an in-sample base, on PROXY data
(Binance daily klines; Deribit DVOL). Not proof of profit.

Base (v1.1, unchanged, reproduced byte-identical with the new hook before testing: tsmom_vol "all" CAGR 35.8%,
max DD 26.3%, Sharpe 1.37): tsmom_vote signal, vol sizing (40%/N per coin / 30-day vol), 10 coins, 2% band,
100% gross cap, same costs, decisions on yesterday's close, fills at the 00:00 UTC open. An overlay is a
function (t, targets, data) -> factor in [0, 1] passed as cta.simulate(scale=...). All of the day's target
weights are multiplied by the factor after the gross cap and before the band: it only cuts exposure (never
adds leverage) and never changes the signals or lookbacks. It may read only bars keyed before day t.

CARD 1 - correlation-aware portfolio risk cap (CovCap). Forecast basket volatility
sigma_p = sqrt(w' S w), w = the day's target weights, S = sample covariance (n-1) of the coins' daily
close-to-close returns over the 60 days ending at yesterday's close, annualised x365.25 (listwise over the
coins in w; fewer than 40 common days -> no cap). Factor = min(1, CAP / sigma_p). Window 60 days (the card
says 30; 30 returns for a 10-coin covariance is noisy, and 60 is the lead's suggested window). CAP = 0.227
(22.7% a year), set by the card's own rule BEFORE this registration from forecasts only (no returns read):
the median pre-cap sigma_p over the 882 invested days of 2018-01-01..2020-12-31 was 22.707% (range 4.1%..74.3%),
rounded to 0.227. Reason: the basket's own typical risk in the years before the 2021 test period, so the cap
trims only the above-typical, high-correlation days. 2018-2020 is therefore in-sample for the cap (one number);
2021-on is untouched and reported separately. Window tested: 2017-12-16 .. 2026-10-11 (all v1.1 decision days).

CARD 2 - DVOL shock cap (DvolShock), rule exactly as on the card: on a decision day, if yesterday's Deribit
BTC DVOL (the close of the day's 23:00 hourly bar, known at 00:00 UTC; verified equal to Deribit's daily
close) is >= 1.25 x the median of the trailing 90 daily values (yesterday's included), multiply all targets by
0.5; otherwise 1. No hysteresis; fewer than 80 of the 90 values -> 1. Data: var/alpha/alt.db series dvol_1h,
backfilled 2026-10-14 from Deribit's public API back to 2021-03-24 (first day served); proxy_market.db not
touched. First day with 90 values: 2021-06-22, so the comparison window is 2021-06-22 .. 2026-10-11 (the overlay
cannot act before it; the May 2021 crash is outside). The 1.5x sensitivity run is not run.

PASS RULE (same shape for both cards; v1.1 on the identical window is the comparison; alpha 0.05 split over the
two tests -> one-sided 0.025). All must hold:
  1. Sharpe(overlay) > Sharpe(v1.1).
  2. Max drawdown lower by at least 3 percentage points (the cards' own materiality).
  3. Sharpe higher in at least 2 of the 3 equal-length thirds of the window.
  4. Versus the uniform de-risking control (v1.1 with its 40% target scaled by one factor so that its average
     exposure matches the overlay's; one shot, no search): the paired circular block bootstrap (10-day blocks,
     20,000 resamples, seed 20261014) one-sided 97.5% lower bound of mean daily (overlay - control) return is
     not below -10% of v1.1's mean daily return ("not clearly negative": timing must not be clearly worse than
     simply holding less).
  5. Episodes: the overlay changes the targets in at least 3 distinct episodes (runs of active days, merged when
     separated by fewer than 7 quiet days); fewer -> verdict INSUFFICIENT, not PASS.
Card 1 also (its card's falsifiers): 6. CAGR at least 90% of v1.1's. 7. Sharpe still higher at 4x costs.
Card 2 also (its card's falsifiers): 6. Sharpe still higher with 2022-05-01..2022-11-30 removed from both.
7. v1.1's mean next-7-day and next-30-day return after trigger days is below that after other days.
8. Sharpe above the median of 200 placebos that halve on the same trigger episodes shifted circularly by random
   offsets (seed 20261014).
Reported, not gating: the 2018-2020 / 2021-on split (card 1), the DVOL-start window (card 2), bootstrap of the
Sharpe difference, CAGR, drawdown, thirds, average exposure, turnover and days active. FAIL if any gate fails.
"""
from __future__ import annotations

import json
import math
import random
import statistics
from datetime import datetime, timezone

from . import cta
from .cta import DAY
from ..data import altdata

HOUR = 3_600_000
ANN = 365.25

# ---- fixed parameters (see the module docstring; nothing here is tuned after a result) --------------
COV_WINDOW = 60                 # card 1: trailing daily-return window for the covariance matrix
COV_MIN_OBS = 40                # card 1: fewer common return days than this -> no cap that day
CAP_CALIB_FROM, CAP_CALIB_TO = "2018-01-01", "2020-12-31"
CAP = 0.227                     # card 1: annualised basket-volatility cap = calibrate_cap() 22.707%, rounded
DVOL_MULT, DVOL_WINDOW, DVOL_MIN_VALUES, DVOL_FACTOR = 1.25, 90, 80, 0.5
BOOT_BLOCK, BOOT_N, BOOT_SEED, BOOT_Q = 10, 20_000, 20261014, 0.025     # alpha 0.05 / 2 tests, one-sided
PLACEBOS, PLACEBO_SEED = 200, 20261014
DD_POINTS = 0.03                # both cards: max drawdown must fall by at least 3 points
EPISODE_GAP_DAYS, MIN_EPISODES = 7, 3
CONTROL_TOLERANCE = 0.10        # bootstrap bound on (overlay - control) mean daily return >= -10% of v1.1's mean
RULE, SIZING = "tsmom_vote", "vol"


def _ms(y, m, d):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)


# ---- card 1: correlation-aware portfolio risk cap ---------------------------------------------------
def basket_vol(t, targets, data, window=COV_WINDOW, min_obs=COV_MIN_OBS):
    """Annualised forecast volatility sqrt(w' S w) of the target weights, with S the sample covariance (n-1)
    of daily close-to-close returns over the `window` days ending at yesterday's close (bars keyed < t only).
    A return day counts only if every coin in `targets` has both closes (listwise). 0.0 with no positions;
    None when fewer than `min_obs` common days exist."""
    coins = [s for s, w in targets.items() if w > 0]
    if not coins:
        return 0.0
    cols = []
    for k in range(1, window + 1):
        u = t - k * DAY                                   # return of day u: close(u) / close(u - 1 day) - 1
        row = []
        for s in coins:
            a, b = data[s].get(u), data[s].get(u - DAY)
            if a is None or b is None:
                row = None
                break
            row.append(a["c"] / b["c"] - 1)
        if row is not None:
            cols.append(row)
    n, k = len(cols), len(coins)
    if n < min_obs or n < 2:
        return None
    mu = [sum(r[i] for r in cols) / n for i in range(k)]
    cov = [[sum((r[i] - mu[i]) * (r[j] - mu[j]) for r in cols) / (n - 1) for j in range(k)] for i in range(k)]
    w = [targets[s] for s in coins]
    var = sum(w[i] * w[j] * cov[i][j] for i in range(k) for j in range(k))
    return math.sqrt(max(var, 0.0) * ANN)


class CovCap:
    """scale hook, card 1: factor = min(1, cap / forecast basket volatility). `log[t]` keeps what it saw."""

    def __init__(self, cap, window=COV_WINDOW, min_obs=COV_MIN_OBS):
        self.cap, self.window, self.min_obs, self.log = cap, window, min_obs, {}

    def __call__(self, t, targets, data):
        vol = basket_vol(t, targets, data, self.window, self.min_obs)
        f = 1.0 if vol is None or vol <= 0 else min(1.0, self.cap / vol)
        self.log[t] = {"forecast": vol, "factor": f, "invested": bool(targets), "active": bool(targets) and f < 1 - 1e-12}
        return f


def calibrate_cap(data, window=COV_WINDOW):
    """Card 1 cap: the median pre-cap forecast basket volatility over the invested days of 2018-01-01..2020-12-31
    (the card's own rule). Uses forecasts only (a no-op recorder with cap = infinity); no returns are read."""
    rec = CovCap(math.inf, window)
    cta.simulate(data, RULE, SIZING, 0, scale=rec)
    lo = _ms(*map(int, CAP_CALIB_FROM.split("-")))
    hi = _ms(*map(int, CAP_CALIB_TO.split("-")))
    xs = [v["forecast"] for t, v in rec.log.items() if lo <= t <= hi and v["forecast"]]
    return {"cap": statistics.median(xs), "n_days": len(xs), "min": min(xs), "max": max(xs)}


# ---- card 2: Deribit DVOL shock cap ------------------------------------------------------------------
def load_dvol_daily(alt_db):
    """{UTC day start ms: DVOL at the end of that day}, from the hourly series: the close of the 23:00 bar
    (stamped at the bar start; verified equal to Deribit's own daily close). A day is known only from the
    next 00:00 UTC. Days without a 23:00 bar (the current, unfinished day) are left out."""
    return {t - 23 * HOUR: v for t, v in altdata.series(alt_db, "dvol_1h") if t % DAY == 23 * HOUR}


class DvolShock:
    """scale hook, card 2: factor 0.5 when yesterday's DVOL >= 1.25 x the median of the trailing 90 daily
    values (including yesterday's), else 1. `daily` is {day start: value}; the value of day u is used from
    decision day u + 1 on. No hysteresis; fewer than 80 of the 90 values -> factor 1."""

    def __init__(self, daily, mult=DVOL_MULT, window=DVOL_WINDOW, min_values=DVOL_MIN_VALUES, factor=DVOL_FACTOR):
        self.daily, self.mult, self.window, self.min_values, self.factor, self.log = daily, mult, window, min_values, factor, {}

    def state(self, t):
        u = t - DAY
        vals = [self.daily[d] for d in (u - k * DAY for k in range(self.window)) if d in self.daily]
        if u not in self.daily or len(vals) < self.min_values:
            return None
        return self.daily[u], statistics.median(vals)

    def __call__(self, t, targets, data):
        st = self.state(t)
        trig = st is not None and st[0] >= self.mult * st[1]
        f = self.factor if trig else 1.0
        self.log[t] = {"dvol": st[0] if st else None, "median90": st[1] if st else None, "trigger": trig, "factor": f,
                       "invested": bool(targets), "active": bool(targets) and trig}
        return f


class MaskScale:
    """Placebo hook: the same halving on the days in `days` (a set of decision-day starts)."""

    def __init__(self, days, factor=DVOL_FACTOR):
        self.days, self.factor = days, factor

    def __call__(self, t, targets, data):
        return self.factor if t in self.days else 1.0


# ---- statistics --------------------------------------------------------------------------------------
def _sharpe(xs):
    m = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))
    return m / sd * math.sqrt(ANN) if sd else 0.0


def paired_block_bootstrap(a, b, block=BOOT_BLOCK, resamples=BOOT_N, seed=BOOT_SEED, q=BOOT_Q):
    """Circular block bootstrap of day indices, the same blocks for both aligned daily-return lists. Returns
    the q-quantile (lower bound), median and (1-q)-quantile of mean(a - b) and of Sharpe(a) - Sharpe(b)."""
    n = len(a)
    assert n == len(b) and n >= 2 * block
    nb = math.ceil(n / block)
    big = nb * block

    def prefix(xs):
        p = [0.0]
        for x in xs + xs:
            p.append(p[-1] + x)
        return p
    pd, pa, pa2, pb, pb2 = (prefix([x - y for x, y in zip(a, b)]), prefix(a), prefix([x * x for x in a]),
                            prefix(b), prefix([x * x for x in b]))
    rng = random.Random(seed)
    md, sd_ = [], []
    for _ in range(resamples):
        sd = sa = sa2 = sb = sb2 = 0.0
        for _k in range(nb):
            s = rng.randrange(n)
            e = s + block
            sd += pd[e] - pd[s]
            sa += pa[e] - pa[s]
            sa2 += pa2[e] - pa2[s]
            sb += pb[e] - pb[s]
            sb2 += pb2[e] - pb2[s]
        ma, mb = sa / big, sb / big
        va, vb = max(sa2 / big - ma * ma, 0.0), max(sb2 / big - mb * mb, 0.0)
        sha = ma / math.sqrt(va) * math.sqrt(ANN) if va else 0.0
        shb = mb / math.sqrt(vb) * math.sqrt(ANN) if vb else 0.0
        md.append(sd / big)
        sd_.append(sha - shb)

    def summ(xs):
        xs.sort()
        k = len(xs)
        return {"lower": xs[int(math.floor(q * k))], "median": xs[k // 2], "upper": xs[min(k - 1, int(math.floor((1 - q) * k)))],
                "share_positive": sum(1 for x in xs if x > 0) / k}
    return {"mean_diff": summ(md), "sharpe_diff": summ(sd_), "block_days": block, "resamples": resamples, "q": q}


def episodes(days, gap_days=EPISODE_GAP_DAYS):
    """Number of distinct episodes among decision days: runs separated by fewer than `gap_days` quiet days merge."""
    n, last = 0, None
    for t in sorted(days):
        if last is None or (t - last) // DAY - 1 >= gap_days:
            n += 1
        last = t
    return n


def _same_days(*series):
    ref = [x[0] for x in series[0]]
    for s in series[1:]:
        if [x[0] for x in s] != ref:
            raise AssertionError("series cover different days")
    return ref


def _compare(base, ov, ctrl):
    """Gate inputs shared by both cards, all on identical days."""
    _same_days(base, ov, ctrl)
    sb, so, sc = cta.stats(base), cta.stats(ov), cta.stats(ctrl)
    rb, ro, rc = [x[1] for x in base], [x[1] for x in ov], [x[1] for x in ctrl]
    boot = paired_block_bootstrap(ro, rc)
    boot["tolerance_daily"] = CONTROL_TOLERANCE * (sum(rb) / len(rb))
    boot["vs_base_sharpe_diff"] = paired_block_bootstrap(ro, rb)["sharpe_diff"]
    return {"v11": sb, "overlay": so, "control_uniform": sc, "bootstrap_vs_control": boot,
            "thirds_sharpe_higher": sum(x > y for x, y in zip(so["sharpe_thirds"], sb["sharpe_thirds"])),
            "max_dd_cut_points": 100 * (sb["max_drawdown"] - so["max_drawdown"]),
            "cagr_ratio": so["cagr"] / sb["cagr"] if sb["cagr"] else None}


def _control(data, start_ms, base_stats, ov_stats):
    """v1.1 with its 40% target lowered uniformly so the average exposure matches the overlay (one shot)."""
    k = ov_stats["avg_exposure"] / base_stats["avg_exposure"]
    return k, cta.simulate(data, RULE, SIZING, start_ms, target=0.40 * k)


def _verdict(gates, episodes_n):
    if episodes_n < MIN_EPISODES:
        return "INSUFFICIENT"
    return "PASS" if all(gates.values()) else "FAIL"


def _gates_common(c):
    b = c["bootstrap_vs_control"]
    return {"sharpe_higher": c["overlay"]["sharpe"] > c["v11"]["sharpe"],
            "max_dd_down_3_points": c["max_dd_cut_points"] >= 100 * DD_POINTS - 1e-9,
            "sharpe_higher_in_2_of_3_thirds": c["thirds_sharpe_higher"] >= 2,
            "bootstrap_vs_uniform_control_not_clearly_negative": b["mean_diff"]["lower"] >= -b["tolerance_daily"]}


# ---- the two tests ------------------------------------------------------------------------------------
def evaluate_card1(data, cap):
    """Card 1 on the full v1.1 window (2017-12-16 on)."""
    costs4 = {s: 4 * v for s, v in cta.COST.items()}
    base = cta.simulate(data, RULE, SIZING, 0)
    hook = CovCap(cap)
    ov = cta.simulate(data, RULE, SIZING, 0, scale=hook)
    k, ctrl = _control(data, 0, cta.stats(base), cta.stats(ov))
    out = _compare(base, ov, ctrl)
    out["control_target_scale"] = k
    act = [t for t in (x[0] for x in ov) if hook.log.get(t, {}).get("active")]
    inv = [t for t in (x[0] for x in ov) if hook.log.get(t, {}).get("invested")]
    fac = [hook.log[t]["factor"] for t in inv]
    out["activity"] = {"decision_days": len(ov), "invested_days": len(inv), "active_days": len(act),
                       "active_share_of_invested": len(act) / len(inv) if inv else None,
                       "mean_factor_on_invested_days": sum(fac) / len(fac) if fac else None,
                       "episodes": episodes(act), "min_factor": min(fac) if fac else None}
    b4 = cta.stats(cta.simulate(data, RULE, SIZING, 0, cost=costs4))
    o4 = cta.stats(cta.simulate(data, RULE, SIZING, 0, cost=costs4, scale=CovCap(cap)))
    sp = _ms(2021, 1, 1)
    sub = {}
    for name, sel in (("2018_2020_cap_calibration_window", lambda t: t < sp), ("2021_on_cap_untouched", lambda t: t >= sp)):
        sub[name] = {"v11": cta.stats([x for x in base if sel(x[0])]), "overlay": cta.stats([x for x in ov if sel(x[0])])}
    out["diagnostics"] = {"costs_4x": {"v11": b4, "overlay": o4}, "subperiods": sub}
    g = _gates_common(out)
    g["cagr_loss_at_most_10pct_relative"] = out["cagr_ratio"] >= 0.90
    g["sharpe_higher_at_4x_costs"] = o4["sharpe"] > b4["sharpe"]
    out["gates"] = g
    out["verdict"] = _verdict(g, out["activity"]["episodes"])
    return out


def evaluate_card2(data, daily):
    """Card 2 from the first day the 90-day median exists (first DVOL day + 90 days)."""
    t0 = min(daily) + DVOL_WINDOW * DAY
    base = cta.simulate(data, RULE, SIZING, t0)
    hook = DvolShock(daily)
    ov = cta.simulate(data, RULE, SIZING, t0, scale=hook)
    k, ctrl = _control(data, t0, cta.stats(base), cta.stats(ov))
    out = _compare(base, ov, ctrl)
    out["control_target_scale"] = k
    days = [x[0] for x in ov]
    trig = [t for t in days if hook.log.get(t, {}).get("trigger")]
    act = [t for t in days if hook.log.get(t, {}).get("active")]
    inv = [t for t in days if hook.log.get(t, {}).get("invested")]
    out["activity"] = {"window_from": datetime.fromtimestamp(t0 / 1000, timezone.utc).date().isoformat(),
                       "decision_days": len(days), "trigger_days": len(trig), "invested_days": len(inv),
                       "active_days": len(act), "trigger_episodes": episodes(trig), "episodes": episodes(act)}
    # card falsifier: mean next-7d / next-30d basket return after trigger days vs the other days
    rb = [x[1] for x in base]
    tset = set(trig)
    fwd = {}
    for h in (7, 30):
        a, o = [], []
        for i, t in enumerate(days[:len(days) - h + 1]):
            r = math.prod(1 + x for x in rb[i:i + h]) - 1
            (a if t in tset else o).append(r)
        fwd[f"next_{h}d"] = {"after_trigger_days": sum(a) / len(a) if a else None, "n_trigger": len(a),
                             "after_other_days": sum(o) / len(o) if o else None, "n_other": len(o)}
    out["forward_returns_v11"] = fwd
    # card falsifier: all of the benefit from May-Nov 2022
    lo, hi = _ms(2022, 5, 1), _ms(2022, 11, 30)
    keep = [i for i, t in enumerate(days) if not lo <= t <= hi]
    ro = [x[1] for x in ov]
    out["ex_2022_05_to_11"] = {"v11_sharpe": _sharpe([rb[i] for i in keep]), "overlay_sharpe": _sharpe([ro[i] for i in keep]),
                               "days": len(keep)}
    # card falsifier: Sharpe below a control that halves on the same episodes placed at random (circular shifts)
    mask = [t in tset for t in days]
    n = len(days)
    rng = random.Random(PLACEBO_SEED)
    plac = []
    for _ in range(PLACEBOS):
        s = rng.randrange(n // 10, n - n // 10)
        plac.append(cta.stats(cta.simulate(data, RULE, SIZING, t0, scale=MaskScale(
            {days[i] for i in range(n) if mask[(i - s) % n]})))["sharpe"])
    plac.sort()
    so = out["overlay"]["sharpe"]
    out["placebo"] = {"n": PLACEBOS, "median_sharpe": plac[len(plac) // 2], "p10": plac[len(plac) // 10],
                      "p90": plac[len(plac) * 9 // 10], "overlay_percentile": sum(1 for x in plac if x < so) / len(plac)}
    # diagnostics: 4x costs; the longer window that starts when DVOL starts (overlay idle until t0)
    costs4 = {s: 4 * v for s, v in cta.COST.items()}
    out["diagnostics"] = {
        "costs_4x": {"v11": cta.stats(cta.simulate(data, RULE, SIZING, t0, cost=costs4)),
                     "overlay": cta.stats(cta.simulate(data, RULE, SIZING, t0, cost=costs4, scale=DvolShock(daily)))},
        "from_dvol_start_overlay_idle_until_t0": {
            "v11": cta.stats(cta.simulate(data, RULE, SIZING, min(daily) + DAY)),
            "overlay": cta.stats(cta.simulate(data, RULE, SIZING, min(daily) + DAY, scale=DvolShock(daily)))}}
    g = _gates_common(out)
    g["sharpe_higher_ex_2022_05_to_11"] = out["ex_2022_05_to_11"]["overlay_sharpe"] > out["ex_2022_05_to_11"]["v11_sharpe"]
    g["v11_return_lower_after_trigger_days_7d_and_30d"] = all(
        fwd[k]["after_trigger_days"] is not None and fwd[k]["after_trigger_days"] < fwd[k]["after_other_days"] for k in fwd)
    g["sharpe_above_placebo_median"] = so > out["placebo"]["median_sharpe"]
    out["gates"] = g
    out["verdict"] = _verdict(g, out["activity"]["episodes"])
    return out


def run(paths, alt_db=None, write=True):
    """Run both pre-registered tests once and save var/reports/cta_overlays.json."""
    data = cta.load(paths)
    alt_db = alt_db or paths.root / "alpha" / "alt.db"
    daily = load_dvol_daily(alt_db)
    rep = {"preregistered": "see the module docstring (pionex_lab/swing/overlays.py)",
           "status": "backtest on PROXY data (Binance daily klines, Deribit DVOL); overlays on the in-sample CTA v1.1; "
                     "not proof of profit; red team pending",
           "parameters": {"cov_window": COV_WINDOW, "cap": CAP, "dvol_mult": DVOL_MULT, "dvol_window": DVOL_WINDOW,
                          "dvol_factor": DVOL_FACTOR, "bootstrap": {"block_days": BOOT_BLOCK, "resamples": BOOT_N, "q": BOOT_Q},
                          "dd_points": DD_POINTS, "control_tolerance": CONTROL_TOLERANCE},
           "dvol_days": {"n": len(daily), "first": datetime.fromtimestamp(min(daily) / 1000, timezone.utc).date().isoformat(),
                         "last": datetime.fromtimestamp(max(daily) / 1000, timezone.utc).date().isoformat()}}
    rep["card1_cov_cap"] = evaluate_card1(data, CAP)
    rep["card2_dvol_shock"] = evaluate_card2(data, daily)
    if write:
        (paths.reports / "cta_overlays.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return rep
