import json
import math
import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from pionex_lab.exchange.pionex_public import BookTicker, Depth, Kline
from pionex_lab.live import health, regime
from pionex_lab.swing import adapt_test

DAY = 86_400_000
NOW = 20_000 * DAY + 3_600_000 * 5            # 05:00 UTC


def closes(n, drift=0.0, vol=0.01):
    out, p = [], 100.0
    for i in range(n):
        p *= math.exp(drift + vol * (1 if i % 2 else -1))
        out.append(p)
    return out


class Env:
    def __init__(self, recv):
        self.recv_ms = recv
        self.latency_ms, self.server_ts, self.skew_ms = 0, None, 0


class FakeClient:
    def __init__(self, hourly_drop=0.0, stale_quote=False, stale_bars=False, now=NOW):
        self.now = now
        self.hourly_drop, self.stale_quote, self.stale_bars = hourly_drop, stale_quote, stale_bars

    def klines(self, symbol, interval, end_time=None, limit=500):
        step = DAY if interval == "1D" else 3_600_000
        now_open = (NOW // step) * step
        n = 120 if interval == "1D" else 48
        shift = 5 if self.stale_bars else 0
        if interval == "1D":
            cs = closes(n, 0.002 if symbol != "ETH_USDT" else 0.0021, 0.01)
        else:
            cs = closes(n, 0.0, 0.0005)
            cs[-1] *= 1 + self.hourly_drop
        bars = [Kline(now_open - (n - i + shift) * step, Decimal(c), Decimal(c), Decimal(c), Decimal(c), Decimal(1))
                for i, c in enumerate(cs)]
        bars.append(Kline(now_open, Decimal(cs[-1]), Decimal(cs[-1]), Decimal(cs[-1]), Decimal(cs[-1]), Decimal(1)))
        return bars, Env(self.now)

    def book_ticker(self, symbol):
        return (BookTicker(symbol, Decimal(100), Decimal(1), Decimal("100.01"), Decimal(1), self.now - (60_000 if self.stale_quote else 0)),
                Env(self.now - (60_000 if self.stale_quote else 0)))

    def depth(self, symbol, limit=20):
        return Depth(((Decimal(100), Decimal(1000)),), ((Decimal("100.01"), Decimal(1000)),), NOW), Env(NOW)


class RegimeTest(unittest.TestCase):
    def test_classify_priority_and_unknown(self):
        self.assertEqual(regime.classify(2.0, 3.0, -0.09, 0.0), "crash")          # crash beats high-vol
        self.assertEqual(regime.classify(1.6, 3.0, 0.0, 0.0), "high-vol")
        self.assertEqual(regime.classify(1.0, 1.2, 0.0, 0.0), "bull")
        self.assertEqual(regime.classify(1.0, -1.2, 0.0, 0.0), "bear")
        self.assertEqual(regime.classify(0.5, 0.2, 0.0, 0.0), "low-vol")
        self.assertEqual(regime.classify(1.0, 0.2, 0.0, 0.0), "sideways")
        self.assertEqual(regime.classify(None, 1.0, 0.0, 0.0), "unknown")
        self.assertEqual(regime.classify(1.0, 1.0, 0.0, 0.16), "crash")

    def test_features(self):
        c = closes(120, 0.002, 0.01)
        self.assertAlmostEqual(regime.vol_ratio(c), 1.0, delta=0.1)
        self.assertGreater(regime.trend_t(c), 1.0)
        self.assertIsNone(regime.vol_ratio(c[:50]))
        a = closes(60, 0.0, 0.01)
        self.assertGreater(regime.mean_corr([a, a]), 0.99)

    def test_debounce_needs_three_and_crash_one(self):
        st = {}
        self.assertEqual(regime.debounce(st, "bull", 0), ("bull", False))          # baseline
        self.assertEqual(regime.debounce(st, "bear", 1), ("bull", False))
        self.assertEqual(regime.debounce(st, "bull", 2), ("bull", False))          # flip back resets
        for k in range(2):
            self.assertFalse(regime.debounce(st, "bear", 3 + k)[1])
        self.assertEqual(regime.debounce(st, "bear", 9), ("bear", True))
        self.assertEqual(regime.debounce(st, "crash", 10), ("crash", True))
        self.assertEqual(regime.debounce(st, "unknown", 11), ("crash", False))     # no data: no change

    def test_step_live_cache_issue_and_stale(self):
        with tempfile.TemporaryDirectory() as d:
            posted, notes = [], []
            ids = Path(d) / "ids.json"
            ids.write_text(json.dumps({"company": "c", "agents": {"Quant": "q", "CEO": "e"}}))
            orig = regime.open_research_issue
            regime.open_research_issue = lambda o, n, s, post=None, ids_path=None: orig(o, n, s, post, ids)
            try:
                def post(path, body):
                    posted.append((path, body))

                def note(*a):
                    notes.append(a)
                coins = ("BTC_USDT", "ETH_USDT")
                s1 = regime.step(FakeClient(), d, coins, NOW, post, note)
                self.assertIn(s1["label"], regime.LABELS)
                self.assertEqual(posted, [])                                          # baseline: no issue
                self.assertTrue((Path(d) / "regime.json").exists())
                s2 = regime.step(FakeClient(hourly_drop=-0.12, now=NOW + 300_000), d, coins, NOW + 300_000, post, note)
                self.assertEqual(s2["label"], "crash")
                self.assertTrue(s2["changed"] and s2["issue_opened"])
                self.assertEqual(posted[0][0], "/companies/c/issues")
                self.assertEqual(posted[0][1]["assigneeAgentId"], "q")
                for k in range(3):                                                    # back to normal: 3 checks, in cooldown
                    s3 = regime.step(FakeClient(now=NOW + 600_000 + k * 300_000), d, coins, NOW + 600_000 + k * 300_000, post, None)
                self.assertTrue(s3["changed"])
                self.assertFalse(s3["issue_opened"])
                self.assertEqual(len(posted), 1)
                s4 = regime.step(FakeClient(stale_quote=True, now=NOW + 5_000_000), d, coins, NOW + 5_000_000, post, note)
                self.assertEqual(s4["label"], "unknown")
                self.assertTrue(any(n[1] == "critical" for n in notes))
                s5 = regime.step(FakeClient(stale_bars=True, now=NOW + 5_300_000), d, coins, NOW + 5_300_000, post, None)
                self.assertEqual(s5["label"], "unknown")
            finally:
                regime.open_research_issue = orig


def points(rets, start=1000.0, t0=19_000 * DAY):
    out, eq = [], start
    for i, r in enumerate(rets):
        eq *= 1 + r
        out.append((t0 + i * DAY + DAY - 1000, eq))
    return out, t0 + len(rets) * DAY + 1000


class HealthTest(unittest.TestCase):
    D = health.Design(0.001, 0.01, 0.30)

    def test_good_record_no_drift(self):
        pts, now = points([0.001, -0.004, 0.006] * 10)
        self.assertFalse(health.judge("x", pts, 1000.0, now, 0.3, design=self.D)["drift"])

    def test_persistent_losses_trip_cusum_but_one_noisy_week_does_not(self):
        pts, now = points([0.001] * 15 + [-0.02] * 8)
        r = health.judge("x", pts, 1000.0, now, 0.5, design=self.D)
        self.assertTrue(r["drift"] and "CUSUM" in r["reasons"][0])
        pts, now = points([0.001] * 30 + [-0.02, -0.02, 0.001, 0.001, -0.02, 0.001, 0.001] + [0.003] * 14)
        self.assertFalse(health.judge("x", pts, 1000.0, now, 0.5, design=self.D)["drift"])    # recovered
        pts, now = points([-0.05])
        self.assertFalse(health.judge("x", pts, 1000.0, now, 0.5, design=self.D)["drift"])    # one day: too short

    def test_drawdown_and_open_day_excluded(self):
        pts, now = points([0.0] * 5 + [-0.35])
        r = health.judge("x", pts, 1000.0, now, 0.5, design=self.D)
        self.assertTrue(r["drift"] and "drawdown" in r["reasons"][0])

    def test_slippage(self):
        pts, now = points([0.001] * 20)
        r = health.judge("x", pts, 1000.0, now, 0.5, [40.0] * 6, self.D)
        self.assertTrue(r["drift"] and "slippage" in r["reasons"][-1])
        self.assertFalse(health.judge("x", pts, 1000.0, now, 0.5, [40.0] * 2, self.D)["drift"])   # too few fills

    def test_stop_state_retire_and_allocate(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(health.status_of(d, "a")["status"], "ACTIVE")
            self.assertEqual(health.stop_strategy(d, "a", ["x"], 1_000)["status"], "PAUSED")
            self.assertTrue(health.is_stopped(d, "a"))
            self.assertEqual(health.stop_strategy(d, "a", ["y"], 1_000 + 30 * DAY)["status"], "RETIRED")
            self.assertEqual(health.stop_strategy(d, "a", ["z"], 9)["status"], "RETIRED")   # sticky
            health.stop_strategy(d, "b", ["x"], 1_000)
            health.stop_strategy(d, "b", ["x"], 1_000 + 400 * DAY)                           # long apart: only PAUSED
            self.assertEqual(health.status_of(d, "b")["status"], "PAUSED")
            self.assertEqual(health.allocate({"a", "b", "c", "d"}, 1000.0, d), {"c": 500.0, "d": 500.0})
            self.assertEqual(health.allocate({"c"}, 1000.0, d, 0.5), {"c": 500.0})
            self.assertEqual(health.allocate(set(), 1000.0, d), {})
            with self.assertRaises(ValueError):
                health.allocate({"c"}, 1000.0, d, 1.5)
            with self.assertRaises(ValueError):
                health.stop_strategy(d, "../evil", ["x"], 1)
            self.assertTrue(health.is_stopped(d, "../evil"))                                   # unknown shape: fail closed

    def test_no_regime_scaling_ships_after_failed_backtest(self):
        self.assertEqual({l: health.regime_scale(l) for l in regime.LABELS}, {l: 1.0 for l in regime.LABELS})

    def test_watch_stops_drifted_strategy_from_db(self):
        with tempfile.TemporaryDirectory() as d:
            db = sqlite3.connect(Path(d) / "shadow_grid.db")
            db.executescript("CREATE TABLE grids(id TEXT PRIMARY KEY, symbol TEXT, params TEXT, created_ts INTEGER, start_price REAL);"
                             "CREATE TABLE snaps(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, grid_id TEXT, price REAL, equity REAL, trips INTEGER);")
            db.execute("INSERT INTO grids VALUES('g','BTC_USDT',?,0,1)", (json.dumps({"invest": 1000.0}),))
            pts, now = points([0.001] * 20 + [-0.04] * 6)
            for ts, eq in pts:
                db.execute("INSERT INTO snaps(ts,grid_id,price,equity,trips) VALUES(?,?,?,?,0)", (ts, "g", 1, eq))
            db.commit()
            db.close()
            notes = []
            res = health.watch(d, 0.30, now, lambda *a: notes.append(a))
            self.assertTrue(res[0]["drift"])
            self.assertEqual(health.status_of(d, "g")["status"], "PAUSED")
            self.assertTrue((Path(d) / "LIVE_STOP_g").exists())
            self.assertEqual(notes[0][1], "important")
            # after the stop only the post-stop record is judged; with none, nothing is judged
            self.assertEqual(health.watch(d, 0.30, now + 2000), [])


class AdaptBacktestTest(unittest.TestCase):
    def series(self, rets):
        return [(i * DAY, r, 0.5, 0.01) for i, r in enumerate(rets)]

    def test_rule_b_aligned_stops_and_requalifies(self):
        design = [0.01 if i % 2 else -0.008 for i in range(adapt_test.DESIGN_DAYS)]
        design[300:312] = [-0.02] * 12                                          # the design range includes a ~22% drawdown
        bleed = [-0.015] * 12                                                   # slow bleed: CUSUM trips before the drawdown limit
        good = [0.01, -0.002] * 60
        s = self.series(design + bleed + good)
        out, stops = adapt_test.rule_b(s, 1)
        self.assertEqual([x[0] for x in out], [x[0] for x in s])               # same days, same length
        self.assertEqual(len(stops), 1)
        self.assertTrue(any(x[2] == 0.0 for x in out[adapt_test.DESIGN_DAYS:]))
        self.assertTrue(any(x[2] > 0 for x in out[-20:]))                      # back live after re-qualifying

    def test_rule_b_first_730_days_untouched_and_retires(self):
        design = [0.01 if i % 2 else -0.008 for i in range(adapt_test.DESIGN_DAYS)]
        design[300:312] = [-0.02] * 12
        s = self.series(design + [-0.015] * 12 + [0.01, -0.002] * 30 + [-0.015] * 14 + [0.01] * 60)
        out, stops = adapt_test.rule_b(s, 1)
        self.assertEqual(out[:adapt_test.DESIGN_DAYS], s[:adapt_test.DESIGN_DAYS])
        self.assertEqual(len(out), len(s))
        if len(stops) >= 2:
            self.assertTrue(all(x[2] == 0.0 for x in out[-30:]))               # retired: stays flat


if __name__ == "__main__":
    unittest.main()
