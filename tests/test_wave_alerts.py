"""Watch-only wave alerts (synthetic bars, fake Telegram transport; no network)."""
import io
import json
import math
import unittest
import urllib.error

from pionex_lab.waves import alerts

from helpers import T0, make_bars

HOUR = 3_600_000
CFG = {**alerts.DEFAULTS, "symbols": ["BTC_USDT"]}


def primary(wave="3", move="up", score=80.0, inv=95.0, targets=(110.0,), kind="impulse", status=""):
    return {"type": kind, "current_wave": wave, "move": move, "score": score, "invalidation": inv,
            "direction": "bullish" if move == "up" else "bearish",
            "invalidated": False, "status": status,
            "targets": [{"price": t, "ratio": 1.0, "kind": "extension", "ref": "w1"} for t in targets]}


class Rules(unittest.TestCase):
    def test_driving_waves(self):
        self.assertEqual(alerts.driving_entry(primary("3", "up")), "LONG")
        self.assertEqual(alerts.driving_entry(primary("5", "down")), "SHORT")
        self.assertEqual(alerts.driving_entry(primary("C", "down", kind="correction (zigzag)")), "SHORT")
        self.assertIsNone(alerts.driving_entry(primary("2", "down")))       # corrective wave: no entry
        self.assertIsNone(alerts.driving_entry(primary("1", "up")))         # wave 1 only after a finished ABC
        self.assertEqual(alerts.driving_entry(primary("1", "up", status="A-B-C complete; the latest swing may start "
                                                                         "a new trend")), "LONG")
        self.assertIsNone(alerts.driving_entry({**primary(), "invalidated": True}))
        self.assertIsNone(alerts.driving_entry(None))

    def test_all_confirmations_required_and_nan_never_passes(self):
        p = primary(inv=97.0)
        self.assertEqual(alerts.confirmations("LONG", 100.0, 1.0, 60.0, 99.0, p, CFG), [])
        self.assertIn("RSI", alerts.confirmations("LONG", 100.0, 1.0, math.nan, 99.0, p, CFG))
        self.assertIn("EMA50", alerts.confirmations("LONG", 100.0, 1.0, 60.0, math.nan, p, CFG))
        self.assertIn("EWO", alerts.confirmations("LONG", 100.0, -1.0, 60.0, 99.0, p, CFG))
        self.assertIn("score", alerts.confirmations("LONG", 100.0, 1.0, 60.0, 99.0, primary(score=40, inv=97), CFG))
        self.assertIn("invalidation", alerts.confirmations("LONG", 100.0, 1.0, 60.0, 99.0, primary(inv=90), CFG))
        self.assertIn("invalidation", alerts.confirmations("LONG", 100.0, 1.0, 60.0, 99.0, primary(inv=101), CFG))
        self.assertEqual(alerts.confirmations("SHORT", 100.0, -1.0, 40.0, 101.0, primary(move="down", inv=103), CFG), [])

    def test_exits_and_costs(self):
        pos = {"side": "LONG", "invalidation": 95.0, "target": 110.0, "adverse": 0}
        self.assertEqual(alerts.exit_reason(pos, 94.0, primary(), 3, CFG)[0], "invalidation broken (stop)")
        self.assertEqual(alerts.exit_reason(pos, 111.0, primary(), 3, CFG)[0], "target reached")
        why, streak = alerts.exit_reason(pos, 100.0, primary(move="down"), 3, CFG)
        self.assertEqual((why, streak), (None, 1))                         # one adverse close is not enough
        why, _ = alerts.exit_reason({**pos, "adverse": 1}, 100.0, primary(move="down"), 3, CFG)
        self.assertEqual(why, "count turned against the position on two closes")
        self.assertEqual(alerts.exit_reason(pos, 100.0, primary(), 168, CFG)[0], "maximum holding time reached")
        gross, net = alerts.bps("SHORT", 100.0, 99.0, 5.0)
        self.assertAlmostEqual(gross, 101.0101, places=3)
        self.assertAlmostEqual(net, gross - 10.0)


class Telegram(unittest.TestCase):
    def test_discovers_chat_then_sends_and_never_leaks_the_token(self):
        token, calls = "123:SECRET-token", []

        class R(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def opener(req, timeout):
            calls.append((req.full_url, dict(x.split("=", 1) for x in req.data.decode().split("&"))))
            if req.full_url.endswith("getUpdates"):
                return R(json.dumps({"ok": True, "result": [{"message": {"chat": {"id": 42}}}]}).encode())
            return R(json.dumps({"ok": True, "result": {}}).encode())
        tg = {"token": token, "chat_id": None}
        self.assertEqual(alerts.telegram_send(tg, "hello", opener), "sent")
        self.assertEqual(calls[-1][1]["chat_id"], "42")
        self.assertEqual(tg["chat_id"], 42)

        def broken(req, timeout):
            raise urllib.error.URLError(f"could not reach {req.full_url}")
        with self.assertRaises(alerts.TelegramError) as cm:
            alerts.telegram_send(tg, "x", broken)
        self.assertNotIn("SECRET", str(cm.exception))


class FakeView:
    def __init__(self, closes):
        self.b = make_bars("BTC_USDT", "60M", closes, start=T0, spread=0.001)

    def bars(self, symbol, interval, limit=None, end_ms=None, complete_only=True):
        n = sum(1 for t in self.b.t if t + HOUR <= end_ms)
        return self.b.slice(max(0, n - (limit or n)), n)


class Flow(unittest.TestCase):
    def setUp(self):
        self.conn = alerts.connect(":memory:")
        self.sent = []
        self.view = FakeView([100.0 * (1.001 ** k) for k in range(300)])    # rising: RSI>50, EWO>0, above EMA
        self.now = T0 + 200 * HOUR + 60_000                                  # one minute after bar 199 closed
        self.p = primary("3", "up", inv=self.view.b.c[199] * 0.98, targets=(self.view.b.c[199] * 1.004,))
        self.orig = alerts.analyze
        alerts.analyze = lambda *a, **k: {"primary": self.p, "alternates": []}

    def tearDown(self):
        alerts.analyze = self.orig

    def wa(self):
        return alerts.WaveAlerts(self.conn, self.view, CFG, notify=lambda t: self.sent.append(t) or "sent",
                                 clock=lambda: self.now / 1000)

    def test_open_hold_close_with_one_alert_per_setup(self):
        wa = self.wa()
        self.assertEqual(wa.step(), [("BTC_USDT", "OPEN_LONG")])
        self.assertIn("OPEN LONG BTC_USDT", self.sent[0])
        self.assertIn("not financial advice", self.sent[0])
        self.assertEqual(wa.step(), [("BTC_USDT", "ALREADY_EVALUATED")])
        self.now += HOUR
        self.assertEqual(wa.step(), [("BTC_USDT", "HOLD")])                 # +0.1%: below the +0.4% target
        for _ in range(3):
            self.now += HOUR
            res = wa.step()
        self.assertEqual(res, [("BTC_USDT", "CLOSE")])
        pos = dict(self.conn.execute("SELECT * FROM positions").fetchone())
        self.assertEqual(pos["exit_reason"], "target reached")
        self.assertAlmostEqual(pos["net_bps"], pos["gross_bps"] - 10.0)
        self.now += HOUR
        self.assertEqual(wa.step(), [("BTC_USDT", "NONE")])                 # still wave 3: no second alert
        self.assertEqual(len(self.sent), 2)

    def test_stale_bar_after_restart_is_skipped(self):
        self.now = T0 + 200 * HOUR + 30 * 60_000                             # 30 minutes after the close
        self.assertEqual(self.wa().step(), [("BTC_USDT", "SKIP")])
        self.assertEqual(self.sent, [])


class SurvivesNetworkDrops(unittest.TestCase):
    def test_a_failing_step_does_not_end_the_loop(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest import mock

        class Stop:
            def __init__(self):
                self.n = 0

            def wait(self, s):
                self.n += 1
                return self.n >= 2                                   # two polls, then stop
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:   # run() keeps its sqlite file open
            paths = SimpleNamespace(root=Path(d))
            (Path(d) / "wave_alerts.json").write_text(json.dumps({"symbols": ["BTC_USDT"]}), encoding="utf-8")
            with mock.patch.object(alerts, "config_path", return_value=Path(d) / "wave_alerts.json"), \
                    mock.patch.object(alerts.WaveAlerts, "step", side_effect=OSError("network down")), \
                    mock.patch.object(alerts, "PionexBars", return_value=None):
                stop = Stop()
                self.assertEqual(alerts.run(paths, stop), 0)
                self.assertEqual(stop.n, 2)                          # kept polling after the error


class DirectPionexBars(unittest.TestCase):
    def test_only_closed_bars_and_limit(self):
        H = 3_600_000

        class Feed:
            def candles(self, symbol, interval, limit=500):
                ts = [T0 + i * H for i in range(5)]                     # last one still open at end_ms
                return {"t": ts, "o": [1.0] * 5, "h": [2.0] * 5, "l": [0.5] * 5, "c": [1.5] * 5, "v": [9.0] * 5}
        b = alerts.PionexBars(Feed()).bars("BTC_USDT", "60M", limit=3, end_ms=T0 + 4 * H + 60_000)
        self.assertEqual(b.t, [T0 + H, T0 + 2 * H, T0 + 3 * H])          # newest closed bar ends at T0+4h
        self.assertEqual(b.interval_ms, H)


if __name__ == "__main__":
    unittest.main()
