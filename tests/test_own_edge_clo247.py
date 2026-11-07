"""Synthetic mechanics only: never evaluate a market-return series here."""
import unittest

from pionex_lab.research import own_edge_clo247 as m


def bars(n=70):
    return {"t": [i * m.BAR_MS for i in range(n)],
            "o": [100.] * n, "h": [101.] * n, "l": [99.] * n,
            "c": [100.] * n, "v": [1000.] * n}


class OwnEdge(unittest.TestCase):
    def test_gap_duplicate_and_invalid_bars_rejected(self):
        for change in (lambda b: b["t"].__setitem__(5, b["t"][4]),
                       lambda b: b["c"].__setitem__(5, float("nan")),
                       lambda b: b["h"].__setitem__(5, 90)):
            b = bars()
            change(b)
            with self.assertRaises(ValueError):
                m.h3_capitulation(b)

    def test_listing_requires_original_clock_and_only_one_signal(self):
        b = bars()
        b["c"][17], b["h"][17] = 102., 103.
        e = dict(id="first", kind="listing", open_time=0, received_at=0,
                 published_at=0, source_url="https://example.test/event")
        self.assertEqual([i for i, s in enumerate(m.h1_listing(b, [e])) if s], [17])
        with self.assertRaises(ValueError):
            m.h1_listing(b, [dict(e, received_at=m.BAR_MS)])
        with self.assertRaises(ValueError):
            m.h1_listing(b, [e, e])

    def test_listing_missing_price_coverage_is_not_zero_signals(self):
        e = dict(id="x", kind="listing", open_time=100 * m.BAR_MS,
                 received_at=0, published_at=0, source_url="https://example.test")
        with self.assertRaises(ValueError):
            m.h1_listing(bars(), [e])

    def test_funding_requires_actual_complete_liquidations_and_causal_receipt(self):
        b = bars()
        rows = [dict(event_end=(i + 1) * m.BAR_MS,
                     received_at=(i + 1) * m.BAR_MS + 1,
                     funding_at=(i + 1) * m.BAR_MS,
                     funding_rate=-0.0004, long_liquidation_usd=10., complete=True,
                     source_url="https://example.test/liq") for i in range(50)]
        rows[42]["long_liquidation_usd"] = 40.
        b["c"][42] = b["c"][43] = 100.5
        sig = m.h2_funding_liquidations(b, rows)
        self.assertEqual(sig[42], 0)  # one millisecond late, cannot enter at this close
        self.assertEqual(sig[43], 1)
        rows[42]["complete"] = False
        with self.assertRaises(ValueError):
            m.h2_funding_liquidations(b, rows)
        with self.assertRaises(ValueError):
            m.h2_funding_liquidations(b, [])

    def test_capitulation_waits_for_confirmation_and_is_prefix_invariant(self):
        b = bars()
        b["c"][25], b["h"][25], b["l"][25], b["o"][25] = 90., 92., 89., 91.
        b["v"][25] = 3000.
        b["c"][26] = 100.5  # confirmation must be green, not a flat candle
        sig = m.h3_capitulation(b)
        self.assertEqual(sig[25], 0)
        self.assertEqual(sig[26], 1)
        prefix = {k: v[:27] for k, v in b.items()}
        self.assertEqual(m.h3_capitulation(prefix), sig[:27])

    def test_next_open_stop_first_and_cost_stress(self):
        b, sig = bars(), [0] * 70
        sig[20] = 1
        b["h"][21], b["l"][21] = 110., 90.
        out = m.replay(b, sig)
        t = out["trades"][0]
        self.assertEqual(t["entry_time"], b["t"][21])
        self.assertEqual(t["exit_reason"], "stop")
        self.assertAlmostEqual(t["gross_bps"], -300.)
        stress = m.replay(b, sig, cost_multiplier=4)["trades"][0]
        self.assertAlmostEqual(t["net_bps"] - stress["net_bps"], 72.)

    def test_time_exit_and_terminal_open_not_discarded(self):
        b, sig = bars(), [0] * 70
        sig[20] = 1
        t = m.replay(b, sig)["trades"][0]
        self.assertEqual(t["exit_time"] - t["entry_time"], 6 * m.BAR_MS)
        sig = [0] * 70
        sig[67] = 1
        self.assertTrue(m.replay(b, sig)["terminal_open"])

    def test_gap_at_stop_fills_open(self):
        b, sig = bars(), [0] * 70
        sig[20] = 1
        b["o"][22], b["h"][22], b["l"][22], b["c"][22] = 90., 91., 89., 90.
        t = m.replay(b, sig)["trades"][0]
        self.assertEqual(t["exit_reason"], "stop_gap")
        self.assertAlmostEqual(t["gross_bps"], -1000.)


if __name__ == "__main__":
    unittest.main()
