"""Daily recorder (fake fetcher; no network)."""
import math
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone

from pionex_lab.data import daily_recorder as dr

D = 86_400_000
NOW = int(datetime(2026, 10, 15, 0, 5, tzinfo=timezone.utc).timestamp() * 1000)
DAY0 = NOW - NOW % D


def fake_fetch(url):
    if "deribit" in url:
        out = []
        for exp in ("22OCT26", "27NOV26", "29JAN27"):
            for k in range(60000, 160001, 10000):
                for cp in "CP":
                    iv = 50 + (100000 - k) / 10000 * (1 if cp == "P" else -0.5)   # put skew
                    out.append({"instrument_name": f"BTC-{exp}-{k}-{cp}", "mark_iv": iv, "underlying_price": 100000})
        return {"result": out}
    if "common/symbols" in url:
        return {"data": {"symbols": [{"symbol": "BTC_USDT", "enable": True, "quoteCurrency": "USDT"},
                                     {"symbol": "OFF_USDT", "enable": False, "quoteCurrency": "USDT"},
                                     {"symbol": "ETH_BTC", "enable": True, "quoteCurrency": "BTC"}]}}
    if "bookTickers" in url:
        t = lambda s, b, a: {"symbol": s, "bidPrice": b, "askPrice": a}
        return {"data": {"tickers": [t("BTC_USDT", "99.99", "100.01"), t("OFF_USDT", "1", "2"), t("ETH_BTC", "1", "2")]}}
    if "premiumIndexKlines" in url:
        return [[DAY0 - 2 * D, "0", "0.1", "-0.1", "0.01", 0], [DAY0 - D, "0", "0.1", "-0.1", "0.02", 0],
                [DAY0, "0", "0", "0", "0.5", 0]]
    if "coinbase" in url:
        return [[(DAY0 - D) // 1000, 1, 3, 2, 100.5, 9], [DAY0 // 1000, 1, 3, 2, 101, 9]]
    if "binance.com/api" in url:
        return [[DAY0 - D, 0, 0, 0, "100.0"], [DAY0, 0, 0, 0, "100"]]
    raise AssertionError(url)


class Recorder(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = os.path.join(self.dir, "recorded.db")

    def q(self, sql):
        con = sqlite3.connect(self.db)
        try:
            return con.execute(sql).fetchall()
        finally:
            con.close()

    def test_all_sources_recorded_once_and_idempotent(self):
        rep = dr.record_daily(self.db, NOW, fake_fetch)
        self.assertTrue(all(isinstance(v, int) for v in rep.values()), rep)
        rep2 = dr.record_daily(self.db, NOW, fake_fetch)
        self.assertEqual(rep2["premium"], 0)
        self.assertEqual(rep2["coinbase_binance"], 0)
        self.assertEqual(self.q("SELECT COUNT(*) FROM pionex_spread")[0][0], 1)       # enabled USDT only
        self.assertAlmostEqual(self.q("SELECT spread_bps FROM pionex_spread")[0][0], 2.0, places=2)
        self.assertEqual(self.q("SELECT COUNT(*) FROM premium_kline WHERE symbol='BTCUSDT'")[0][0], 2)  # open bar skipped
        self.assertAlmostEqual(self.q("SELECT premium_bps FROM cb_binance")[0][0], 50.0, places=3)
        self.assertEqual(self.q("SELECT COUNT(*) FROM deribit_skew")[0][0], 6)

    def test_put_skew_gives_negative_risk_reversal(self):
        dr.record_daily(self.db, NOW, fake_fetch)
        tenor, dte, atm, rr = self.q("SELECT tenor, dte, atm_iv, rr25 FROM deribit_skew WHERE currency='BTC' AND tenor=30")[0]
        self.assertLess(rr, 0)
        self.assertAlmostEqual(atm, 0.50, places=2)

    def test_one_failing_source_does_not_stop_others(self):
        def bad(url):
            if "deribit" in url:
                raise RuntimeError("down")
            return fake_fetch(url)
        rep = dr.record_daily(self.db, NOW, bad)
        self.assertTrue(rep["deribit"].startswith("error"))
        self.assertEqual(rep["pionex_spread"], 1)

    def test_delta_atm_forward_is_about_half(self):
        self.assertAlmostEqual(dr.bs_delta(100, 100, 0.0001, 0.1, True), 0.5, places=1)
        self.assertEqual(dr.parse_expiry("BTC-27MAR26-80000-C")[1:], (80000.0, True))


if __name__ == "__main__":
    unittest.main()
