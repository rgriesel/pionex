"""Q6 tokenised sleeve: calendar rows are lagged and lookahead-free, costs and window logic behave (synthetic data only)."""
import unittest

from pionex_lab.swing import cta, tokenised as tk
from pionex_lab.swing.cta import DAY
from tests.test_overlays import make_data

D0 = 100 * DAY


def bars(n=300, skip_weekends=True):
    out, p = [], 100.0
    for i in range(n):
        t = D0 + i * DAY
        if skip_weekends and (t // DAY) % 7 in (2, 3):             # 2 non-trading days a week
            continue
        p *= 1.002
        out.append((t, p, p))
    return out


class TokenisedTests(unittest.TestCase):
    def test_rows_lagged_and_flat_on_gaps(self):
        b = bars()
        rows = tk.calendar_rows(b)
        closes = {t: c for t, _, c in b}
        for t, r in list(rows.items())[130:200]:
            prev = t - DAY
            known = max(d for d in closes if d <= prev)
            self.assertEqual(r["o"], closes[known])               # open = previous day's (forward-filled) close
            self.assertEqual(r["c"], r["o"])
        gap = [t for t in rows if t not in closes and t - DAY not in closes and t - 2 * DAY in closes]
        self.assertTrue(gap)

    def test_no_lookahead_features(self):
        b = bars()
        a = tk.calendar_rows(b)
        cut = D0 + 200 * DAY
        c = tk.calendar_rows([x for x in b if x[0] <= cut])
        for t in c:
            if t <= cut:
                for k in ("o", "r20", "r60", "r120", "vol", "age"):
                    x, y = a[t][k], c[t][k]
                    self.assertTrue(x == y or (x != x and y != y), (t, k))

    def test_costs(self):
        self.assertAlmostEqual(tk.costs()["NVDAX_USDT"], cta.SIDE + 0.5 / 2 / 1e4)
        self.assertAlmostEqual(tk.costs(4.0)["BTC_USDT"], 4 * cta.COST["BTC_USDT"])
        self.assertEqual(set(tk.costs()), set(tk.COINS_15))

    def test_trim_and_same_days(self):
        rows = {s: tk.calendar_rows(bars()) for s in tk.SLEEVE}
        crypto = make_data(days=420, coins=cta.UNIVERSE[:3])
        data = tk.trim({**crypto, **rows})
        end = min(max(r) for r in data.values())
        self.assertTrue(all(max(r) == end for r in data.values()))
        sim = cta.simulate(data, tk.RULE, tk.SIZING, 0, coins=cta.UNIVERSE[:3] + tk.SLEEVE, target=0.6, cost=tk.costs())
        self.assertTrue(sim)
        self.assertEqual(len(tk.sleeve_contrib([(D0, {"QQQX_USDT": 0.01, "BTC_USDT": 1.0})], [D0 - DAY])), 1)
        self.assertAlmostEqual(tk.sleeve_contrib([(D0, {"QQQX_USDT": 0.01, "BTC_USDT": 1.0})], [D0 - DAY])[0], 0.01)


if __name__ == "__main__":
    unittest.main()
