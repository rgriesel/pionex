"""Read-only account reader (fake credentials and a fake transport; no network)."""
import hashlib
import hmac
import io
import json
import unittest
import urllib.error

from pionex_lab.exchange import account
from pionex_lab.reporting.report import human_comparison
from pionex_lab.runtime import account_reader
from pionex_lab.util import iso_ms

from helpers import T0, cleanup, tmp_paths

KEY, SECRET = "fake-key-1234567890", "fake-secret-abcdefghij"


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class Credentials(unittest.TestCase):
    def setUp(self):
        self.paths, self.dir = tmp_paths()

    def tearDown(self):
        cleanup(self.dir)

    def env(self, text):
        p = self.paths.root / "t.env"
        p.write_text(text, encoding="utf-8")
        return p

    def test_prefers_official_names_and_never_shows_values(self):
        c = account.load_credentials(self.env(f'OTHER=1\nPIONEX_API_KEY="{KEY}"\nexport PIONEX_API_SECRET={SECRET}\n'))
        for text in (repr(c), str(c), c.source):
            self.assertNotIn(KEY, text)
            self.assertNotIn(SECRET, text)
        self.assertEqual((c._key, c._secret), (KEY, SECRET))

    def test_ambiguity_lists_names_only(self):
        p = self.env(f"PIONEX_MAIN_KEY={KEY}\nPIONEX_TEST_KEY=x\nPIONEX_SECRET={SECRET}\n")
        with self.assertRaises(account.AccountReadError) as cm:
            account.load_credentials(p)
        self.assertIn("PIONEX_TEST_KEY", str(cm.exception))
        self.assertNotIn(KEY, str(cm.exception))
        self.assertNotIn(SECRET, str(cm.exception))


class SignedGet(unittest.TestCase):
    creds = account.Credentials(KEY, SECRET, "test")

    def test_only_allowlisted_read_endpoints(self):
        for path in ("/api/v1/trade/order", "/api/v1/trade/allOrders", "/api/v1/bot/orders/spotGrid/cancel"):
            with self.assertRaises(account.AccountReadError):
                account.signed_get(self.creds, path, opener=lambda *a, **k: self.fail("network touched"))
        from pathlib import Path
        self.assertNotIn("POST", Path(account.__file__).read_text(encoding="utf-8"))   # no write verbs at all

    def test_request_matches_official_signing(self):
        seen = {}

        def opener(req, timeout):
            seen["url"], seen["method"], seen["headers"] = req.full_url, req.get_method(), dict(req.header_items())
            return Resp(json.dumps({"result": True, "data": {"totalInUsdt": "151.5"}}).encode())
        body = account.signed_get(self.creds, "/api/v1/wallet/balancesFull", now_ms=1234567890123, opener=opener)
        self.assertEqual(body["data"]["totalInUsdt"], "151.5")
        self.assertEqual(seen["method"], "GET")
        self.assertEqual(seen["url"], "https://api.pionex.com/api/v1/wallet/balancesFull?timestamp=1234567890123")
        expected = hmac.new(SECRET.encode(), b"GET/api/v1/wallet/balancesFull?timestamp=1234567890123",
                            hashlib.sha256).hexdigest()
        self.assertEqual(seen["headers"]["Pionex-signature"], expected)
        self.assertEqual(seen["headers"]["Pionex-key"], KEY)

    def test_errors_are_scrubbed(self):
        def opener(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 401, "no", {}, io.BytesIO(f"bad key {KEY}".encode()))
        with self.assertRaises(account.AccountReadError) as cm:
            account.signed_get(self.creds, "/api/v1/account/balances", opener=opener)
        self.assertNotIn(KEY, str(cm.exception))
        self.assertIn("<redacted>", str(cm.exception))


class BotReader(unittest.TestCase):
    creds = account.Credentials(KEY, SECRET, "test")
    ALLOWED = {"/api/v1/bot/orders", "/api/v1/bot/orders/spotGrid/order", "/api/v1/bot/orders/futuresGrid/order"}

    def test_bot_allowlist_is_exactly_the_three_get_paths(self):
        self.assertEqual(set(account.BOT_PATHS), self.ALLOWED)
        self.assertEqual({p for p in account.READ_ONLY_PATHS if "/bot/" in p}, self.ALLOWED)
        for path in ("/api/v1/bot/orders/spotGrid/checkParams", "/api/v1/bot/orders/spotGrid/create",
                     "/api/v1/bot/orders/spotGrid/cancel", "/api/v1/bot/orders/futuresGrid/checkParams",
                     "/api/v1/bot/orders/spotGrid/aiStrategy"):
            with self.assertRaises(account.AccountReadError):
                account.signed_get(self.creds, path, opener=lambda *a, **k: self.fail("network touched"))

    def test_reader_sends_only_get_to_allowlisted_paths(self):
        from urllib.parse import urlparse
        seen = []

        def opener(req, timeout):
            seen.append((req.get_method(), urlparse(req.full_url).path, req.data))
            p = seen[-1][1]
            if p == "/api/v1/bot/orders":
                return Resp(json.dumps({"result": True, "data": {"orders": [
                    {"buOrderId": "b1", "buOrderType": "spot_grid", "base": "BTC", "quote": "USDT"},
                    {"buOrderId": "b2", "buOrderType": "futures_grid", "base": "ETH.PERP", "quote": "USDT"}]}}).encode())
            return Resp(json.dumps({"result": True, "data": {"buOrderData": {
                "top": "2", "bottom": "1", "row": 10, "quoteTotalInvestment": "100", "gridProfit": "1.5",
                "realizedProfit": "2.0", "status": "running"}}}).encode())
        paths, d = tmp_paths()
        try:
            rows = account_reader.bots_once(paths, self.creds, now_ms=T0,
                                            get=lambda c, p, q=None: account.signed_get(c, p, q, opener=opener))
            self.assertTrue(seen)
            for method, path, data in seen:
                self.assertEqual(method, "GET")
                self.assertIsNone(data)
                self.assertIn(path, self.ALLOWED)
            self.assertEqual(rows[0]["range"], "1-2")
            self.assertEqual(rows[0]["float_profit"], "0.5")
            self.assertEqual(rows[0]["pair"], "BTC_USDT")
            self.assertNotIn(KEY, rows[0]["raw"])
            c = account_reader.connect(paths, readonly=True)
            self.assertGreater(c.execute("SELECT COUNT(*) FROM bots").fetchone()[0], 0)
            c.close()
        finally:
            cleanup(d)

    def test_missing_permission_is_one_error_row_no_retry(self):
        calls = []

        def get(c, p, q=None):
            calls.append(p)
            raise account.AccountReadError("HTTP 403 on /api/v1/bot/orders: no permission")
        paths, d = tmp_paths()
        try:
            rows = account_reader.bots_once(paths, self.creds, now_ms=T0, get=get)
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(rows), 1)
            self.assertIn("403", rows[0]["error"])
            self.assertFalse(account_reader.bots_due(paths, T0 + 60_000))
            self.assertTrue(account_reader.bots_due(paths, T0 + 3_600_000))
        finally:
            cleanup(d)

    def test_empty_or_odd_list_still_writes_marker_row(self):
        paths, d = tmp_paths()
        try:
            for body in ({"data": {"orders": []}}, {"data": {"orders": ["x", 3]}}):
                rows = account_reader.bots_once(paths, self.creds, now_ms=T0, get=lambda c, p, q=None, b=body: b)
                self.assertEqual(len(rows), 1)
                self.assertIn("no bots parsed", rows[0]["error"])
            self.assertFalse(account_reader.bots_due(paths, T0 + 60_000))
        finally:
            cleanup(d)

    def test_no_write_verbs_in_reader_sources(self):
        from pathlib import Path
        for mod in (account, account_reader):
            text = Path(mod.__file__).read_text(encoding="utf-8")
            for verb in ("POST", "DELETE", "PUT", "method=\"P"):
                self.assertNotIn(verb, text, mod.__name__)


class HumanLine(unittest.TestCase):
    def test_snapshot_store_and_indexed_line(self):
        paths, d = tmp_paths()
        try:
            for i, total in enumerate(("150", "165")):
                row = account_reader.snapshot_once(paths, {}, None, now_ms=T0 + i * 60_000,
                                                   get=lambda c, p, t=total: {"result": True,
                                                                              "data": {"totalInUsdt": t}})
                self.assertIsNone(row["error"])
            from pionex_lab.reporting.report import human_account_series
            series = human_account_series(paths, T0 + 10 * 60_000)
            rows = [{"at": iso_ms(T0 - 60_000)}, {"at": iso_ms(T0 + 30_000)}, {"at": iso_ms(T0 + 90_000)}]
            hc = human_comparison(series, rows)
            self.assertEqual([r["human_equity_usd"] for r in rows], [None, 100.0, 110.0])
            self.assertFalse(hc["comparable"])
            self.assertIn("165.00 USDT", hc["note"])
        finally:
            cleanup(d)


if __name__ == "__main__":
    unittest.main()


class LiveBotListShape(unittest.TestCase):
    def test_results_and_next_page_token(self):
        from pionex_lab.runtime.account_reader import _orders
        items, token = _orders({"data": {"results": [{"buOrderId": "a"}], "nextPageToken": "p2"}, "result": True})
        self.assertEqual((len(items), token), (1, "p2"))     # the shape Pionex returned on 2026-10-17
