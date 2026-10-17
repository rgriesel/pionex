import json
import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from pionex_lab.exchange.pionex_public import BookTicker, Kline
from pionex_lab.live import forward_shadow as fs
from pionex_lab.swing.cta import DAY

DAY0 = 20_000 * DAY                                  # a 00:00 UTC open
NOW = DAY0 / 1000 + 120                              # two minutes after the close
BTC, ETH = "BTC_USDT", "ETH_USDT"
CANARY = fs.Book("canary", "vol", (BTC, ETH), 100.0, "canary", swing_file="state_canary.json")
DEF = fs.Book("defensive", "vol", (BTC, ETH), 1000.0, "def", swing_file="state.json")
DON = fs.Book("donchian_c1", "vol", (BTC, ETH), 1000.0, "don", donchian=True, note=fs.C1_LABEL)


class Rules:
    def __init__(self, sym):
        self.symbol, self.base_precision = sym, 4
        self.min_amount, self.min_dump_size = Decimal("10"), Decimal("0.0001")


class FakeClient:
    def __init__(self, n=200, bid=100.0, ask=100.1, last_close=None, with_today=True):
        self.n, self.bid, self.ask, self.with_today, self.quote_calls = n, bid, ask, with_today, 0
        self.last_close = last_close

    def klines(self, symbol, interval, end_time=None, limit=500):
        out = []
        for i in range(self.n):                      # steady uptrend, noisy enough for a non-zero vol
            t = DAY0 - (self.n - i) * DAY
            c = 50.0 * 1.004 ** i * (1.01 if i % 2 else 0.99)
            out.append(Kline(t, Decimal(str(c * 0.999)), Decimal(str(c)), Decimal(str(c)), Decimal(str(c)), Decimal(1)))
        if self.with_today:                          # the unfinished current-day bar, with a crazy close
            c = self.last_close if self.last_close is not None else 1e-6
            out.append(Kline(DAY0, Decimal(100), Decimal(100), Decimal(1), Decimal(str(c)), Decimal(1)))
        return out, None

    def book_ticker(self, symbol):
        self.quote_calls += 1
        return BookTicker(symbol, Decimal(str(self.bid)), Decimal(1), Decimal(str(self.ask)), Decimal(1), 0), None

    def symbols(self, symbols):
        return [Rules(s) for s in symbols], None


class ForwardShadowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "forward_shadow.db"

    def tearDown(self):
        self.tmp.cleanup()

    def runner(self, client, books, clock=lambda: NOW, **kw):
        return fs.Runner(client, fs.Store(self.path), books=books, clock=clock, **kw)

    def rows(self, sql):
        return sqlite3.connect(self.path).execute(sql).fetchall()

    def test_signals_use_closed_bars_only(self):
        a, b = FakeClient(last_close=1e-6), FakeClient(last_close=1e6)         # wildly different unfinished bar
        ra, meta = fs.build_series(a, BTC, int(DAY0 + 120_000))
        rb, _ = fs.build_series(b, BTC, int(DAY0 + 120_000))
        self.assertEqual(ra, rb)
        self.assertEqual(ra[-1][0], DAY0 - DAY)                                # last bar is yesterday's
        ta = fs.targets_for(DEF, {BTC: ra, ETH: ra})["weights"]
        tb = fs.targets_for(DEF, {BTC: rb, ETH: rb})["weights"]
        self.assertEqual(ta, tb)
        self.assertGreater(sum(ta.values()), 0)
        # and a decision made before the 60 s delay is not taken at all
        r = self.runner(a, [DEF], clock=lambda: DAY0 / 1000 + 10)
        r.poll()
        self.assertEqual(self.rows("SELECT * FROM decisions"), [])

    def test_waits_when_yesterdays_bar_is_missing(self):
        c = FakeClient()
        c.n = 150
        orig = c.klines
        c.klines = lambda *a, **k: ([x for x in orig(*a, **k)[0] if x.open_time != DAY0 - DAY], None)
        self.runner(c, [DEF]).poll()
        self.assertEqual(self.rows("SELECT * FROM decisions"), [])
        self.assertEqual(self.rows("SELECT * FROM fills"), [])

    def test_fills_buy_ask_sell_bid_with_fee(self):
        rules = {BTC: Rules(BTC)}
        cash, hold, fills, _ = fs.execute(1000.0, {}, {BTC: 0.5}, {BTC: (100.0, 100.2)}, rules, 1000.0)
        f = fills[0]
        self.assertEqual((f["side"], f["price"]), ("BUY", 100.2))
        self.assertAlmostEqual(f["fee"], f["qty"] * 100.2 * 0.0005)
        self.assertAlmostEqual(cash, 1000.0 - f["qty"] * 100.2 * 1.0005)
        self.assertLessEqual(f["qty"] * 100.2 * 1.0005, 500.0 + 1e-9)
        cash2, hold2, fills2, _ = fs.execute(cash, hold, {}, {BTC: (110.0, 110.2)}, rules, 1000.0)
        s = fills2[0]
        self.assertEqual((s["side"], s["price"], hold2), ("SELL", 110.0, {}))
        self.assertAlmostEqual(cash2, cash + s["qty"] * 110.0 * (1 - 0.0005))

    def test_band_and_minimum_buy(self):
        rules = {BTC: Rules(BTC)}
        # weight already 0.49, target 0.50: inside the 2% band, no trade
        q = 0.49 * 1000 / 100.0
        _, _, fills, _ = fs.execute(510.0, {BTC: q}, {BTC: 0.5}, {BTC: (100.0, 100.1)}, rules, 1000.0)
        self.assertEqual(fills, [])
        # canary: a 9 USDT buy on 100 USDT is skipped, never forced to 10
        _, _, fills, _ = fs.execute(100.0, {}, {BTC: 0.09}, {BTC: (100.0, 100.1)}, rules, 100.0)
        self.assertEqual(fills, [])

    def test_idempotent_daily_rebalance_and_restart(self):
        c = FakeClient()
        r = self.runner(c, [DEF, CANARY])
        r.poll()
        r.poll()
        n_fills = self.rows("SELECT COUNT(*) FROM fills")[0][0]
        self.assertGreater(n_fills, 0)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM decisions")[0][0], 2)
        r2 = self.runner(c, [DEF, CANARY])                                      # restart: new process, same db
        r2.poll()
        self.assertEqual(self.rows("SELECT COUNT(*) FROM decisions")[0][0], 2)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM fills")[0][0], n_fills)
        dec = self.rows("SELECT book,day,late_s FROM decisions ORDER BY book")
        self.assertEqual({d[1] for d in dec}, {DAY0})
        self.assertAlmostEqual(dec[0][2], 120.0, delta=1)                       # flagged late relative to 00:00 UTC
        # next UTC day rebalances again (bars for the new day come from a fresh client at the next open)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM equity WHERE kind='rebalance'")[0][0], 2)

    def test_quotes_and_equity_marked_at_bid(self):
        c = FakeClient(bid=100.0, ask=100.5)
        self.runner(c, [DEF]).poll()
        q = self.rows("SELECT symbol,bid,ask,purpose FROM quotes")
        self.assertEqual({(x[1], x[2], x[3]) for x in q}, {(100.0, 100.5, "fill")})
        fills = self.rows("SELECT side,price FROM fills")
        self.assertTrue(fills and all(f == ("BUY", 100.5) for f in fills))
        eq, cash, hold = self.rows("SELECT equity,cash,holdings FROM equity")[0]
        self.assertAlmostEqual(eq, cash + sum(v * 100.0 for v in json.loads(hold).values()))
        self.assertLess(eq, 1000.0)                                             # paid fee + spread

    def test_canary_never_buys_below_ten_usdt(self):
        c = FakeClient()
        self.runner(c, [CANARY]).poll()
        for notional, in self.rows("SELECT notional FROM fills WHERE side='BUY'"):
            self.assertGreaterEqual(notional, 10.0)

    def test_append_only(self):
        self.runner(FakeClient(), [DEF]).poll()
        db = sqlite3.connect(self.path)
        for t in ("decisions", "quotes", "fills", "equity", "books"):
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute(f"UPDATE {t} SET ts=0")
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute(f"DELETE FROM {t}")
        self.assertGreater(db.execute("SELECT COUNT(*) FROM decisions").fetchone()[0], 0)

    def test_donchian_book_is_labelled_and_sized(self):
        rows, _ = fs.build_series(FakeClient(), BTC, int(DAY0 + 120_000))
        t = fs.targets_for(DON, {BTC: rows, ETH: rows})
        self.assertEqual(set(t["weights"]), {BTC, ETH} if t["weights"] else set())
        self.assertTrue(all(0 < v <= 1 for v in t["weights"].values()))
        self.runner(FakeClient(), [DON]).poll()
        rep = fs.report(type("P", (), {"root": self.dir})(), now_ms=int(NOW * 1000))
        self.assertEqual(rep["books"][0]["label"], fs.C1_LABEL)
        self.assertIn("PASS - Red Team pending, not a candidate", fs.render(rep))
        self.assertIn("paper only", fs.render(rep))

    def test_reconciliation_flags_divergence(self):
        sd = self.dir / "swing"
        sd.mkdir()
        c = FakeClient()
        r = self.runner(c, [DEF], swing_dir=sd)
        r.poll()
        tgt = json.loads(self.rows("SELECT targets FROM decisions")[0][0])
        (sd / "state.json").write_text(json.dumps({"updated": "1999-01-01T00:00:00", "next_targets": tgt}))
        self.assertIsNone(fs.reconcile(DEF, DAY0, tgt, sd))                     # stale: cannot compare
        upd = __import__("datetime").datetime.fromtimestamp(NOW + 60, __import__("datetime").timezone.utc).isoformat()
        (sd / "state.json").write_text(json.dumps({"updated": upd, "next_targets": tgt}))
        self.assertEqual(fs.reconcile(DEF, DAY0, tgt, sd)[0], "ok")
        bad = {BTC: tgt[BTC] + 0.05}
        (sd / "state.json").write_text(json.dumps({"updated": upd, "next_targets": bad}))
        self.assertEqual(fs.reconcile(DEF, DAY0, tgt, sd)[0], "DIVERGED")
        r.last_recon = 0
        r.poll()
        self.assertEqual(self.rows("SELECT status FROM recon")[0][0], "DIVERGED")


if __name__ == "__main__":
    unittest.main()
