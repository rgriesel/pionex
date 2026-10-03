"""Labelled proxy-venue history (synthetic archive files only; no network)."""
import contextlib
import hashlib
import io
import unittest
import zipfile
from datetime import date

from pionex_lab.data import proxy
from pionex_lab.data.store import MarketStore, MarketView
from pionex_lab.research.registry import Registry

from helpers import T0, cleanup, make_bars, random_walk, tmp_paths

DAY = 86_400_000


def archive(rows, name="x.csv"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, "\n".join(",".join(str(v) for v in r) for r in rows))
    return buf.getvalue()


def day_rows(day_ms, step=300_000, micro=True, price=100.0):
    k = 1000 if micro else 1
    return [[(day_ms + i * step) * k, price, price + 1, price - 1, price + 0.5, 3.0, (day_ms + (i + 1) * step) * k - 1,
             0, 0, 0, 0, 0] for i in range(DAY // step)]


class FakeArchive:
    """Serves the daily files for 2026-09-01..03 plus checksums; everything else is 404."""
    def __init__(self, corrupt=False):
        self.files, self.requests = {}, []
        for d in range(1, 4):
            day = date(2026, 9, d)
            ms = (day.toordinal() - date(1970, 1, 1).toordinal()) * DAY
            url = f"{proxy.BASE_URL}/daily/klines/BTCUSDT/5m/BTCUSDT-5m-{day:%Y-%m-%d}.zip"
            blob = archive(day_rows(ms, micro=d != 2))                  # day 2 uses millisecond timestamps
            self.files[url] = blob
            digest = hashlib.sha256(b"tampered" if corrupt else blob).hexdigest()
            self.files[url + ".CHECKSUM"] = f"{digest}  BTCUSDT-5m-{day:%Y-%m-%d}.zip".encode()

    def __call__(self, url):
        self.requests.append(url)
        return self.files.get(url)


class Fetch(unittest.TestCase):
    def setUp(self):
        self.paths, self.dir = tmp_paths()
        self.store = MarketStore(self.paths.proxy_market)

    def tearDown(self):
        self.store.close()
        cleanup(self.dir)

    def test_parses_micro_and_milli_timestamps_and_skips_complete_days(self):
        fake = FakeArchive()
        cov = proxy.fetch(self.store, "BTC_USDT", "5M", 0, date(2026, 9, 4), T0, get=fake)
        self.assertEqual((cov["files_downloaded"], cov["bars"], cov["files_missing"]), (3, 3 * 288, 0))
        b = self.store.bars("BTC_USDT", "5M")
        self.assertEqual(b.t[288] - b.t[287], 300_000)                   # day 1 (us) joins day 2 (ms) cleanly
        self.assertEqual(b.t[0] % DAY, 0)
        again = FakeArchive()
        cov = proxy.fetch(self.store, "BTC_USDT", "5M", 0, date(2026, 9, 4), T0, get=again)
        self.assertEqual((cov["files_skipped"], again.requests), (3, []))

    def test_unpublished_monthly_archive_falls_back_to_daily_files(self):
        fake = FakeArchive()   # no September monthly file yet; only daily files for 1-3 September
        cov = proxy.fetch(self.store, "BTC_USDT", "5M", 1, date(2026, 10, 2), T0, get=fake)
        self.assertIn(f"{proxy.BASE_URL}/monthly/klines/BTCUSDT/5m/BTCUSDT-5m-2026-09.zip", fake.requests)
        self.assertEqual((cov["files_downloaded"], cov["bars"]), (3, 3 * 288))
        self.assertEqual(cov["files_missing"], 27 + 1)                  # 4-30 September and 1 October not served

    def test_checksum_mismatch_is_refused(self):
        with self.assertRaises(proxy.ProxyDataError):
            proxy.fetch(self.store, "BTC_USDT", "5M", 0, date(2026, 9, 4), T0, get=FakeArchive(corrupt=True))
        self.assertEqual(len(self.store.bars("BTC_USDT", "5M")), 0)


class Tracking(unittest.TestCase):
    def test_close_proxy_passes_and_divergent_proxy_fails(self):
        closes = random_walk(3000, 100.0, 0.002, seed=4)
        pionex = make_bars("BTC_USDT", "5M", closes)
        near = make_bars("BTC_USDT", "5M", [c * 1.0001 for c in closes])      # 1 bp away, same moves
        self.assertTrue(proxy.tracking_check(near, pionex)["ok"])
        other = make_bars("BTC_USDT", "5M", random_walk(3000, 100.0, 0.002, seed=9))
        self.assertFalse(proxy.tracking_check(other, pionex)["ok"])
        short = make_bars("BTC_USDT", "5M", closes[:500])
        self.assertFalse(proxy.tracking_check(short, pionex)["ok"])          # too little overlap to judge


class ResearchOnProxy(unittest.TestCase):
    def test_divergent_proxy_is_refused_without_spending_budget(self):
        from pionex_lab.cli import main
        paths, d = tmp_paths()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--var", str(paths.root), "init"]), 0)
            real, fake = MarketStore(paths.market), MarketStore(paths.proxy_market)
            for sym, seed in (("BTC_USDT", 1), ("ETH_USDT", 2)):
                closes = random_walk(30 * 288, 100.0, 0.002, seed=seed)
                for store, cl in ((real, closes), (fake, random_walk(len(closes), 100.0, 0.002, seed=seed + 50))):
                    b = make_bars(sym, "5M", cl, start=T0)
                    store.upsert_klines(sym, "5M", [proxy.Kline(t, *(proxy.Decimal(str(v)) for v in (o, h, l, c, v_)))
                                                    for t, o, h, l, c, v_ in zip(b.t, b.o, b.h, b.l, b.c, b.v)],
                                        None, T0 + 400 * DAY)
            real.close(), fake.close()
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(["--var", str(paths.root), "research", "--data", "proxy"]), 0)
            self.assertIn("does not track Pionex", out.getvalue())
            self.assertEqual(Registry(paths.research).conn.execute("SELECT COUNT(*) FROM cycles").fetchone()[0], 0)
        finally:
            cleanup(d)


if __name__ == "__main__":
    unittest.main()
