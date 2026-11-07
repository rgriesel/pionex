import unittest
from pionex_lab.reporting import trade_ledger as tl


class Fake:
    pass


class T(unittest.TestCase):
    def test_avg_cost_realized(self):
        out = tl.avg_cost_realized([("A", "BUY", 2, 10.0, 0.2), ("A", "SELL", 1, 12.0, 0.1), ("A", "SELL", 1, 9.0, 0.0)])
        self.assertEqual(out[0], 0.0)
        self.assertAlmostEqual(out[1], (12 - 10.1) * 1 - 0.1)
        self.assertAlmostEqual(out[2], (9 - 10.1) * 1)

    def test_check_price_strict(self):
        self.assertIsNone(tl.check_price(10, 9, 11))
        self.assertIsNone(tl.check_price(11, 9, 11))
        self.assertAlmostEqual(tl.check_price(11.1, 9, 11), 0.1 / 11 * 1e4)

    def test_equity_lookup(self):
        f = tl._equity_lookup([(10, 1.0), (20, 2.0)])
        self.assertIsNone(f(5))
        self.assertEqual(f(10), 1.0)
        self.assertEqual(f(25), 2.0)

    def test_check_rows_flags_mismatch_and_unavailable(self):
        from types import SimpleNamespace as N

        class C:
            def klines(self, sym, iv, end_time=None, limit=500):
                if sym == "BAD":
                    raise RuntimeError("retention")
                return [N(open_time=0, low=9, high=11)], None
        rows = [dict(symbol="OK", ts_ms=5000, fill_price=10.0, book="b", side="BUY", note=""),
                dict(symbol="OK2", ts_ms=5000, fill_price=12.0, book="b", side="BUY", note=""),
                dict(symbol="BAD", ts_ms=5000, fill_price=10.0, book="b", side="BUY", note="")]
        rep = tl.check_rows(rows, client=C(), now_ms=10**9)
        self.assertEqual((rep["matched"], rep["mismatched"], rep["kline_unavailable"]), (1, 1, 1))
        self.assertEqual(rep["verdict"], "MISMATCHES")


if __name__ == "__main__":
    unittest.main()
