"""BTC-led gate: dict scale hook is neutral by default, the gate zeroes only non-BTC coins while BTC is OUT."""
import unittest

from pionex_lab.swing import btc_gate, cta
from pionex_lab.swing.cta import DAY
from tests.test_overlays import make_data


class GateTests(unittest.TestCase):
    def setUp(self):
        self.data = make_data(days=420)
        self.coins = tuple(self.data)

    def sim(self, **kw):
        return cta.simulate(self.data, "tsmom_vote", "vol", coins=self.coins, **kw)

    def test_empty_dict_is_v11(self):
        self.assertEqual(self.sim(), self.sim(scale=lambda t, w, d: {}))

    def test_dict_factor_validated(self):
        with self.assertRaises(ValueError):
            self.sim(scale=lambda t, w, d: {"B": 1.5})

    def test_gate_only_cuts_alts_when_btc_out(self):
        hook = btc_gate.BtcGate(btc="A")
        self.sim(scale=hook)
        self.assertTrue(any(not v["btc_in"] for v in hook.log.values()))
        targets = {"A": 0.1, "B": 0.1}
        f = hook(300 * DAY, targets, self.data)
        if not hook.log[300 * DAY]["btc_in"]:
            self.assertEqual(f, {"B": 0.0})
        else:
            self.assertEqual(f, {})

    def test_missing_btc_counts_as_out(self):
        hook = btc_gate.BtcGate(btc="ZZZ")
        self.assertEqual(hook(300 * DAY, {"A": 0.1}, self.data), {"A": 0.0})
        self.assertTrue(hook.log[300 * DAY]["binds"])

    def test_gate_never_adds_exposure(self):
        base = self.sim()
        gate = self.sim(scale=btc_gate.BtcGate(btc="A"))
        self.assertLessEqual(sum(x[2] for x in gate), sum(x[2] for x in base) + 1e-9)

    def test_evaluate_runs(self):
        out = btc_gate.evaluate(self.data, coins=self.coins, cost=None, cost4=None, btc="A")
        self.assertIn(out["verdict"], ("PASS", "FAIL", "INSUFFICIENT"))
        self.assertLessEqual(out["control_target_scale"], 1.0 + 1e-9)


if __name__ == "__main__":
    unittest.main()
