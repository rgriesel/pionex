import math
import tempfile
import unittest
from pathlib import Path

from pionex_lab.research.owner_grid_clo237 import Ledger, HOUR, run_path, evaluate_once


RULES = {'quoteStep':'0.1','baseStep':'0.0001','minSizeLimit':'0.0001',
         'minNotional':'1','liquidationFeeRate':'0.0115','_half_spread':.000001}


class OwnerGridTests(unittest.TestCase):
    def test_ledger_conserves_pnl_and_costs(self):
        s=Ledger(80000,50,40,RULES)
        qty=s.qty
        self.assertTrue(s.valid)
        self.assertAlmostEqual(s.equity(80000),50-s.fees-s.slippage)
        s.close(80100,'test')
        self.assertAlmostEqual(s.cash,50+qty*100-s.fees-s.slippage)

    def test_liquidation_cannot_consume_cash_reserve(self):
        s=Ledger(80000,50,40,RULES)
        s.candle([0,80000,81000,70000,80000])
        self.assertTrue(s.closed)
        self.assertEqual(s.reason,'liquidation')
        self.assertEqual(s.cash,0)
        self.assertEqual(s.qty,0)

    def test_roundtrip_inventory_reconciles(self):
        s=Ledger(80000,50,5,RULES)
        s.q=.0002
        initial=s.qty
        p=s.levels[5]
        s.move(80000,p-.1)
        bought=s.qty-initial
        self.assertGreater(bought,0)
        s.move(p-.1,80000)
        self.assertGreater(s.trips,0)
        self.assertGreaterEqual(s.qty,0)

    def test_minimum_rejects_small_capital(self):
        self.assertFalse(Ledger(80000,1,40,RULES).valid)

    def test_signal_and_fill_are_causal(self):
        bars=[[i*HOUR,80000+i*5,80001+i*5,79999+i*5,80000+i*5] for i in range(24*12)]
        sig=[False]*len(bars)
        sig[175]=True  # consumed by 176h open, never at 175h
        r=run_path(bars,RULES,(40,.02,8),entry_signals=sig)
        self.assertEqual(r['trades'][0]['entry_time'],176*HOUR)
        self.assertTrue(all(math.isfinite(x) for x in r['returns']))
        self.assertAlmostEqual(100*math.prod(1+x for x in r['returns']),r['final_usdt'])

    def test_gap_is_rejected(self):
        bars=[[i*HOUR,80000,80001,79999,80000] for i in range(300)]
        bars[170][0]+=1
        with self.assertRaisesRegex(ValueError,'gapped'):
            run_path(bars,RULES,(40,.02,8))

    def test_costs_reduce_flat_hold_equity(self):
        a=Ledger(80000,50,40,RULES,1)
        b=Ledger(80000,50,40,RULES,4)
        a.close(80000,'test')
        b.close(80000,'test')
        self.assertLess(b.cash,a.cash)

    def test_existing_result_prevents_rerun(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'result.json'
            p.write_text('{}')
            with self.assertRaisesRegex(RuntimeError,'already evaluated'):
                evaluate_once('unused',Path(d)/'trials.db',p)


if __name__=='__main__':
    unittest.main()
