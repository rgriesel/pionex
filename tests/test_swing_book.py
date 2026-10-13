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
            self.assertGreater(st["equity"], 100.0)                       # steady uptrend, held long
            self.assertTrue(st["next_targets"])
            again = sb.run(paths, client=Client(), now_ms=now)
            self.assertEqual(len(again["history"]), len(st["history"]))  # idempotent: no day booked twice


if __name__ == "__main__":
    unittest.main()
