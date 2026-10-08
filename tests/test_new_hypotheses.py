"""Hypotheses pre-registered 2026-10-06 (synthetic data only) and hypothesis retirement."""
import unittest

from pionex_lab.data.store import resample
from pionex_lab.strategies import catalog

from helpers import T0, make_bars, random_walk

HOUR = 3_600_000


def universe_5m(closes, vol=None, symbol="BTC_USDT"):
    b5 = make_bars(symbol, "5M", closes, vol=vol)
    b60 = make_bars(symbol, "60M", [closes[min(len(closes) - 1, k * 12 + 11)] for k in range(len(closes) // 12)])
    return {symbol: (b5, b60)}


def universe_1h(closes, symbol="BTC_USDT"):
    b = make_bars(symbol, "60M", closes)
    return {symbol: (b, resample(b, "4H"))}


def signals(strategy, universe, symbol="BTC_USDT"):
    prep = strategy.prepare(universe)
    n = len(universe[symbol][0])
    return [s for s in (strategy.check(prep, symbol, i) for i in range(strategy.warmup, n)) if s]


class CapitulationReversal(unittest.TestCase):
    def test_fires_after_a_high_volume_flush_and_not_on_calm_data(self):
        cls = catalog.ALL["capitulation_reversal"]
        calm = random_walk(400, 100.0, 0.0005, seed=3)
        self.assertEqual(signals(cls({"n": 6, "k": 3.0, "rr": 1.0}), universe_5m(calm)), [])
        flush = calm[:330] + [calm[329] * (1 - 0.006 * k) for k in range(1, 6)] + [calm[329] * 0.972]
        flush += [flush[-1] * 1.004] + [flush[-1] * 1.004 * (1 + 0.0002 * k) for k in range(1, 64)]
        vol = [10.0] * len(flush)
        vol[333] = 60.0                                                   # volume spike inside the drop
        sig = signals(cls({"n": 6, "k": 3.0, "rr": 1.0}), universe_5m(flush, vol))
        self.assertTrue(sig)
        s = sig[0]
        self.assertEqual(s.bar_time, T0 + 335 * 300_000)                  # bar 334 is the low; 335 is first green
        self.assertLess(s.stop, min(flush[330:336]))
        self.assertGreater(s.target, s.reference_price)
        self.assertLessEqual(s.max_hold_bars * 5, 240)


class BandSnapbackScalp(unittest.TestCase):
    def test_impulsive_close_below_band_targets_the_mean(self):
        cls = catalog.ALL["band_snapback_scalp"]
        p = {"k": 2.5, "trend": 0, "stop_atr": 1.0, "hold": 6}
        calm = random_walk(400, 100.0, 0.0004, seed=5)
        self.assertEqual(signals(cls(p), universe_5m(calm)), [])
        shock = calm[:350] + [calm[349] * 0.985] + calm[351:]
        sig = signals(cls(p), universe_5m(shock))
        self.assertTrue(sig)
        self.assertEqual(sig[0].bar_time, T0 + 350 * 300_000)
        self.assertGreater(sig[0].target, sig[0].reference_price)
        self.assertEqual(sig[0].max_hold_bars, 6)


class UsOpenBreakoutScalp(unittest.TestCase):
    def day(self, start_ms, breakout=True):
        """5m bars from 00:00 UTC on a US-summer date: flat, a 13:30-13:45 range, then a break."""
        n = 24 * 12
        closes = [100.0] * n
        k0 = (13 * 60 + 30) // 5
        closes[k0:k0 + 3] = [100.2, 99.9, 100.1]
        if breakout:
            closes[k0 + 5] = 100.6
        vol = [10.0] * n
        vol[k0 + 5] = 30.0
        b5 = make_bars("BTC_USDT", "5M", [100.0] * 300 + closes, start=start_ms - 300 * 300_000, spread=0.0005,
                       vol=[10.0] * 300 + vol)
        b60 = make_bars("BTC_USDT", "60M", [100.0] * (len(b5) // 12), start=b5.t[0])
        return {"BTC_USDT": (b5, b60)}

    def test_first_break_after_the_us_open_only_on_weekdays(self):
        from datetime import datetime, timezone
        cls = catalog.ALL["us_open_breakout_scalp"]
        p = {"stop_mid": 0, "rr": 1.5, "v_mult": 1.5}
        wed = int(datetime(2026, 7, 15, tzinfo=timezone.utc).timestamp() * 1000)
        sig = signals(cls(p), self.day(wed))
        self.assertEqual(len(sig), 1)
        self.assertEqual(sig[0].bar_time, wed + ((13 * 60 + 30) + 25) * 60_000)
        self.assertLess(sig[0].stop, 100.0)
        self.assertEqual(signals(cls(p), self.day(wed, breakout=False)), [])
        sat = int(datetime(2026, 7, 18, tzinfo=timezone.utc).timestamp() * 1000)
        self.assertEqual(signals(cls(p), self.day(sat)), [])


class SessionDrift(unittest.TestCase):
    def test_enters_only_at_the_registered_hour_with_a_time_exit(self):
        cls = catalog.ALL["session_drift_1h"]
        closes = random_walk(24 * 20, 100.0, 0.004, seed=8)
        sig = signals(cls({"hour": 14, "hold": 2, "trend": 0}), universe_1h(closes))
        self.assertTrue(sig)
        for s in sig:
            self.assertEqual(((s.bar_time + HOUR) // HOUR) % 24, 14)     # entry at the 14:00 UTC open
            self.assertIsNone(s.target)
            self.assertEqual(s.max_hold_bars, 2)
        filtered = signals(cls({"hour": 14, "hold": 2, "trend": 1}), universe_1h(closes))
        self.assertLessEqual(len(filtered), len(sig))


class DeepPullback(unittest.TestCase):
    def test_deep_dip_in_uptrend_only(self):
        cls = catalog.ALL["deep_pullback_1h"]
        p = {"k": 1.5, "stop_atr": 1.5, "confirm": 0}
        up = [100 * (1.0015 ** k) for k in range(400)]
        dip = up[:380] + [up[379] * f for f in (0.985, 0.975, 0.97)] + up[383:]
        sig = signals(cls(p), universe_1h(dip))
        self.assertTrue(sig)
        for s in sig:
            self.assertGreater(s.target, s.reference_price)               # target is the EMA above the dip
            self.assertLessEqual(s.max_hold_bars, 4)
        down = [100 * (0.9985 ** k) for k in range(400)]
        crash = down[:380] + [down[379] * f for f in (0.985, 0.975, 0.97)] + down[383:]
        self.assertEqual(signals(cls(p), universe_1h(crash)), [])         # no 4h uptrend, no trade


class FundingExtreme(unittest.TestCase):
    def series(self, n_hours=24 * 120, low_at=None):
        """Hourly bars plus funding settled every 8h: alternating mild rates, one deep negative."""
        b = make_bars("BTC_USDT", "60M", random_walk(n_hours, 100.0, 0.003, seed=12))
        f = []
        for k in range(n_hours // 8):
            t = T0 + k * 8 * HOUR + 1                                     # 1 ms after the hour, as Binance does
            f.append((t, -0.0009 if t == low_at else 0.0001 * (1 + (k % 7))))
        return b, f

    def test_fresh_low_settlement_only_and_point_in_time(self):
        cls = catalog.ALL["funding_extreme_1h"]
        p = {"q": 0.05, "hold": 2, "stop_atr": 1.5}
        low_at = T0 + 300 * 8 * HOUR + 1                                  # after the 270-settlement warm-up
        b, f = self.series(low_at=low_at)
        self.assertEqual(signals(cls(p), {"BTC_USDT": (b, resample(b, "4H"))}), [])   # no funding attached
        b.funding = f
        sig = signals(cls(p), {"BTC_USDT": (b, resample(b, "4H"))})
        self.assertEqual(len(sig), 1)
        self.assertGreaterEqual(sig[0].decided_at, low_at)              # never before the settlement is known
        self.assertEqual(sig[0].bar_time, low_at - 1)                    # the first bar closing after it
        self.assertIsNone(sig[0].target)
        self.assertEqual(sig[0].max_hold_bars, 2)

    def test_fetch_pages_and_stores_settlements(self):
        import sqlite3
        from pionex_lab.data import proxy
        conn = sqlite3.connect(":memory:")
        now = T0 + 3000 * 8 * HOUR
        calls = []

        def get_json(url):
            calls.append(url)
            start = int(url.split("startTime=")[1].split("&")[0])
            first = max(start, T0)
            k0 = -(-(first - T0) // (8 * HOUR))
            return [{"fundingTime": T0 + (k0 + k) * 8 * HOUR, "fundingRate": "0.0001"}
                    for k in range(1000) if T0 + (k0 + k) * 8 * HOUR <= now]
        out = proxy.fetch_funding(conn, "BTC_USDT", now, days=1100, get_json=get_json)
        self.assertEqual(out["funding_rows"], 3001)
        self.assertGreaterEqual(len(calls), 4)                           # paged 1000 at a time
        again = proxy.fetch_funding(conn, "BTC_USDT", now, get_json=get_json)
        self.assertEqual(again["funding_rows_added"], 0)                 # resumes after the last settlement
        self.assertEqual(len(proxy.funding_series(conn, "BTC_USDT")), 3001)


class Mandate(unittest.TestCase):
    def test_new_hypotheses_respect_search_budget_and_holding_cap(self):
        from helpers import mandate
        q = mandate().qualification
        for name in ("capitulation_reversal", "band_snapback_scalp", "us_open_breakout_scalp", "funding_extreme_1h", "session_drift_1h",
                     "deep_pullback_1h"):
            cls = catalog.ALL[name]
            self.assertLessEqual(len(cls.grid), int(q["max_parameter_trials_per_hypothesis"]))
            bar_min = catalog.INTERVAL_MS[cls.base_interval] // 60_000
            self.assertLessEqual(cls.max_hold_bars * bar_min, 240)


class Retirement(unittest.TestCase):
    def test_rejected_twice_is_retired_and_least_tested_go_first(self):
        from pionex_lab.cli import select_hypotheses
        names = ["a", "b", "c", "d"]
        active, retired = select_hypotheses(names, {"a": 2, "b": 1, "c": 5}, 5)
        self.assertEqual(retired, ["a", "c"])
        self.assertEqual(active, ["d", "b"])
        active, _ = select_hypotheses(names, {}, 2)
        self.assertEqual(active, ["a", "b"])                              # budget cap keeps catalog order
        self.assertEqual(select_hypotheses(["a"], {"a": 2}, 5), ([], ["a"]))


if __name__ == "__main__":
    unittest.main()
