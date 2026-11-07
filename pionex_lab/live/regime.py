"""Regime watch (CLO-45, "adapt or die"): classify the market from LIVE Pionex data every 5 minutes.
RESEARCH/MONITOR ONLY: public endpoints, no keys, no orders. It can open a research issue and write a human cache; it
can never trade, and every consumer recomputes from live data (var/regime.json is a cache for humans, never read back
as an input to a decision; var/regime_state.json holds only the label-change debounce counters).

FROZEN 2026-10-17 18:08 SAST (machine clock), before any run or backtest. A changed threshold is a new version.
Features (daily bars = completed Pionex 1D klines only, newest = previous UTC day; hourly = completed 60M klines):
  vol_ratio   = realised vol of the last VOL_SHORT (14) daily log returns / that of the last VOL_LONG (90); BTC and ETH,
                the label uses the larger ratio. Also reported: vol 30d and its position vs the 90d history.
  trend_t     = (close/close[-30] - 1) / (sd of 30 daily returns * sqrt(30))   (return per unit of vol; BTC)
  ret_24h     = BTC close of the last completed hour / close 24 hours earlier - 1
  dd_7d       = 1 - BTC last daily close / max daily close of the last 7 days
  corr        = mean pairwise correlation of 30 daily returns across the 10-coin CTA universe
  spread_bps, depth_usdt = BTC and ETH best bid/ask spread and USDT value of the top-20 levels each side (quote <= 5 s old)
  funding     = not available: the lab's Pionex client has no perpetual funding endpoint; reported as null, never guessed.
Labels, first match wins (priority order):
  crash     ret_24h <= -8%  or  dd_7d >= 15%
  high-vol  vol_ratio >= 1.5
  bull      trend_t >= +1.0
  bear      trend_t <= -1.0
  low-vol   vol_ratio <= 0.6   (and |trend_t| < 1)
  sideways  otherwise
  unknown   any required series missing or stale (a stale feed is never classified; critical notice is the caller's)
Flags (not labels): corr_high (corr >= 0.85), liquidity_thin (spread > 10 bps or depth < 50,000 USDT on BTC or ETH).
Debounce (so one noisy week or print cannot flip the firm): a new label becomes CONFIRMED only after CONFIRM_N (3)
consecutive 5-minute checks agree (crash confirms after 1: protective only), and a research issue is opened at most once
per ISSUE_GAP_H (24 h).
Backtest (pionex_lab/swing/adapt_test.py) uses the same classify() on daily-bar features (ret_24h = previous day's return).
"""
from __future__ import annotations

import json
import logging
import math
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import fresh

log = logging.getLogger("regime")

DAY_MS = 86_400_000
HOUR_MS = 3_600_000
VOL_SHORT, VOL_LONG, TREND_N, CORR_N = 14, 90, 30, 30
CRASH_RET24, CRASH_DD7 = -0.08, 0.15
HIGH_VOL, LOW_VOL = 1.5, 0.6
TREND_T = 1.0
CORR_HIGH = 0.85
SPREAD_MAX_BPS, DEPTH_MIN_USDT = 10.0, 50_000.0
QUOTE_MAX_AGE_MS = 5_000
CONFIRM_N = 3
ISSUE_GAP_H = 24.0
LABELS = ("bull", "bear", "sideways", "crash", "high-vol", "low-vol")
PAPERCLIP_API = "http://127.0.0.1:3100/api"


# ------------------------------------------------------------------ pure features
def _logrets(closes):
    return [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]


def _sd(xs):
    if len(xs) < 2:
        return float("nan")
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def vol_ratio(closes):
    """14-day / 90-day realised vol of daily closes (oldest first); None if fewer than 91 closes or zero long vol."""
    if len(closes) < VOL_LONG + 1:
        return None
    r = _logrets(closes)
    lo = _sd(r[-VOL_LONG:])
    return None if not lo or lo != lo else _sd(r[-VOL_SHORT:]) / lo


def trend_t(closes):
    """30-day return divided by (30-day daily sd * sqrt(30)); None if too short or flat."""
    if len(closes) < TREND_N + 1:
        return None
    sd = _sd(_logrets(closes)[-TREND_N:])
    if not sd or sd != sd:
        return None
    return (closes[-1] / closes[-TREND_N - 1] - 1) / (sd * math.sqrt(TREND_N))


def dd_7d(closes):
    return None if len(closes) < 7 else 1 - closes[-1] / max(closes[-7:])


def mean_corr(series):
    """Mean pairwise Pearson correlation of the last CORR_N log returns; series = list of close lists, equal length
    ends (aligned by position from the newest). None if fewer than 2 usable series."""
    rs = [_logrets(s)[-CORR_N:] for s in series if len(s) >= CORR_N + 1]
    n = min((len(r) for r in rs), default=0)
    rs = [r[-n:] for r in rs]
    if len(rs) < 2 or n < 10:
        return None
    cs = []
    for i in range(len(rs)):
        for j in range(i + 1, len(rs)):
            a, b = rs[i], rs[j]
            ma, mb = sum(a) / n, sum(b) / n
            va = sum((x - ma) ** 2 for x in a)
            vb = sum((y - mb) ** 2 for y in b)
            if va > 0 and vb > 0:
                cs.append(sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb))
    return sum(cs) / len(cs) if cs else None


def classify(vol_r, trend, ret24, dd7):
    """-> label. Any None input that the rule needs makes the result 'unknown' (never a guess)."""
    if ret24 is None or dd7 is None or vol_r is None or trend is None:
        return "unknown"
    if ret24 <= CRASH_RET24 or dd7 >= CRASH_DD7:
        return "crash"
    if vol_r >= HIGH_VOL:
        return "high-vol"
    if trend >= TREND_T:
        return "bull"
    if trend <= -TREND_T:
        return "bear"
    if vol_r <= LOW_VOL:
        return "low-vol"
    return "sideways"


def label_from_daily(btc_closes, eth_closes=None):
    """Daily-bar version used by the backtest and by the live path: closes oldest-first, last = last completed day.
    ret_24h is the last day's return here (the live path passes the hourly 24 h return instead)."""
    vr = [v for v in (vol_ratio(btc_closes), vol_ratio(eth_closes) if eth_closes else None) if v is not None]
    ret24 = btc_closes[-1] / btc_closes[-2] - 1 if len(btc_closes) >= 2 else None
    return classify(max(vr) if vr else None, trend_t(btc_closes), ret24, dd_7d(btc_closes))


# ------------------------------------------------------------------ live snapshot
class Stale(Exception):
    pass


def _closed_closes(klines, interval_ms, now_ms, max_lag_bars):
    """Close prices of completed bars, oldest first. Raises Stale if the newest completed bar is too old."""
    bars = sorted((k for k in klines if k.open_time + interval_ms <= now_ms), key=lambda k: k.open_time)
    if not bars:
        raise Stale("no completed bars")
    if now_ms - (bars[-1].open_time + interval_ms) > max_lag_bars * interval_ms:
        raise Stale("newest completed bar is too old")
    return [float(k.close) for k in bars]


def snapshot(client, coins, now_ms=None):
    """Fetch live Pionex data and classify. Raises Stale/ExchangeError on missing or stale data (caller -> 'unknown')."""
    live = now_ms is None                       # live: re-read the clock when each quote arrives (the klines take seconds)
    now_ms = now_ms or int(time.time() * 1000)
    daily = {}
    for s in coins:
        ks, _ = client.klines(s, "1D", limit=120)
        daily[s] = _closed_closes(ks, DAY_MS, now_ms, 1)
    hk, _ = client.klines("BTC_USDT", "60M", limit=48)
    hourly = _closed_closes(hk, HOUR_MS, now_ms, 2)
    if len(hourly) < 25:
        raise Stale("fewer than 25 hourly bars")
    ret24 = hourly[-1] / hourly[-25] - 1
    btc, eth = daily["BTC_USDT"], daily["ETH_USDT"]
    vr = [v for v in (vol_ratio(btc), vol_ratio(eth)) if v is not None]
    micro = {}
    for s in ("BTC_USDT", "ETH_USDT"):
        bt, env = client.book_ticker(s)
        try:
            fresh.stamp(bt, "quote", env, bt.exchange_ts).require(int(time.time() * 1000) if live else now_ms)     # quotes <= 5 s, FIRM_RULES freshness
        except fresh.StaleData as exc:
            raise Stale(f"{s}: {exc}") from exc
        d, _ = client.depth(s, 20)
        mid = float(bt.mid)
        micro[s] = {"spread_bps": (float(bt.ask) - float(bt.bid)) / mid * 1e4,
                    "depth_usdt": sum(float(p) * float(q) for p, q in list(d.bids) + list(d.asks))}
    corr = mean_corr(list(daily.values()))
    tt, d7 = trend_t(btc), dd_7d(btc)
    label = classify(max(vr) if vr else None, tt, ret24, d7)
    thin = any(m["spread_bps"] > SPREAD_MAX_BPS or m["depth_usdt"] < DEPTH_MIN_USDT for m in micro.values())
    sd30 = _sd(_logrets(btc)[-30:])
    return {"at_ms": now_ms, "label": label, "source": "Pionex live public API",
            "features": {"vol_ratio": max(vr) if vr else None, "vol_30d_ann": sd30 * math.sqrt(365.25) if sd30 == sd30 else None,
                         "trend_t": tt, "ret_24h": ret24, "dd_7d": d7, "corr": corr, "funding": None},
            "micro": micro, "flags": {"corr_high": corr is not None and corr >= CORR_HIGH, "liquidity_thin": thin},
            "thresholds": {"crash_ret24": CRASH_RET24, "crash_dd7": CRASH_DD7, "high_vol": HIGH_VOL, "low_vol": LOW_VOL,
                           "trend_t": TREND_T}}


# ------------------------------------------------------------------ debounce + issue
def debounce(state: dict, label: str, now_ms: int):
    """-> (confirmed_label, changed). state is mutated: {label, pending, count, last_issue_ms}."""
    cur = state.get("label")
    if label == "unknown":                       # no data: keep the confirmed label, reset the pending run
        state["pending"], state["count"] = None, 0
        return cur, False
    if cur is None:
        state["label"] = label
        return label, False                      # first observation is a baseline, not a change
    if label == cur:
        state["pending"], state["count"] = None, 0
        return cur, False
    if state.get("pending") == label:
        state["count"] = state.get("count", 0) + 1
    else:
        state["pending"], state["count"] = label, 1
    need = 1 if label == "crash" else CONFIRM_N
    if state["count"] >= need:
        state["label"], state["pending"], state["count"] = label, None, 0
        return label, True
    return cur, False


def open_research_issue(old: str, new: str, snap: dict, post=None, ids_path=None) -> bool:
    """Open a Paperclip issue for the Quant: re-test the candidate set on the latest regime window by the
    pre-registered walk-forward procedure. Best effort; returns True when posted. `post(path, body)` is injectable."""
    ids_path = Path(ids_path or Path(__file__).resolve().parents[2] / "var" / "paperclip_ids.json")
    try:
        ids = json.loads(ids_path.read_text(encoding="utf-8"))
        cid, quant, ceo = ids["company"], ids["agents"]["Quant"], ids["agents"]["CEO"]
    except (OSError, ValueError, KeyError):
        return False
    f = snap.get("features", {})
    body = {"title": f"Regime change: {old} -> {new}",
            "description": (f"Regime watch confirmed a regime change {old} -> {new} on live Pionex data at "
                            f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(snap['at_ms'] / 1000))} SAST.\n\n"
                            f"Features: {json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in f.items()})}\n\n"
                            "Task (Quant): re-test the candidate set on the most recent window of the NEW regime with the "
                            "pre-registered walk-forward procedure (docs/STRATEGY_LOG.md, FIRM_RULES 'Adapt or die'). "
                            "No tuning on the latest week; every variant counts in the trial registry. Report the table to "
                            "the CEO (routine 'Regime change review'). A strategy re-enters only through the full gate."),
            "priority": "high", "assigneeAgentId": quant, "parentId": None, "reviewerAgentId": ceo}
    body = {k: v for k, v in body.items() if v is not None and k != "reviewerAgentId"}
    try:
        if post is not None:
            post(f"/companies/{cid}/issues", body)
        else:
            req = urllib.request.Request(f"{PAPERCLIP_API}/companies/{cid}/issues", data=json.dumps(body).encode(),
                                         method="POST", headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=20).read()
        return True
    except (urllib.error.URLError, OSError, ValueError):
        log.warning("could not open the regime-change issue")
        return False


def step(client, var: Path, coins, now_ms=None, post=None, notify=None) -> dict:
    """One 5-minute check: live snapshot -> debounce -> human cache -> (on a confirmed change) issue + notice."""
    var = Path(var)
    arg_ms = now_ms
    now_ms = now_ms or int(time.time() * 1000)
    sp = var / "regime_state.json"
    try:
        state = json.loads(sp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    try:
        snap = snapshot(client, coins, arg_ms)
    except Stale as exc:
        snap = {"at_ms": now_ms, "label": "unknown", "error": str(exc), "features": {}}
        if notify:
            notify(f"Regime watch: live Pionex data stale or missing ({str(exc)[:80]}); no regime call made.", "critical",
                   "regime-stale")
    confirmed, changed = debounce(state, snap["label"], now_ms)
    snap["confirmed_label"], snap["changed"] = confirmed, changed
    if changed:
        old = state.get("prev_label") or "?"
        gap_ok = (now_ms - state.get("last_issue_ms", 0)) >= ISSUE_GAP_H * HOUR_MS
        snap["issue_opened"] = bool(gap_ok and open_research_issue(state.get("prev_label") or "?", confirmed, snap, post))
        if snap["issue_opened"]:
            state["last_issue_ms"] = now_ms
        if notify:
            notify(f"Regime change confirmed: {old} -> {confirmed}. Research re-test "
                   f"{'requested' if snap['issue_opened'] else 'not opened (cooldown or Paperclip unreachable)'}.",
                   "important", f"regime-{confirmed}")
    if confirmed:
        state["prev_label"] = confirmed
    (var).mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(state), encoding="utf-8")
    (var / "regime.json").write_text(json.dumps(snap, indent=1, default=str), encoding="utf-8")   # cache for humans
    return snap


def run(paths, stop, once=False, client=None, period_s=300.0, dd_limit=0.30, health_every_s=3600.0):
    from ..exchange.pionex_public import ExchangeError, PionexPublic
    from ..notify import notify as _notify
    from ..swing.cta import UNIVERSE
    paths.ensure()
    client = client or PionexPublic()

    def notify(text, level, key):
        try:
            _notify(paths.root, text, level=level, key=key)
        except Exception:
            pass
    last_health = 0.0
    while not stop.is_set():
        if time.time() - last_health >= health_every_s:                   # hourly strategy-health pass (stop-only)
            last_health = time.time()
            try:
                from . import health
                for r in health.watch(paths.root, dd_limit, notify=notify):
                    if r["drift"]:
                        log.warning("DRIFT %s: %s", r["strategy_id"], r["reasons"])
            except Exception:
                log.exception("health pass failed")
        try:
            snap = step(client, paths.root, UNIVERSE, notify=notify)
            log.info("regime %s (confirmed %s)", snap["label"], snap.get("confirmed_label"))
        except ExchangeError as exc:
            log.warning("regime check failed: %s", exc)
        except Exception:
            log.exception("unexpected error")
        if once:
            return 0
        stop.wait(period_s)
    return 0
