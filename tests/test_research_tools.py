"""Strategy zoo, factor engine and order-book depth parser (synthetic data only)."""
import hashlib
import io
import math
import os
import unittest
import zipfile
from datetime import date

from pionex_lab.data import depth, proxy
from pionex_lab.data.store import MarketStore
from pionex_lab.swing import factors, zoo

from helpers import cleanup, tmp_paths


class Zoo(unittest.TestCase):
    def bars(self, closes):
        n = len(closes)
        o = [closes[0]] + closes[:-1]
        return {"t": [k * 3_600_000 for k in range(n)], "o": o, "h": [max(a, b) * 1.001 for a, b in zip(o, closes)],
                "l": [min(a, b) * 0.999 for a, b in zip(o, closes)], "c": closes, "v": [1.0] * n}

    def test_costs_one_position_and_stop(self):
        b = self.bars([100 + math.sin(k / 7) * 5 + k * 0.01 for k in range(800)])
        a = zoo.atr(b["h"], b["l"], b["c"], 14)
        for name, (fn, grid) in zoo.STRATEGIES.items():
            if name in zoo.INTRADAY_ONLY:
                continue
            sig, ex = fn(b, grid[0])
            tr = zoo.simulate(b, a, sig, ex, 1.0, 2.0, 48)
            for x, y in zip(tr, tr[1:]):
                self.assertLessEqual(x[1], y[0], name)                              # one position at a time
            for x in tr:
                self.assertAlmostEqual(x[3] - x[4], 2 * (zoo.FEE + zoo.SLIP), msg=name)
        self.assertEqual(zoo._exit_in_bar(1, 100, 101, 98, 99, 103), 99)           # stop hit before target


class ZooEarly(unittest.TestCase):
    """The 2019-2023-03 re-test plumbing: separate database, bounded window, untouched default load()."""

    def setUp(self):
        self.paths, self.dir = tmp_paths()
        self.old_var = os.environ.get("PIONEX_LAB_VAR")
        os.environ["PIONEX_LAB_VAR"] = str(self.paths.root)
        zoo._CACHE.clear()

    def tearDown(self):
        if self.old_var is None:
            os.environ.pop("PIONEX_LAB_VAR", None)
        else:
            os.environ["PIONEX_LAB_VAR"] = self.old_var
        zoo._CACHE.clear()
        cleanup(self.dir)

    @staticmethod
    def month_files(files, raw, y, m):
        start = (date(y, m, 1).toordinal() - date(1970, 1, 1).toordinal()) * 86_400_000
        n = (date(y + m // 12, m % 12 + 1, 1).toordinal() - date(y, m, 1).toordinal()) * 24
        rows = chr(10).join(f"{start + k * 3_600_000},100,101,99,100.5,3,0,0,0,0,0,0" for k in range(n))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("x.csv", rows)
        url = f"{proxy.BASE_URL}/monthly/klines/{raw}/1h/{raw}-1h-{y}-{m:02d}.zip"
        files[url] = buf.getvalue()
        files[url + ".CHECKSUM"] = f"{hashlib.sha256(buf.getvalue()).hexdigest()}  x.zip".encode()
        return n

    def test_download_starts_at_listing_and_stays_before_april_2023(self):
        files, requests = {}, []
        n = sum(self.month_files(files, "BTCUSDT", 2023, m) for m in (1, 2, 3))

        def get(url):
            requests.append(url)
            return files.get(url)

        path = self.paths.root / "alpha" / zoo.EARLY_DB
        out = zoo.download_early(path, coins=("BTC_USDT",), get=get, now_ms=1_790_000_000_000)
        self.assertEqual((out[0]["bars"], out[0]["first_month"]), (n, "2023-01"))
        store = MarketStore(path)
        try:
            b = store.bars("BTC_USDT", "60M")
        finally:
            store.close()
        self.assertEqual(len(b), n)
        self.assertLess(b.t[-1], 1_680_307_200_000)                                  # before 2023-04-01 00:00 UTC
        self.assertFalse([u for u in requests if "2023-04" in u or "-2024" in u or "-2025" in u or "-2026" in u])
        self.assertFalse([u for u in requests if "/daily/" in u])                     # never a day from the live window
        with self.assertRaises(ValueError):
            zoo.download_early(self.paths.root / "alpha" / "alts_1h.db", coins=("BTC_USDT",), get=get)

    def test_pooled_work_threads_the_source_and_keeps_the_four_item_task(self):
        seen = []
        real_load, real_eval = zoo.load, zoo.evaluate
        zoo.load = lambda tf, symbol, source=None: seen.append((tf, symbol, source)) or {}
        zoo.evaluate = lambda b, name, hold: ([], [], [], [])
        try:
            self.assertEqual(zoo._pooled_work(("4h", "supertrend", "BTC_USDT", 60)), ("supertrend", "BTC_USDT", []))
            zoo._pooled_work(("4h", "supertrend", "ETH_USDT", 60, "early"))
        finally:
            zoo.load, zoo.evaluate = real_load, real_eval
        self.assertEqual(seen, [("4h", "BTC_USDT", None), ("4h", "ETH_USDT", "early")])

    def test_load_early_reads_its_own_database_and_leaves_default_alone(self):
        files = {}
        self.month_files(files, "ETHUSDT", 2023, 1)
        path = self.paths.root / "alpha" / zoo.EARLY_DB
        zoo.download_early(path, coins=("ETH_USDT",), get=lambda u: files.get(u), now_ms=1_790_000_000_000)
        b4 = zoo.load("4h", "ETH_USDT", "early")
        self.assertEqual(len(b4["t"]), 31 * 6)
        self.assertEqual(b4["t"][1] - b4["t"][0], 4 * 3_600_000)
        self.assertEqual(len(zoo.load("1h", "ETH_USDT", "early")["t"]), 31 * 24)
        self.assertEqual(set(zoo._CACHE), {("4h", "ETH_USDT", "early"), ("1h", "ETH_USDT", "early")})
        with self.assertRaises(ValueError):
            zoo.load("5m", "ETH_USDT", "early")
        with self.assertRaises(ValueError):
            zoo.load("4h", "ETH_USDT", "elsewhere")
        with self.assertRaises(Exception):                        # default source still looks in var/proxy_market.db
            zoo.load("4h", "ETH_USDT")


class Factors(unittest.TestCase):
    def test_spearman_and_series(self):
        self.assertAlmostEqual(factors.spearman(list(range(50)), [x * x for x in range(50)]), 1.0)
        self.assertAlmostEqual(factors.spearman(list(range(50)), [-x for x in range(50)]), -1.0)
        s = factors.Series([(10, 1.0), (20, 2.0)], avail_lag=5)
        self.assertTrue(math.isnan(s.at(14)))                                       # not available before t + lag
        self.assertEqual(s.at(15), 1.0)
        self.assertTrue(math.isnan(s.at(100, max_age=10)))

    def test_quantile_trades_use_only_past_predictions(self):
        preds = [(k * 1000, float(k % 10), 0.01) for k in range(600)]
        r = factors.trade_quantiles(preds, hold=1000, q=0.1, longonly=True)
        self.assertGreater(r["n"], 0)
        self.assertAlmostEqual(r["gross_pct"], 1.0)                                 # long-only side on +1% moves


class Depth(unittest.TestCase):
    def test_parse_keeps_last_snapshot_per_5_minutes(self):
        csv = "timestamp,percentage,depth,notional\n2026-10-01 00:00:01,-1.00,10,100\n2026-10-01 00:04:31,-1.00,12,120\n2026-10-01 00:05:01,-1.00,7,70\n"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("x.csv", csv)
        rows = depth.parse(buf.getvalue())
        t0 = 1790812800000                                                          # 2026-10-01 00:00 UTC
        self.assertEqual(rows[(t0, -1.0)], (12.0, 120.0))
        self.assertEqual(rows[(t0 + 300_000, -1.0)], (7.0, 70.0))


if __name__ == "__main__":
    unittest.main()
