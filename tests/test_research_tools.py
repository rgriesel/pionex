"""Strategy zoo, factor engine and order-book depth parser (synthetic data only)."""
import io
import math
import unittest
import zipfile

from pionex_lab.data import depth
from pionex_lab.swing import factors, zoo


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
