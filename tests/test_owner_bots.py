import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pionex_lab.research import owner_bots as ob
from pionex_lab.research import owner_rules as orl


def _raw(status="canceled", close=1_000_000):
    return json.dumps({"summary": {"status": status, "closeTime": close, "createTime": 0, "buOrderType": "futures_grid",
                                   "base": "BTC.PERP", "quote": "USDT",
                                   "buOrderData": {"top": "110", "bottom": "90", "initPrice": "100", "initUsdtInvestment": "10",
                                                   "marginBalance": "11", "gridProfit": "0.2", "row": 20, "leverage": "5",
                                                   "trend": "long", "closedPrice": "105"}}})


class OwnerBots(unittest.TestCase):
    def test_load_bots_finished_only_and_fields(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.db"
            c = sqlite3.connect(p)
            c.execute("CREATE TABLE bots(id INTEGER PRIMARY KEY, at INTEGER, bu_order_id TEXT, raw TEXT)")
            c.execute("INSERT INTO bots(at,bu_order_id,raw) VALUES(1,'a',?)", (_raw(),))
            c.execute("INSERT INTO bots(at,bu_order_id,raw) VALUES(2,'b',?)", (_raw("running", None),))
            c.commit()
            c.close()
            rows = ob.load_bots(p)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertAlmostEqual(r["range_pct"], 0.2)
        self.assertAlmostEqual(r["ret"], 0.1)
        self.assertAlmostEqual(r["float_pnl"], 0.8)
        self.assertFalse(r["closed_outside"])

    def test_spearman_and_perm(self):
        x = list(range(20))
        self.assertAlmostEqual(ob.spearman(x, x), 1.0)
        rho, p = ob.perm_p(x, [-v for v in x], n_perm=500)
        self.assertAlmostEqual(rho, -1.0)
        self.assertLess(p, 0.01)

    def test_no_lookahead_daily_closes(self):
        bars = [(i * 3_600_000, 1, 1, 1, float(i)) for i in range(24 * 5)]
        d = orl.daily_closes(bars, 24 * 3)
        self.assertEqual(len(d), 3)
        self.assertEqual(d[-1], 71.0)

    def test_reflect_inverts_path(self):
        w = [(0, 100.0, 110.0, 90.0, 105.0)]
        t, o, h, l, c = orl.reflect(w)[0]
        self.assertAlmostEqual(o, 100.0)
        self.assertGreater(h, o)
        self.assertLess(c, o)


if __name__ == "__main__":
    unittest.main()
