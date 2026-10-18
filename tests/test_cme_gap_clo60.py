import importlib.util
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location('cme_gap', Path(__file__).resolve().parents[1] / 'research/cme_gap_clo60.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class CMEGapTests(unittest.TestCase):
    def test_dst_calendar(self):
        for day, expected in [(date(2024, 1, 7), 0), (date(2024, 7, 7), 23)]:
            friday, reopen, entry = m.times(day)
            self.assertEqual(datetime.fromtimestamp(entry / 1000, timezone.utc).hour, expected)
            self.assertEqual(entry - reopen, m.HOUR)
            self.assertEqual((reopen - friday) / m.HOUR, 49)

    def test_dst_transition_weekends(self):
        for day, hours in [(date(2024, 3, 10), 48), (date(2024, 11, 3), 50)]:
            friday, reopen, _ = m.times(day)
            self.assertEqual((reopen - friday) / m.HOUR, hours)

    def test_minimum_hold_and_next_open(self):
        bars = {i * m.HOUR: (101., 105., 90., 102.) for i in range(121)}
        bars[4 * m.HOUR] = (103., 105., 90., 104.)
        t = m.trade(bars, 0, 100)
        self.assertEqual(t['hours'], 4)
        self.assertEqual(t['exit'], 103.)
        self.assertEqual(t['reason'], 'target')

    def test_stop_overshoot_and_timeout(self):
        bars = {i * m.HOUR: (100., 101., 99., 100.) for i in range(121)}
        self.assertEqual(m.trade(bars, 0, 110)['hours'], 120)
        bars[3 * m.HOUR] = (100., 100., 90., 94.)
        bars[4 * m.HOUR] = (90., 95., 89., 94.)
        t = m.trade(bars, 0, 110)
        self.assertEqual(t['reason'], 'stop')
        self.assertLess(t['net_1x'], -.10)

    def test_costs_both_sides(self):
        self.assertAlmostEqual(m.net(100, 100), (1 - .0007) / (1 + .0007) - 1)
        self.assertLess(m.net(100, 110, 4), m.net(100, 110))


if __name__ == '__main__':
    unittest.main()
