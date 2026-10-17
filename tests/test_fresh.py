"""CLO-44 live-data freshness rule: fake clients, no network."""
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from pionex_lab.exchange.pionex_public import BookTicker
from pionex_lab.live import fresh

NOW = 1_800_000_000_000


def env(server_ts=None, sent=NOW - 100, recv=NOW, skew=None):
    return SimpleNamespace(server_ts=server_ts, sent_ms=sent, recv_ms=recv, latency_ms=recv - sent,
                           skew_ms=skew if skew is not None else (None if server_ts is None else server_ts - (sent + recv) // 2))


def ticker(ts):
    return BookTicker("BTC_USDT", Decimal(100), Decimal(1), Decimal(101), Decimal(1), ts)


class Client:
    def __init__(self, t, e, rules=True):
        self.t, self.e, self.rules = t, e, rules

    def book_ticker(self, symbol):
        return self.t, self.e

    def symbols(self, syms):
        return ([SimpleNamespace(symbol="BTC_USDT")] if self.rules else []), self.e


class Fresh(unittest.TestCase):
    def test_fresh_quote_passes(self):
        s = fresh.fetch_quote("BTC_USDT", Client(ticker(NOW - 1000), env(NOW - 50)))
        self.assertEqual(s.require(NOW).bid, Decimal(100))

    def test_old_quote_rejected(self):
        s = fresh.fetch_quote("BTC_USDT", Client(ticker(NOW - 6000), env(NOW - 50)))
        with self.assertRaises(fresh.StaleData):
            s.require(NOW)

    def test_limit_boundaries(self):
        self.assertEqual(fresh.stamp("v", "quote", env(), NOW - 5000).require(NOW), "v")
        with self.assertRaises(fresh.StaleData):
            fresh.stamp("v", "quote", env(), NOW - 5001).require(NOW)
        self.assertEqual(fresh.stamp_account("a", NOW - 299_000).require(NOW), "a")
        with self.assertRaises(fresh.StaleData):
            fresh.stamp_account("a", NOW - 301_000).require(NOW)
        with self.assertRaises(fresh.StaleData):
            fresh.Stamped("r", "symbol_rules", NOW - 86_401_000, 0, 0, True).require(NOW)

    def test_future_timestamp_rejected(self):
        with self.assertRaises(fresh.StaleData):
            fresh.stamp("v", "quote", env(), NOW + 60_000).require(NOW)

    def test_falls_back_to_server_time_then_local_receive(self):
        s = fresh.fetch_quote("BTC_USDT", Client(ticker(None), env(NOW - 9000)))   # server clock 9 s behind: skew-corrected
        self.assertTrue(s.exchange_clock)
        self.assertEqual(s.require(NOW).bid, Decimal(100))
        with self.assertRaises(fresh.StaleData):                               # but not 6 s after it was fetched
            s.require(NOW + 6000)
        local = fresh.fetch_quote("BTC_USDT", Client(ticker(None), env(None)))
        self.assertFalse(local.exchange_clock)
        self.assertEqual(local.require(NOW + 1000).bid, Decimal(100))
        with self.assertRaises(fresh.StaleData):
            local.require(NOW + 6000)

    def test_slow_response_rejected(self):
        s = fresh.stamp("v", "quote", env(sent=NOW - 6000, recv=NOW), NOW)
        with self.assertRaises(fresh.StaleData):
            s.require(NOW)

    def test_skew_corrected(self):
        # exchange clock 10 s ahead of ours: a quote stamped "now" on their clock is fresh, not future
        s = fresh.stamp("v", "quote", env(skew=10_000, sent=NOW - 50, recv=NOW), NOW + 10_000)
        self.assertEqual(s.require(NOW), "v")

    def test_missing_rules_rejected(self):
        with self.assertRaises(fresh.StaleData):
            fresh.fetch_symbol_rules("BTC_USDT", Client(None, env(NOW), rules=False))
        self.assertEqual(fresh.fetch_symbol_rules("BTC_USDT", Client(None, env(NOW))).kind, "symbol_rules")

    def test_executor_default_quote_uses_the_fresh_helper(self):
        src = (Path(fresh.__file__).parent / "executor.py").read_text(encoding="utf-8")
        self.assertIn("fresh.fetch_quote(symbol).require()", src)

    def test_helper_reads_no_logs_or_reports(self):
        body = Path(fresh.__file__).read_text(encoding="utf-8").split('"""')[2]
        for bad in ("read_text", "open(", "json.load", "reports", "STRATEGY_LOG", ".log"):
            self.assertNotIn(bad, body)


if __name__ == "__main__":
    unittest.main()
