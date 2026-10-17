import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from pionex_lab.exchange.pionex_public import BookTicker, Trade
from pionex_lab.live import shadow_grid as sg
from pionex_lab.paths import Paths
from pionex_lab.swing.grid import simulate


class FakeClient:
    def __init__(self, px):
        self.px, self.trades_list = px, []

    def book_ticker(self, symbol):
        return BookTicker(symbol, Decimal(self.px - 0.5), Decimal(1), Decimal(self.px + 0.5), Decimal(1), 0), None

    def trades(self, symbol, limit=100):
        return list(reversed(self.trades_list))[:limit], None

    def add(self, prices, t0=1000):
        n = len(self.trades_list)
        for k, p in enumerate(prices):
            self.trades_list.append(Trade(f"t{n + k:06d}", Decimal(str(p)), Decimal(1), "BUY", t0 + n + k))
        self.px = prices[-1]


CFG = sg.Config("T_v1", "BTC_USDT", 0.10, 20)


class ShadowGridTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.path = Path(self.tmp.name) / "shadow_grid.db"

    def tearDown(self):
        self.tmp.cleanup()

    def runner(self, client):
        r = sg.Runner(client, sg.Store(self.path), configs=[CFG], clock=lambda: 1.0)
        r.init()
        return r

    def test_start_invests_everything_and_balances(self):
        g, ev = sg.ShadowGrid.start(CFG, 100.0, 1)
        self.assertAlmostEqual(g.equity(100.0) / 1000, 1.0, delta=0.002)       # only fees/spread lost
        self.assertEqual(ev[0]["kind"], "start")
        self.assertGreater(g.q * 100 * 20, 0)
        with self.assertRaises(ValueError):
            sg.ShadowGrid.start(sg.Config("x", "BTC_USDT", 0.1, 200), 100.0, 1)

    def test_strict_crossing_and_grid_profit_identity(self):
        g, _ = sg.ShadowGrid.start(CFG, 100.0, 1)
        lv = g.lv
        i = g.b - 1                                                           # nearest buy level below start
        self.assertEqual(g.on_price(lv[i], 2), [])                            # touching is not crossing
        ev = g.on_price(lv[i] - 0.01, 3)
        self.assertEqual([e["side"] for e in ev], ["BUY"])
        ev = g.on_price(lv[i + 1] + 0.01, 4)                                  # back above the upper level: sell
        self.assertEqual([e["side"] for e in ev], ["SELL"])
        self.assertEqual(g.trips, 1)
        eq = g.equity(lv[i + 1] + 0.01)
        self.assertAlmostEqual(g.snapshot(lv[i + 1] + 0.01)["float_profit"] + g.gp, eq - 1000, places=9)
        self.assertGreater(g.gp, 0)

    def test_matches_candle_simulator_on_a_clean_path(self):
        """Down through 3 levels and back up: same equity as grid.simulate with a touch-free walk (strictly through)."""
        g, _ = sg.ShadowGrid.start(CFG, 100.0, 1)
        lv = g.lv
        down, up = lv[g.b - 3] - 0.001, lv[g.b] + 0.001
        g.on_price(down, 2)
        g.on_price(up, 3)
        bars = [(0, 100.0, 100.0, down, down), (1, down, up, down, up)]
        ref = simulate(bars, g.bottom, g.top, CFG.rows, 1000.0, close_on_exit=False)
        self.assertAlmostEqual(g.gp, ref["grid_profit"], places=6)
        self.assertEqual(g.fills, ref["fills"])

    def test_stop_loss_and_frozen(self):
        g, _ = sg.ShadowGrid.start(CFG, 100.0, 1)
        ev = g.on_price(g.stop_price - 1, 2)
        self.assertEqual(ev[-1]["kind"], "stop")
        self.assertEqual(g.status, "stopped")
        self.assertEqual(g.base, 0.0)
        self.assertEqual(g.on_price(100.0, 3), [])

    def test_runner_replays_trades_dedupes_and_restores(self):
        c = FakeClient(100)
        r = self.runner(c)
        g = r.grids["T_v1"]
        c.add([97.0, 103.0, 99.0])
        r.poll()
        f1 = g.fills
        self.assertGreater(f1, 0)
        r.poll()                                                              # same trades again: nothing new
        self.assertEqual(g.fills, f1)
        db = self.path
        r2 = sg.Runner(c, sg.Store(db), configs=[CFG], clock=lambda: 2.0)
        r2.init()                                                             # restart restores identical state
        g2 = r2.grids["T_v1"]
        self.assertEqual((g2.fills, g2.b, round(g2.cash, 9)), (g.fills, g.b, round(g.cash, 9)))
        r2.poll()
        self.assertEqual(g2.fills, f1)

    def test_gap_is_recorded(self):
        c = FakeClient(100)
        r = self.runner(c)
        c.add([100.0 + (k % 2) * 0.001 for k in range(150)])                  # > 100 trades between polls
        r.poll()
        kinds = [k for (k,) in r.store.db.execute("SELECT kind FROM events")]
        self.assertIn("gap", kinds)

    def test_append_only(self):
        r = self.runner(FakeClient(100))
        with self.assertRaises(Exception):
            r.store.db.execute("UPDATE snaps SET equity=0")
        with self.assertRaises(Exception):
            r.store.db.execute("DELETE FROM events")

    def test_report_and_render(self):
        c = FakeClient(100)
        r = self.runner(c)
        c.add([97.0, 103.0])
        r.poll()
        paths = Paths(Path(self.tmp.name))
        rep = sg.report(paths)
        self.assertEqual(rep["shadow"][0]["id"], "T_v1")
        self.assertIn("Not profit", sg.render(rep))

    def test_frozen_configs(self):
        self.assertEqual([c.id for c in sg.CONFIGS], ["BTC_narrow_v1", "BTC_medium_v1", "BTC_wide_v1", "ETH_medium_v1"])
        for c in sg.CONFIGS:
            self.assertGreaterEqual(c.invest / c.rows, 10.0)


if __name__ == "__main__":
    unittest.main()
