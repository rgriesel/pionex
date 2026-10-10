"""Wave Lab: Elliott counting rules, feeds, and the read-only local server (synthetic data only)."""
from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request

from pionex_lab.exchange.pionex_public import PionexPublic
from pionex_lab.exchange.ratelimit import WeightedLimiter
from pionex_lab.waves import elliott as ew
from pionex_lab.waves.feeds import DemoFeed, PionexFeed, validate
from pionex_lab.waves.server import WaveApi, make_handler
from tests.fake_pionex import FakePionex
from tests.helpers import T0


def path(points, steps=10):
    """Piecewise-linear closes through the given swing points; h/l hug the close."""
    c = []
    for a, b in zip(points, points[1:]):
        c += [a + (b - a) * k / steps for k in range(steps)]
    c.append(points[-1])
    h = [x * 1.001 for x in c]
    l = [x * 0.999 for x in c]
    return list(range(len(c))), c, h, l


class ZigzagTest(unittest.TestCase):
    def test_alternating_pivots_and_unconfirmed_last(self):
        t, c, h, l = path([100, 110, 104, 120, 115])
        piv = ew.zigzag(h, l, 0.03)
        self.assertEqual([p.kind for p in piv], ["L", "H", "L", "H", "L"])
        self.assertTrue(all(p.confirmed for p in piv[:-1]))
        self.assertFalse(piv[-1].confirmed)
        self.assertAlmostEqual(piv[1].price, 110 * 1.001)

    def test_small_moves_are_ignored(self):
        t, c, h, l = path([100, 101, 100.5, 102])
        self.assertEqual(len(ew.zigzag(h, l, 0.05)), 0)

    def test_degree_thresholds_increase(self):
        t, c, h, l = path([100, 110, 104, 120, 115, 130])
        thr = [ew.auto_threshold(h, l, c, d) for d in ("minor", "intermediate", "primary")]
        self.assertEqual(thr, sorted(thr))
        with self.assertRaises(ValueError):
            ew.auto_threshold(h, l, c, "cosmic")


class RulesTest(unittest.TestCase):
    def test_textbook_impulse_passes_every_rule(self):
        rules, guides = ew.check_impulse([100, 110, 104, 126, 119, 133], up=True)
        self.assertTrue(all(ok for _, ok in rules))
        self.assertGreater(ew._score(rules, guides), 80)

    def test_wave4_overlap_rejects_impulse(self):
        rules, guides = ew.check_impulse([100, 110, 104, 126, 108, 133], up=True)
        self.assertFalse(dict(rules)["Wave 4 does not overlap wave 1"])
        self.assertEqual(ew._score(rules, guides), 0.0)

    def test_wave2_beyond_origin_rejects(self):
        rules, _ = ew.check_impulse([100, 110, 99], up=True)
        self.assertFalse(all(ok for _, ok in rules))

    def test_wave3_shortest_rejects(self):
        rules, _ = ew.check_impulse([100, 120, 110, 125, 120, 145], up=True)
        self.assertFalse(dict(rules)["Wave 3 is not the shortest of waves 1, 3, 5"])

    def test_bearish_impulse_is_mirror(self):
        up = ew.check_impulse([100, 110, 104, 126, 119, 133], up=True)
        down = ew.check_impulse([-100, -110, -104, -126, -119, -133], up=False)
        self.assertEqual([ok for _, ok in up[0]], [ok for _, ok in down[0]])

    def test_correction_kinds(self):
        kind, rules, _ = ew.check_correction([120, 110, 116, 104], down=True)
        self.assertEqual(kind, "zigzag")
        self.assertTrue(all(ok for _, ok in rules))
        kind, _, _ = ew.check_correction([120, 110, 121, 108], down=True)
        self.assertEqual(kind, "expanded flat")


class AnalyzeTest(unittest.TestCase):
    def test_wave3_in_progress_targets_and_invalidation(self):
        t, c, h, l = path([100, 110, 104, 118])
        a = ew.analyze(t, c, h, l, c, pct=0.03)
        counts = {x["type"]: x for x in [a["primary"], *a["alternates"]]}
        # Same swings, two valid readings: impulse waves 1-2-3 or a rising A-B-C zigzag.
        self.assertIn("correction (zigzag)", counts)
        self.assertEqual(counts["correction (zigzag)"]["move"], "up")
        p = counts["impulse"]
        self.assertEqual(p["current_wave"], "3")
        self.assertEqual(p["move"], "up")
        self.assertAlmostEqual(p["invalidation"], 100 * 0.999)
        w1 = 110 * 1.001 - 100 * 0.999
        self.assertIn(round(104 * 0.999 + 1.618 * w1, 6), [round(x["price"], 6) for x in p["targets"]])

    def test_completed_impulse_then_correction(self):
        t, c, h, l = path([100, 110, 104, 126, 119, 133, 124])
        a = ew.analyze(t, c, h, l, c, pct=0.03)
        p = a["primary"]
        self.assertEqual((p["type"], p["current_wave"], p["move"]), ("impulse", "A", "down"))
        self.assertEqual([w["label"] for w in p["waves"]], ["0", "1", "2", "3", "4", "5"])
        row = ew.scan_summary("X_USDT", "60M", a, c[-1])
        self.assertEqual(row["current_wave"], "A")
        self.assertLess(row["next_target"], c[-1])

    def test_invalidated_counts_are_dropped(self):
        # Wave 2 then a collapse below the origin of wave 1: no bullish 1-2 count may survive.
        t, c, h, l = path([100, 110, 104, 97.5])
        a = ew.analyze(t, c, h, l, c, pct=0.03)
        for cnt in [a["primary"], *a["alternates"]]:
            if cnt and cnt["type"] == "impulse" and cnt["trend"] == "up":
                self.assertFalse(cnt["invalidated"])
                self.assertNotEqual(cnt["waves"][0]["price"], 100 * 0.999)

    def test_short_series_is_safe(self):
        a = ew.analyze([1, 2], [1, 1], [1, 1], [1, 1], [1, 1])
        self.assertIsNone(a["primary"])

    def test_levels_count_each_swing_once(self):
        t, c, h, l = path([100, 110, 104, 110, 104, 110, 100], steps=12)
        for lv in ew.support_resistance(h, l, c):
            self.assertLessEqual(lv["touches"], 4)

    def test_wave_oscillator(self):
        h = [float(i) for i in range(40)]
        out = ew.wave_oscillator(h, h)
        self.assertIsNone(out[33])
        self.assertAlmostEqual(out[39], (37.0) - (22.0))


class FeedTest(unittest.TestCase):
    def test_validate(self):
        validate("BTC_USDT", "60M")
        for sym, iv in (("btc", "60M"), ("../x", "60M"), ("BTC_USDT", "2H")):
            with self.assertRaises(ValueError):
                validate(sym, iv)

    def test_demo_is_deterministic_and_consistent_across_intervals(self):
        now = (T0 + 7_200_000) / 1000
        f = DemoFeed(clock=lambda: now)
        a, b = f.candles("BTC_USDT", "60M", 50), f.candles("BTC_USDT", "60M", 50)
        self.assertEqual(a, b)
        d4 = f.candles("BTC_USDT", "4H", 5)
        self.assertAlmostEqual(a["c"][-1], d4["c"][-1], delta=a["c"][-1] * 1e-9)
        for i in range(50):
            self.assertLessEqual(a["l"][i], min(a["o"][i], a["c"][i]))
            self.assertGreaterEqual(a["h"][i], max(a["o"][i], a["c"][i]))

    def test_pionex_feed_pages_and_caches(self):
        fake = FakePionex(lambda: T0 + 30 * 86_400_000).__enter__()
        try:
            client = PionexPublic(fake.url, limiter=WeightedLimiter(10_000, exit_reserve=0))
            feed = PionexFeed(client, ttl_s=60, clock=lambda: 0.0)
            bars = feed.candles("BTC_USDT", "60M", 700)
            self.assertEqual(len(bars["t"]), 700)
            self.assertEqual(bars["t"], sorted(set(bars["t"])))
            n = len(fake.requests)
            feed.candles("BTC_USDT", "60M", 300)
            self.assertEqual(len(fake.requests), n)  # served from cache
        finally:
            fake.__exit__(None, None, None)


class BrowserEngineParityTest(unittest.TestCase):
    """wavelab/engine.js (hosted build) must count waves exactly like elliott.py."""

    def test_js_engine_matches_python(self):
        import shutil
        import subprocess
        from pionex_lab.util import PROJECT_ROOT
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        now = (T0 + 5 * 86_400_000 + 1_234_567) / 1000
        feed, cases = DemoFeed(clock=lambda: now), []
        for sym in ("BTC_USDT", "ETH_USDT", "DOGE_USDT"):
            for iv in ("15M", "60M", "4H", "1D"):
                b = feed.candles(sym, iv, 400)
                for deg in ("minor", "intermediate", "primary"):
                    a = ew.analyze(b["t"], b["o"], b["h"], b["l"], b["c"], degree=deg)
                    cases.append({"sym": sym, "iv": iv, "deg": deg, "bars": b, "py": {
                        "primary": a["primary"], "alternates": a["alternates"], "history": a["history"],
                        "levels": a["levels"], "pivots": a["pivots"]}})
        script = """
global.window = {}; require(process.argv[1]);
const E = window.WaveEngine, cases = JSON.parse(require('fs').readFileSync(0, 'utf8')), out = [];
Date.now = () => %d;
for (const c of cases) {
  const b = c.bars, a = E.analyze(b.t, b.o, b.h, b.l, b.c, c.deg);
  const jb = E.candles(c.sym, c.iv, b.c.length);
  out.push({primary: a.primary, alternates: a.alternates, history: a.history, levels: a.levels, pivots: a.pivots,
            closes: jb.c});
}
process.stdout.write(JSON.stringify(out));
""" % int(now * 1000)
        res = subprocess.run([node, "-e", script, str(PROJECT_ROOT / "wavelab" / "engine.js")],
                             input=json.dumps(cases), capture_output=True, text=True, timeout=120)
        self.assertEqual(res.returncode, 0, res.stderr)
        js = json.loads(res.stdout)

        def close(x, y, path="") -> None:
            if isinstance(x, dict):
                self.assertEqual(set(x), set(y), path)
                for k in x:
                    close(x[k], y[k], f"{path}.{k}")
            elif isinstance(x, list):
                self.assertEqual(len(x), len(y), path)
                for i, (a, b) in enumerate(zip(x, y)):
                    close(a, b, f"{path}[{i}]")
            elif isinstance(x, float) or isinstance(y, float):
                self.assertAlmostEqual(float(x), float(y), delta=max(1e-9, abs(float(x)) * 1e-9), msg=path)
            else:
                self.assertEqual(x, y, path)
        for c, j in zip(cases, js):
            for k in ("primary", "alternates", "history", "levels", "pivots"):
                close(c["py"][k], j[k], f"{c['sym']} {c['iv']} {c['deg']} {k}")
            close(c["bars"]["c"], j["closes"], f"{c['sym']} {c['iv']} demo closes")


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        port = cls.httpd.server_address[1]
        cls.httpd.RequestHandlerClass = make_handler(WaveApi(DemoFeed()), {f"127.0.0.1:{port}", f"localhost:{port}"})
        cls.base = f"http://127.0.0.1:{port}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def get(self, path, headers=None, method="GET"):
        req = urllib.request.Request(self.base + path, headers=headers or {}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers

    def test_page_and_meta(self):
        st, body, hdr = self.get("/")
        self.assertEqual(st, 200)
        self.assertIn(b"Wave Lab", body)
        self.assertIn("frame-ancestors 'none'", hdr["Content-Security-Policy"])
        st, body, _ = self.get("/api/meta")
        meta = json.loads(body)
        self.assertEqual(meta["feed"], "demo")
        self.assertIn("not market data", meta["feed_label"])

    def test_analysis_with_bars(self):
        st, body, _ = self.get("/api/analysis?symbol=ETH_USDT&interval=4H&degree=minor&limit=300&bars=1")
        self.assertEqual(st, 200)
        a = json.loads(body)
        self.assertEqual(len(a["bars"]["c"]), 300)
        self.assertEqual(len(a["ewo"]), 300)
        self.assertTrue(a["pivots"])

    def test_scan_and_quotes(self):
        st, body, _ = self.get("/api/scan?symbols=BTC_USDT,ETH_USDT&intervals=60M,1D&degree=primary")
        rows = json.loads(body)["rows"]
        self.assertEqual(len(rows), 4)
        st, body, _ = self.get("/api/quotes?symbols=BTC_USDT")
        q = json.loads(body)["quotes"]["BTC_USDT"]
        self.assertEqual(len(q["spark"]), 25)

    def test_rejects_foreign_host_bad_input_and_writes(self):
        self.assertEqual(self.get("/api/meta", {"Host": "evil.example:80"})[0], 403)
        self.assertEqual(self.get("/api/candles?symbol=../etc&interval=60M")[0], 400)
        self.assertEqual(self.get("/api/analysis?symbol=BTC_USDT&interval=60M&degree=x")[0], 400)
        self.assertEqual(self.get("/api/analysis?symbol=BTC_USDT&interval=60M&pct=5")[0], 400)
        self.assertEqual(self.get("/api/scan?symbols=BTC_USDT&intervals=")[0], 400)
        self.assertEqual(self.get("/api/meta", method="POST")[0], 405)
        self.assertEqual(self.get("/nope")[0], 404)


if __name__ == "__main__":
    unittest.main()
