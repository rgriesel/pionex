"""Paper swing book (synthetic candles only)."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from pionex_lab.swing import cta, swing_book as sb

DAY = 86_400_000


class Book(unittest.TestCase):
    def test_targets_follow_the_vote_and_cap_at_full_capital(self):
        up = [(k * DAY, 100 * 1.01 ** k, 100 * 1.01 ** (k + 1)) for k in range(200)]
        down = [(k * DAY, 100 * 0.99 ** k, 100 * 0.99 ** (k + 1)) for k in range(200)]
        t = sb.targets({"A": up, "B": down, "C": up[:50]})
        self.assertEqual(t["available"], 2)                              # C too young
        self.assertIn("A", t["weights"])
        self.assertNotIn("B", t["weights"])
        self.assertLessEqual(sum(t["weights"].values()), 1.0 + 1e-9)
        g = sb.targets({"A": up, "B": down, "C": up[:50]}, sizing="equal")
        self.assertEqual(g["weights"], {"A": 0.5})                       # growth book: 1/N per IN coin

    def test_forward_paper_run_books_returns_and_costs(self):
        from datetime import datetime, timezone
        start = int(datetime.fromisoformat(sb.FORWARD_START).replace(tzinfo=timezone.utc).timestamp() * 1000)
        first = start - 200 * DAY
        prices = {s: [100 * (1.003 if k % 2 else 1.001) ** i for i in range(210)] for k, s in enumerate(cta.UNIVERSE)}

        class Client:
            def klines(self, sym, iv, limit=300):
                p = prices[sym]
                return [SimpleNamespace(open_time=first + i * DAY, open=p[i], close=p[i + 1]) for i in range(len(p) - 1)], None
        with tempfile.TemporaryDirectory() as d:
            paths = SimpleNamespace(root=Path(d))
            now = first + 209 * DAY + 1
            st = sb.run(paths, client=Client(), now_ms=now)
            self.assertGreater(len(st["history"]), 3)
            self.assertGreater(st["equity"], 1000.0)                      # steady uptrend, held long, 1000 USDT book
            self.assertTrue(st["next_targets"])
            again = sb.run(paths, client=Client(), now_ms=now)
            self.assertEqual(len(again["history"]), len(st["history"]))  # idempotent: no day booked twice
            can = sb.run(paths, client=Client(), now_ms=now, book="canary")
            self.assertEqual(set(can["next_targets"]), {"BTC_USDT", "ETH_USDT"})
            self.assertEqual(can["paper_usdt"], 100.0)
            self.assertTrue(all(v >= 10.0 for v in can["next_targets_usdt"].values()))


    def test_todays_open_is_booked_before_the_candle_closes(self):
        from datetime import datetime, timezone
        start = int(datetime.fromisoformat(sb.FORWARD_START).replace(tzinfo=timezone.utc).timestamp() * 1000)
        first = start - 200 * DAY
        p = [100 * 1.002 ** i for i in range(206)]

        class Client:
            def klines(self, sym, iv, limit=300):        # 205 candles; the last one opened 1 h ago
                return [SimpleNamespace(open_time=first + i * DAY, open=p[i], close=p[i + 1] if i < 204 else 999.0)
                        for i in range(205)], None
        with tempfile.TemporaryDirectory() as d:
            now = first + 204 * DAY + 3_600_000
            st = sb.run(SimpleNamespace(root=Path(d)), client=Client(), now_ms=now, book="canary")
        self.assertEqual(st["last_day"], first + 204 * DAY)                 # rebalanced at today's open
        self.assertNotIn(999.0, [v["r20_pct"] for v in st["signals"].values()])
        self.assertAlmostEqual(st["signals"]["BTC_USDT"]["r20_pct"], round(100 * (1.002 ** 20 - 1), 1))  # closed days only


class Bookkeeping(unittest.TestCase):
    def test_weights_drift_with_prices(self):
        w, port = cta.drift({"A": 0.5}, {"A": 0.10})
        self.assertAlmostEqual(port, 0.05)
        self.assertAlmostEqual(w["A"], 0.55 / 1.05)                       # 55 of 105 after A rose 10%

    def test_band_minimum_buy_and_gross_cap(self):
        zero = {"A": 0.0, "B": 0.0}
        new, paid, traded = cta.rebalance({"A": 0.30}, {"A": 0.31}, {"A"}, cost=zero)
        self.assertEqual((new, traded), ({"A": 0.30}, 0.0))               # inside the 2% band
        new, _, traded = cta.rebalance({}, {"A": 0.05}, {"A"}, equity=100.0, cost=zero)
        self.assertEqual((new, traded), ({}, 0.0))                        # 5 USDT buy is below the minimum
        new, _, _ = cta.rebalance({"A": 0.05}, {}, {"A"}, equity=100.0, cost=zero)
        self.assertEqual(new, {})                                         # small sells are allowed
        new, _, traded = cta.rebalance({"A": 0.51}, {"A": 0.50, "B": 0.50}, {"A", "B"}, cost=zero)
        self.assertAlmostEqual(sum(new.values()), 1.0)                    # kept 51% + new 50% re-capped
        self.assertAlmostEqual(traded, 0.51)
        new, _, _ = cta.rebalance({"A": 0.3}, {}, set(), cost=zero)
        self.assertEqual(new, {"A": 0.3})                                 # no price today: cannot trade

    def test_missing_bar_is_marked_not_peeked(self):
        def rows(skip=None, jump_from=None):
            out = {}
            for i in range(131):
                if i == skip:
                    continue
                o = 110.0 if jump_from is not None and i >= jump_from else 100.0
                out[i * DAY] = {"o": o, "c": o, "ema": o, "vol": 0.5, "age": i, "r20": 0.1, "r60": 0.1, "r120": 0.1}
            return out
        data = {"A": rows(skip=125, jump_from=126), "B": rows()}
        out = cta.simulate(data, "hold", "equal", band=0.0, cost={"A": 0.0, "B": 0.0}, coins=("A", "B"))
        eq = 1.0
        for _, r, _, _ in out:
            eq *= 1 + r
        self.assertAlmostEqual(eq, 1.05)                                  # half the book in A, A +10% across its gap


if __name__ == "__main__":
    unittest.main()
