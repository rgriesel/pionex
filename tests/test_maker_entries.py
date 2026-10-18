import unittest

from pionex_lab.swing import cta
from pionex_lab.swing.maker_entries import fill


def hours():
    return {h:{'o':100.,'h':102.,'l':99.,'c':100.,'v':10000.} for h in range(7)}


class MakerEntryTests(unittest.TestCase):
    def test_submission_hour_and_wick_do_not_fill(self):
        rows=hours()
        rows[0]['c']=98.
        rows[0]['l']=97.
        rows[6]['o']=101.
        self.assertEqual(fill(100,rows,.01,2,100),(101.,False,6))

    def test_later_close_through_and_tick_rounding(self):
        rows=hours()
        rows[1]['c']=99.
        price,maker,h=fill(100,rows,.01,3,100)
        self.assertEqual((price,maker,h),(99.98,True,1))

    def test_missing_hour_is_not_a_free_fill(self):
        rows=hours()
        del rows[3]
        with self.assertRaisesRegex(ValueError,'missing'):
            fill(100,rows,.01,2,100)

    def test_insufficient_volume_chases(self):
        rows=hours()
        for h in range(1,6):
            rows[h]['c']=99.
            rows[h]['v']=.001
        self.assertFalse(fill(100,rows,.01,2,100)[1])

    def test_open_mismatch_and_invalid_bars_rejected(self):
        rows=hours()
        rows[0]['o']=101
        with self.assertRaisesRegex(ValueError,'mismatch'):
            fill(100,rows,.01,2,100)
        rows=hours()
        rows[1]['l']=103
        with self.assertRaisesRegex(ValueError,'OHLCV'):
            fill(100,rows,.01,2,100)

    def test_trace_does_not_change_baseline(self):
        data={'BTC_USDT':{i*cta.DAY:{'o':100+i,'c':101+i,'age':i,
              'r20':.1,'r60':.1,'r120':.1,'vol':.5} for i in range(130)}}
        trace=[]
        expected=cta.simulate(data,'tsmom_vote','vol',coins=('BTC_USDT',),capital=1000)
        actual=cta.simulate(data,'tsmom_vote','vol',coins=('BTC_USDT',),capital=1000,order_trace=trace)
        self.assertEqual(actual,expected)
        self.assertTrue(any(o['after'] for o in trace))


if __name__=='__main__':
    unittest.main()
