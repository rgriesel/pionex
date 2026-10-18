"""Pionex funding carry study (synthetic data only)."""
import unittest

from pionex_lab.swing import carry_pionex as cp

H = 3_600_000


class FakeClient:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, path, params=None):
        self.calls.append(params)
        class E: pass
        e = E()
        e.data = {"rates": self.pages.pop(0) if self.pages else []}
        return e


class CarryPionex(unittest.TestCase):
    def test_fetch_funding_pages_back_and_sorts(self):
        p1 = [{"fundingTime": 10_000 - 8 * H * i, "fundingRate": "0.0001"} for i in range(500)]
        p2 = [{"fundingTime": 10_000 - 8 * H * (500 + i), "fundingRate": "0.0002"} for i in range(3)]
        c = FakeClient([p1, p2])
        out = cp.fetch_funding(c, "BTC_USDT_PERP")
        self.assertEqual(len(out), 503)
        self.assertEqual(out, sorted(out))
        self.assertEqual(c.calls[1]["endTime"], min(t for t, _ in out[3:]) - 1)

    def test_align_keeps_common_hours(self):
        rows = cp.align({0: (1, 2), H: (2, 3)}, {H: (5, 6), 2 * H: (7, 8)})
        self.assertEqual(rows, [(H, 2, 3, 5, 6)])

    def good(self, annual=0.06, days=400, third=(1, 1, 1), dd=0.001):
        a = {"per_year_on_capital_3x": annual, "thirds": list(third), "max_drawdown": dd}
        return {"days": days, "always": a}

    def test_verdicts(self):
        self.assertEqual(cp.verdict({"BTC_USDT": self.good()})[0], "PASS")
        self.assertEqual(cp.verdict({"BTC_USDT": self.good(annual=0.03)})[0], "FAIL")
        self.assertEqual(cp.verdict({"BTC_USDT": self.good(third=(1, 1, -1))})[0], "FAIL")
        self.assertEqual(cp.verdict({"BTC_USDT": self.good(dd=0.02)})[0], "FAIL")
        self.assertEqual(cp.verdict({"BTC_USDT": self.good(days=100)})[0], "INSUFFICIENT")


if __name__ == "__main__":
    unittest.main()
