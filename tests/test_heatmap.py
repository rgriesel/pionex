"""Estimated liquidation heatmap model (synthetic data, fake transport; no network)."""
import unittest

from pionex_lab.waves import heatmap as hm
from pionex_lab.waves.feeds import DemoFeed
from pionex_lab.waves.server import WaveApi

STEP = 300_000
EQUAL = hm.MODELS[1]


def levels_at(out, k):
    """{bin price midpoint: (long, short)} for column k."""
    b = out["bins"]
    return {round(b["lo"] + (c[0] + 0.5) * b["width"], 2): (c[1], c[2]) for c in out["columns"][k]["cells"]}


class Model(unittest.TestCase):
    def test_new_open_interest_places_levels_at_leverage_prices(self):
        rows = [(STEP, 1000.0, 100.2, 99.8, 100.0), (2 * STEP, 1200.0, 100.2, 99.8, 100.0)]
        out = hm.model(rows, STEP, EQUAL, bins=2000)
        cells = out["columns"][1]["cells"]
        self.assertEqual(sum(c[1] for c in cells), 100)          # 200 new notional: half long ...
        self.assertEqual(sum(c[2] for c in cells), 100)          # ... half short, 25 per tier
        prices = sorted(levels_at(out, 1))
        for lev in (10, 25, 50, 100):                            # long at p(1 - 1/L + mmr), short at p(1 + 1/L - mmr)
            for target in (100 * (1 - 1 / lev + hm.MMR), 100 * (1 + 1 / lev - hm.MMR)):
                self.assertTrue(any(abs(p - target) < 0.02 for p in prices), (lev, target))
        self.assertEqual(out["columns"][0]["cells"], [])         # nothing before the first increase

    def test_trading_through_a_level_removes_it_and_falling_oi_shrinks_the_rest(self):
        rows = [(STEP, 1000.0, 100.2, 99.8, 100.0), (2 * STEP, 1200.0, 100.2, 99.8, 100.0),
                (3 * STEP, 1200.0, 100.2, 96.0, 97.0),           # low 96: 25x/50x/100x long levels gone
                (4 * STEP, 600.0, 97.5, 96.8, 97.0)]             # OI halves: what is left halves
        out = hm.model(rows, STEP, EQUAL, bins=2000)
        longs = sum(c[1] for c in out["columns"][2]["cells"])
        self.assertEqual(longs, 25)                              # only the 10x long tier (90.5) survives
        self.assertEqual(sum(c[2] for c in out["columns"][2]["cells"]), 100)   # shorts untouched
        self.assertEqual(sum(c[1] for c in out["columns"][3]["cells"]), 12)    # 25 * 0.5, rounded
        self.assertEqual(out["max_long"], 25)                    # brightest single cell: one 25-unit tier

    def test_short_side_consumed_by_highs(self):
        rows = [(STEP, 1000.0, 100.2, 99.8, 100.0), (2 * STEP, 1200.0, 100.2, 99.8, 100.0),
                (3 * STEP, 1200.0, 104.0, 99.9, 103.0)]          # high 104: 50x/100x/25x short levels gone
        out = hm.model(rows, STEP, EQUAL, bins=2000)
        self.assertEqual(sum(c[2] for c in out["columns"][2]["cells"]), 25)    # only 10x short (109.5) left


class FakeBinance:
    def __init__(self, n=288, fail=False):
        self.urls, self.n, self.fail = [], n, fail

    def __call__(self, url):
        self.urls.append(url)
        if self.fail:
            raise hm.HeatmapError("Binance HTTP 400 for openInterestHist")
        t0 = 1_790_000_000_000
        if "openInterestHist" in url:
            return [{"timestamp": t0 + (k + 1) * STEP, "sumOpenInterestValue": str(1e6 + k * 1000)} for k in range(self.n)]
        return [[t0 + k * STEP, "100", "100.5", "99.5", "100", "1"] for k in range(self.n + 1)]


class Service(unittest.TestCase):
    def test_range_period_and_leverage_filter(self):
        fake = FakeBinance()
        out = hm.heatmap("BTC_USDT", "24h", 2, "25", get=fake)
        self.assertIn("symbol=BTCUSDT&period=5m&limit=288", fake.urls[0])
        self.assertEqual(out["tiers"], {25: hm.MODELS[2][25]})
        self.assertEqual(len(out["columns"]), 288)
        self.assertIn("not observed liquidations", out["note"])
        for rng, (period, n) in hm.RANGES.items():
            self.assertLessEqual(n, 500, rng)                    # every range is one request
        with self.assertRaises(ValueError):
            hm.heatmap("BTC_USDT", "5y", 1, "all", get=fake)
        with self.assertRaises(ValueError):
            hm.heatmap("BTC_USDT", "24h", 3, "10", get=fake)     # model 3 has no 10x tier
        with self.assertRaises(hm.HeatmapError):
            hm.binance_symbol("ETH_BTC")

    def test_api_caches_and_reports_unavailable(self):
        fake = FakeBinance()
        api = WaveApi(DemoFeed(), heat_source=fake)
        a = api.heatmap("BTC_USDT", "24h", 1, "all")
        b = api.heatmap("BTC_USDT", "24h", 1, "all")
        self.assertTrue(a["available"])
        self.assertIs(a, b)
        self.assertEqual(len(fake.urls), 2)                      # second call served from the 60 s cache
        bad = WaveApi(DemoFeed(), heat_source=FakeBinance(fail=True)).heatmap("BTC_USDT", "24h", 1, "all")
        self.assertFalse(bad["available"])
        self.assertIn("HTTP 400", bad["note"])


if __name__ == "__main__":
    unittest.main()
