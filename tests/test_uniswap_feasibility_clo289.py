import unittest
from research.uniswap_feasibility_clo289 import MINT,BURN,apply_event,signed,word,words
from research.uniswap_feasibility_clo289 import run
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

def event(topic,lo,hi,amount):
    data=('0'*64 if topic==MINT else '')+word(amount)+word(0)+word(0)
    return {'topics':[topic,'0x'+word(1),'0x'+word(lo),'0x'+word(hi)],'data':'0x'+data}

class RangeReplayTests(unittest.TestCase):
    def test_signed_negative_ticks(self):
        self.assertEqual(signed(int(word(-100),16),24),-100)
        self.assertEqual(words('0x'+word(8)),[8])
    def test_mint_burn_churn_and_fee_only(self):
        book={}
        apply_event(book,event(MINT,-10,20,50))
        apply_event(book,event(MINT,-10,30,20))
        apply_event(book,event(BURN,-10,20,0))
        self.assertEqual(book,{-10:(70,70),20:(50,-50),30:(20,-20)})
        apply_event(book,event(BURN,-10,20,50))
        self.assertEqual(book,{-10:(20,20),30:(20,-20)})
    def test_missing_initial_liquidity_is_error(self):
        with self.assertRaises(ValueError):apply_event({},event(BURN,-10,20,5))
    def test_malformed_abi_is_error(self):
        for bad in ['0x123','bad',None]:
            with self.assertRaises(ValueError):words(bad)

    def test_transport_failure_never_creates_success(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'result.json'
            with patch('research.uniswap_feasibility_clo289.RPC.request',side_effect=OSError('429 rate limit')):
                run(path)
            result=json.loads(path.read_text())
            self.assertEqual(result['verdict'],'NO_NOT_DEMONSTRATED')
            self.assertIn('429',result['failure'])
            self.assertNotIn('exact_replay_match',result)
            self.assertTrue(Path(str(path)+'.rpc.json').is_file())

if __name__=='__main__':unittest.main()
