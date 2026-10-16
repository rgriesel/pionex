"""CLO-17 flow module: z-score window excludes today, partial IC, hook factors, taker zip parsing."""
import io
import math
import unittest
import zipfile

from pionex_lab.data import binance_vision as bv
from pionex_lab.swing import flow
from pionex_lab.swing.cta import DAY


class FlowTests(unittest.TestCase):
    def test_z_excludes_today_and_needs_full_window(self):
        tk = {i * DAY: (100.0, 50.0) for i in range(400)}
        tk[399 * DAY] = (100.0, 90.0)                    # a spike today
        for i in range(380, 399):
            tk[i * DAY] = (100.0, 50.0 + (i % 3))        # make the history have nonzero std
        z = flow.flow_z(tk)
        self.assertNotIn(300 * DAY, z)                   # fewer than 365 days of m5 history
        self.assertGreater(z[399 * DAY], 1.0)            # spike is measured against the history without itself

    def test_partial_ic_removes_return_driven_signal(self):
        # z is a pure function of the day's return, y independent of z once r1/r5 are removed
        n = 500
        closes, c = {}, 100.0
        import random
        rng = random.Random(1)
        for i in range(n):
            c *= 1 + rng.gauss(0, 0.02)
            closes[i * DAY] = c
        z = {i * DAY: 50 * (closes[i * DAY] / closes[(i - 1) * DAY] - 1) for i in range(10, n - 8)}
        r = flow.ic_screen(z, closes)
        self.assertLess(abs(r["partial_ic"]), 0.15)

    def test_hook_returns_factor_only_below_cut(self):
        h = flow.FlowScale({"BTC_USDT": {0: -1.5, DAY: 0.2}, "ETH_USDT": {}})
        self.assertEqual(h(DAY, {"BTC_USDT": 0.3}, None), {"BTC_USDT": 0.5})
        self.assertEqual(h(2 * DAY, {"BTC_USDT": 0.3}, None), {})

    def test_parse_taker(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("x.csv", "1,2,3,4,5,6,7,100,9,10,40,0\n1700000086400000,0,0,0,0,0,0,50,1,1,20,0\n")
        self.assertEqual(bv.parse_taker(buf.getvalue()), [(1, 100.0, 40.0), (1700000086400, 50.0, 20.0)])


if __name__ == "__main__":
    unittest.main()
