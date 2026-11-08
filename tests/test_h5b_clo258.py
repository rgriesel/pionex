"""Synthetic fixtures only. Never load historical prices or evaluate trial 172."""
import inspect
import unittest
from unittest.mock import patch

from pionex_lab.research import h5b_clo258 as model
from research.own_edge_b_clo248 import H, h5_signals


class H5bChecks(unittest.TestCase):
    def bars(self, side=1):
        b = [(100., 110., 90., 100.) for _ in range(180)]
        b[72] = (110., 116., 109., 115.)
        b[73] = (114., 117., 107., 108.)
        for k in range(74, len(b)):
            b[k] = (108., 109., 107., 108.)
        if side == -1:
            b = [tuple(200-x for x in (o, l, h, c)) for o, h, l, c in b]
        return b

    def run_case(self, b=None, signals=None, **kwargs):
        if b is None:
            b = self.bars()
        if signals is None:
            signals = [(72, 1, 8.)]
        with patch.object(model, 'h5_signals', return_value=iter(signals)):
            return model.h5b(b, 0, **kwargs)

    def test_reuses_parent_generator_and_frozen_doc(self):
        self.assertIs(model.h5_signals, h5_signals)
        doc = inspect.getdoc(model.h5b)
        for token in ('trial 172', 'SAST', 'PREPARATION ONLY', '>=100', 'maxReviewRounds 2'):
            self.assertIn(token, doc)

    def test_real_parent_signal_integration_on_synthetic_compression(self):
        b = [(100., 110., 90., 100.)] * 560
        for k in range(378, len(b)):
            b[k] = (100., 102., 98., 100.)
        b[450] = (102., 104., 101., 103.)
        b[451] = (103., 104., 100., 101.)
        b[452] = (101., 102., 99., 100.)
        signals = list(h5_signals(b))
        self.assertTrue(any(i == 450 and side == 1 for i, side, _ in signals))
        ts, _ = model.h5b(b, 0)
        t = next(x for x in ts if x['signal_time'] == 450*H)
        self.assertEqual((t['confirmation_time'], t['entry_time'], t['exit_reason']),
                         (451*H, 452*H, 'tp'))

    def test_short_confirmation_next_open_and_full_notional(self):
        ts, events = self.run_case()
        t = ts[0]
        self.assertEqual(events, [])
        self.assertEqual((t['side'], t['entry_time'], t['confirmation_time']), (-1, 74*H, 73*H))
        self.assertEqual((t['entry'], t['stop'], t['tp'], t['notional']), (108., 119., 100., 1.))
        self.assertEqual((t['exit_reason'], t['hours'], t['exit_time']), ('time', 96, 170*H))
        self.assertEqual(t['inventory_notional_hours'], 96.)

    def test_long_symmetric_geometry(self):
        t = self.run_case(self.bars(-1), [(72, -1, 8.)])[0][0]
        self.assertEqual((t['side'], t['stop'], t['entry'], t['tp']), (1, 81., 92., 100.))

    def test_pending_and_position_ignore_signals(self):
        ts, _ = self.run_case(signals=[(72, 1, 8.), (73, 1, 8.), (80, 1, 8.)])
        self.assertEqual(len(ts), 1)

    def test_first_return_only_and_fourth_bar_inclusive(self):
        b = self.bars()
        for k in (73, 74, 75):
            b[k] = (114., 117., 111., 115.)
        b[76] = (114., 117., 107., 108.)
        t = self.run_case(b)[0][0]
        self.assertEqual(t['entry_time'], 77*H)
        b[76] = (114., 117., 111., 115.)
        self.assertEqual(self.run_case(b)[0], [])  # bar 77 is too late

    def test_inside_boundary_is_confirmation(self):
        b = self.bars()
        b[73] = (114., 117., 109., 110.)
        self.assertEqual(self.run_case(b)[0][0]['confirmation_time'], 73*H)

    def test_invalid_geometry_skips_without_waiting_for_better_open(self):
        b = self.bars()
        b[74] = (99., 109., 98., 108.)
        ts, events = self.run_case(b)
        self.assertEqual(ts, [])
        self.assertEqual(events[-1]['reason'], 'invalid_geometry')

    def test_stop_before_tp_on_entry_bar_both_sides(self):
        for side in (1, -1):
            b = self.bars(side)
            b[74] = (108., 121., 98., 108.) if side == 1 else (92., 102., 79., 92.)
            t = self.run_case(b, [(72, side, 8.)])[0][0]
            self.assertEqual(t['exit_reason'], 'stop')
            self.assertEqual(t['hours'], 1)
            self.assertEqual(t['exit'], 119. if side == 1 else 81.)

    def test_adverse_stop_gap_both_sides(self):
        for side in (1, -1):
            b = self.bars(side)
            b[75] = (125., 126., 124., 125.) if side == 1 else (75., 76., 74., 75.)
            t = self.run_case(b, [(72, side, 8.)])[0][0]
            self.assertEqual(t['exit'], 125. if side == 1 else 75.)
            self.assertEqual(t['exit_reason'], 'stop')
            self.assertEqual(t['hours'], 1)

    def test_tp_gap_gets_no_improvement(self):
        b = self.bars()
        b[75] = (95., 96., 94., 95.)
        t = self.run_case(b)[0][0]
        self.assertEqual((t['exit'], t['exit_reason']), (100., 'tp'))

    def test_time_open_ignores_later_extremes(self):
        b = self.bars()
        b[170] = (108., 150., 50., 108.)
        t = self.run_case(b)[0][0]
        self.assertEqual((t['exit'], t['exit_reason'], t['hours']), (108., 'time', 96))

    def test_stop_gap_at_time_open_still_worse(self):
        b = self.bars()
        b[170] = (125., 126., 124., 125.)
        t = self.run_case(b)[0][0]
        self.assertEqual((t['exit'], t['exit_reason'], t['hours']), (125., 'stop', 96))

    def test_missing_windows_and_entry_never_fill(self):
        for k, reason in ((5, 'missing_lookback'), (73, 'missing_confirmation'), (74, 'missing_entry')):
            b = self.bars()
            b[k] = None
            ts, events = self.run_case(b)
            self.assertEqual(ts, [])
            self.assertIn(reason, [x['reason'] for x in events])

    def test_position_gap_or_end_halts_coin_no_silent_loss_drop(self):
        for k in (75, 170):
            b = self.bars()
            b[k] = None
            ts, events = self.run_case(b, [(72, 1, 8.), (80, 1, 8.)])
            self.assertEqual(ts, [])
            self.assertEqual(events, [dict(signal=72, entry=74, reason='unresolved_position_gap_or_end')])
        self.assertIn('unresolved', self.run_case(self.bars()[:100])[1][-1]['reason'])

    def test_fixed_spread_funding_and_cost_stress(self):
        for side in (1, -1):
            for mult in (1, 2, 3, 4):
                t = self.run_case(self.bars(side), [(72, side, 8.)], mult=mult)[0][0]
                self.assertEqual(t['execution_cost_bps'], 26.*mult)
                self.assertEqual(t['funding_bps'], 12.)
                self.assertEqual(t['net_bps'], -26.*mult-12.)
        self.assertEqual(model.execution_cost(8, 2, 1.5), (38., 1.))

    def test_full_notional_gross_and_cost_identity(self):
        b = self.bars()
        b[74] = (108., 109., 99., 101.)
        t = self.run_case(b)[0][0]
        self.assertAlmostEqual(t['gross_bps'], (1-100/108)*10000)
        self.assertAlmostEqual(t['net_bps'], t['gross_bps']-26.-.125)

    def test_prefix_invariance_no_future_excursion_leak(self):
        b = self.bars()
        b[74] = (108., 109., 99., 101.)
        t = self.run_case(b)[0][0]
        b[75:] = [(150., 151., 149., 150.)]*len(b[75:])
        self.assertEqual(self.run_case(b)[0][0], t)
        self.assertEqual(self.run_case(b[:75])[0][0], t)

    def test_bad_data_and_costs_rejected(self):
        for bad in ((100., 90., 110., 100.), (float('nan'), 110., 90., 100.)):
            b = self.bars()
            b[73] = bad
            with self.assertRaises(ValueError):
                self.run_case(b)
        for kwargs in ({'mult': 0}, {'half_spread_bps': -1}, {'half_spread_bps': float('nan')}):
            with self.assertRaises(ValueError):
                self.run_case(**kwargs)


if __name__ == '__main__':
    unittest.main()
