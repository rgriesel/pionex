import unittest
from datetime import datetime, timezone

from pionex_lab.swing import cta, staggered


def fixture():
    start = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    return {'BTC_USDT': {start + i * cta.DAY: {'o': 100 + i + (i % 7), 'age': i,
             'r20': 0.1 if i % 19 < 11 else -0.1, 'r60': 0.1,
             'r120': -0.1, 'vol': 0.8} for i in range(200)}}


class StaggeredTest(unittest.TestCase):
    def test_daily_parity_including_minimum_buys_and_costs(self):
        data = fixture()
        for capital in (None, 100, 15):
            a = cta.simulate(data, 'tsmom_vote', 'vol', capital=capital, coins=tuple(data))
            b = staggered.simulate(data, capital=capital)
            self.assertEqual(a, b)

    def test_trades_only_on_assigned_weekday_and_drifts_between(self):
        rows = staggered.simulate(fixture(), weekday=2)
        self.assertTrue(any(x[3] > 0 for x in rows))
        for t, _, _, traded in rows:
            if traded:
                self.assertEqual(datetime.fromtimestamp(t/1000, timezone.utc).weekday(), 2)
        self.assertTrue(any(rows[i][2] != rows[i-1][2] and rows[i][3] == 0 for i in range(1, len(rows))))

    def test_decision_uses_previous_close(self):
        data = fixture()
        before = staggered.simulate(data)
        t = before[15][0]
        data['BTC_USDT'][t]['r20'] *= -1
        after = staggered.simulate(data)
        self.assertEqual([x for x in before if x[0] <= t], [x for x in after if x[0] <= t])

    def test_nav_weighted_combination(self):
        books = [[(0, 1., 1., 0.), (1, 0., 1., 0.)], [(0, 0., 0., 0.), (1, 1., 1., 0.)]]
        rows = staggered.combine(books)
        self.assertAlmostEqual(rows[0][1], 0.5)
        self.assertAlmostEqual(rows[1][1], 1/3)
        self.assertAlmostEqual((1+rows[0][1])*(1+rows[1][1]), 2.)
        with self.assertRaises(ValueError):
            staggered.combine([books[0], books[1][1:]])

    def test_kill_criteria(self):
        self.assertEqual(staggered.verdict(1.3, 1.25, 1.2, 1.1), 'PASS')
        self.assertEqual(staggered.verdict(1.3, 1.19, 1.2, 1.1), 'FAIL')
        self.assertEqual(staggered.verdict(1.3, 1.25, 1.2, 1.04), 'FAIL')


if __name__ == '__main__':
    unittest.main()
