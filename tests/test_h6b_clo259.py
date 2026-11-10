"""Synthetic-only H6b preparation; no archive IO or trial-173 evaluation."""
import json
import math
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from pionex_lab.research import h6b_clo259 as m


class FillChecks(unittest.TestCase):
    def fixture(self, side=1):
        bars = [(100., 101., 99., 100. + .1*(k % 2)) for k in range(745)]
        # Signal i=724; submission=725; earliest permitted fill=726.
        for k in range(724, len(bars)):
            bars[k] = (100., 100.5, 100., 100.)
        bars[726] = (100., 100.5, 99.9, 100.)
        if side == -1:
            bars = [(200-o, 200-l, 200-h, 200-c) for o, h, l, c in bars]
        lr, z = [None]*len(bars), [None]*len(bars)
        lr[724], z[724] = side*.04, side*3.
        return bars, (lr, z)

    def case(self, bars=None, stats=None, side=1, **kwargs):
        b, s = self.fixture(side)
        return m.h6b(s if stats is None else stats, b if bars is None else bars, 0, .1, **kwargs)

    def test_delayed_fill_full_notional_and_frozen_geometry_both_sides(self):
        for side in (1, -1):
            ts, events = self.case(side=side)
            t = ts[0]
            self.assertEqual(events, [])
            self.assertEqual((t['submission_time'], t['entry_time'], t['exit_time']),
                             (725*m.H, 726*m.H, 734*m.H))
            self.assertEqual((t['entry'], t['exit'], t['exit_reason'], t['hours']), (100.,100.,'time',8))
            self.assertEqual(t['notional'], 1.)
            self.assertAlmostEqual(t['tp'], 100*math.exp(side*.02))
            self.assertAlmostEqual(t['stop'], 100*math.exp(-side*1.5*t['sd1h']*math.sqrt(8)))

    def test_touch_and_subtick_do_not_fill_submission_extremes_ignored(self):
        for low in (100.,99.95):
            b, _ = self.fixture()
            b[725] = (100., 200., 1., 100.)
            b[726] = (100., 100.5, low, 100.)
            ts, events = self.case(b)
            self.assertEqual(ts, [])
            self.assertEqual(events, [dict(signal=724,reason='expired_unfilled')])

    def test_fourth_bar_fill_and_fifth_bar_expiry(self):
        b, _ = self.fixture()
        b[726], b[729] = b[727], b[726]
        self.assertEqual(self.case(b)[0][0]['entry_time'],729*m.H)
        b[729], b[730] = b[727], b[729]
        self.assertEqual(self.case(b)[0], [])

    def test_pending_and_position_signals_ignored(self):
        b, s = self.fixture()
        for k in (725, 726, 730, 734):
            s[0][k],s[1][k] = .04,3.
        self.assertEqual(len(self.case(b,s)[0]),1)

    def test_threshold_and_lag_boundary(self):
        b,s = self.fixture()
        s[1][724] = 2.999
        self.assertEqual(self.case(b,s)[0],[])
        s[1][724] = 3.
        # Exact lag boundary is ineligible (use leader derived from same math).
        b[724] = (100., 105., 99., 104.)
        s[0][724] = 2*math.log(104/100)
        self.assertEqual(self.case(b,s)[0],[])

    def test_missing_lookback_and_submission_do_not_fill(self):
        for k,reason in ((600,'missing_lookback'),(725,'missing_submission')):
            b,_=self.fixture()
            b[k]=None
            ts,events=self.case(b)
            self.assertEqual(ts,[])
            self.assertIn(reason,[e['reason'] for e in events])

    def test_unknown_pending_or_inventory_halts_coin(self):
        for k,reason in ((726,'unresolved_pending_gap_or_end'),(727,'unresolved_position_gap_or_end'),
                         (734,'unresolved_position_gap_or_end')):
            b,s=self.fixture()
            b[k]=None
            s[0][738],s[1][738]=.04,3.
            ts,events=self.case(b,s)
            self.assertEqual(ts,[])
            self.assertEqual(len(events),1)
            self.assertEqual(events[0]['reason'],reason)

    def test_ambiguous_stop_precedes_tp_both_sides(self):
        for side in (1,-1):
            b,s=self.fixture(side)
            b[726]=(100.,110.,90.,100.)
            t=self.case(b,s)[0][0]
            self.assertEqual(t['exit_reason'],'stop')
            self.assertEqual(t['exit'],t['stop'])

    def test_adverse_fill_open_and_later_gap_never_improve_price(self):
        for side in (1,-1):
            for k in (726,727):
                b,s=self.fixture(side)
                o=90. if side==1 else 110.
                b[k]=(o,o+.1,o-.1,o)
                t=self.case(b,s)[0][0]
                self.assertEqual((t['entry'],t['exit'],t['exit_reason']),(100.,o,'stop'))

    def test_intrabar_fill_does_not_use_prefill_tp_extreme(self):
        b,_=self.fixture()
        b[726]=(100.,110.,99.9,100.)
        self.assertEqual(self.case(b)[0][0]['exit_reason'],'time')
        b[726]=(100.,110.,99.9,105.)
        self.assertEqual(self.case(b)[0][0]['exit_reason'],'tp')

    def test_time_open_ignores_later_extremes_but_stop_gap_wins(self):
        b,_=self.fixture()
        b[734]=(100.,200.,1.,100.)
        self.assertEqual(self.case(b)[0][0]['exit_reason'],'time')
        b[734]=(90.,200.,1.,100.)
        self.assertEqual(self.case(b)[0][0]['exit'],90.)

    def test_costs_all_friction_stressed_funding_unchanged(self):
        for side in (1,-1):
            for mult in (1,2,3,4):
                t=self.case(side=side,mult=mult)[0][0]
                self.assertEqual((t['execution_cost_bps'],t['funding_bps']), (22.*mult,1.))
                self.assertAlmostEqual(t['net_bps'],t['gross_bps']-22.*mult-1.)
        self.assertEqual(m.execution_cost(8,2,1.5),(30.,1.))

    def test_frozen_signal_and_future_prefix_invariance(self):
        b,s=self.fixture()
        b[727]=(100.,110.,100.,100.)
        t=self.case(b,s)[0][0]
        b[728:]=[(200.,210.,190.,200.)]*len(b[728:])
        self.assertEqual(self.case(b,s)[0][0],t)
        self.assertEqual(m.h6b((s[0][:728],s[1][:728]),b[:728],0,.1)[0][0],t)

    def test_validation_and_fingerprints(self):
        b,s=self.fixture()
        a=m.row_fingerprint(0,b)
        b[700]=None
        self.assertNotEqual(a,m.row_fingerprint(0,b))
        self.assertNotEqual(a,m.row_fingerprint(m.H,self.fixture()[0]))
        with self.assertRaises(ValueError):
            m.h6b(s,b,0,0)
        b[724]=(100.,90.,110.,100.)
        with self.assertRaises(ValueError):
            self.case(b,s)

    def test_real_leader_normalization_on_synthetic_prices(self):
        lead=[(100.,101.,99.,100*math.exp(.001*math.sin(i))) for i in range(745)]
        lead[724]=(100.,120.,99.,115.)
        lr,z=m.lead_stats([lead,lead])
        self.assertGreater(z[724],3.)
        b,_=self.fixture()
        self.assertEqual(len(m.h6b((lr,z),b,0,.1)[0]),1)


class HarnessChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.report=Path(self.tmp.name)/'result.json'
        self.db=sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE trials(id INTEGER PRIMARY KEY,ref TEXT,params TEXT,result TEXT,weight INTEGER)')
        self.spec=(Path(__file__).resolve().parents[1]/'research/registrations/clo256_h6b_v1.md').read_bytes()
        self.params=dict(sha256=m.SPEC_SHA256,gate_status='PENDING_CONFIRMATION',evaluation_state='NOT_RUN')
        self.db.execute('INSERT INTO trials VALUES(173,?,?,?,1)',('CLO-256:H6b:v1',json.dumps(self.params),'NOT RUN'))
        self.db.commit()
        self.fn=Mock(return_value={'synthetic':True})

    def run_harness(self):
        return m.run_once(self.db,self.report,self.spec,{'SYNTHETIC':'a'*64},self.fn)

    def authorize_synthetic(self):
        self.params.update(gate_status='CONFIRMED',evaluation_state='AUTHORIZED',board_confirmation_comment_id='SYNTHETIC ONLY')
        self.db.execute('UPDATE trials SET params=? WHERE id=173',(json.dumps(self.params),))
        self.db.commit()

    def test_pending_gate_refuses_before_callback_file_or_registry_mutation(self):
        with self.assertRaises(PermissionError):
            self.run_harness()
        self.fn.assert_not_called()
        self.assertFalse(self.report.exists())
        self.assertEqual(self.db.execute('SELECT result FROM trials').fetchone()[0],'NOT RUN')

    def test_create_only_and_existing_trial_no_new_reservations(self):
        self.authorize_synthetic()
        self.report.write_text('prior attempt')
        with self.assertRaises(FileExistsError):
            self.run_harness()
        self.fn.assert_not_called()
        self.assertEqual(self.report.read_text(),'prior attempt')
        self.assertEqual(self.db.execute('SELECT count(*) FROM trials').fetchone()[0],1)

    def test_counts_at_run_and_duplicate_refused(self):
        self.authorize_synthetic()
        self.db.execute("INSERT INTO trials VALUES(999,'other','{}','prior',500)")
        self.db.commit()
        self.assertEqual(self.run_harness()['ntrials'],501)
        self.fn.assert_called_once_with(501)
        with self.assertRaises(PermissionError):
            self.run_harness()
        self.fn.assert_called_once()

    def test_interruption_keeps_started_evidence_and_no_retry(self):
        self.authorize_synthetic()
        self.fn.side_effect=RuntimeError('synthetic interruption')
        with self.assertRaises(RuntimeError):
            self.run_harness()
        self.assertEqual(json.loads(self.report.read_text())['state'],'started')
        self.assertEqual(self.db.execute('SELECT result FROM trials').fetchone()[0],'EVALUATING')
        with self.assertRaises(PermissionError):
            self.run_harness()
        self.fn.assert_called_once()

    def test_bad_spec_or_fingerprint_cannot_evaluate(self):
        self.authorize_synthetic()
        with self.assertRaises(ValueError):
            m.run_once(self.db,self.report,b'altered',{'x':'a'*64},self.fn)
        with self.assertRaises(ValueError):
            m.run_once(self.db,self.report,self.spec,{},self.fn)
        self.fn.assert_not_called()


if __name__=='__main__':
    unittest.main()
