"""Forward-only YouTube BTC guidance scorecard (synthetic candles only)."""
import tempfile
import unittest
from pathlib import Path

from pionex_lab.swing import guidance as g

H = 3_600_000
T0 = g._ms("2026-10-13T07:00:00+00:00")


def call(**kw):
    c = {"source": "Chart Hackers", "video_id": "abc", "title": "t", "published": "2026-10-12T18:00:00Z",
         "recorded": "2026-10-13T07:00:00Z", "bias": "SHORT"}
    c.update(kw)
    return c


def bars(closes, start=T0):
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        out.append((start + i * H, prev, max(prev, c) + 10, min(prev, c) - 10, c))
        prev = c
    return out


class Records(unittest.TestCase):
    def test_forward_only_and_append_once(self):
        with self.assertRaises(ValueError):
            g.validate(call(recorded="2026-10-12T20:00:00Z"))            # before "start from today"
        with self.assertRaises(ValueError):
            g.validate(call(source="Someone Else"))
        with self.assertRaises(ValueError):
            g.validate(call(long_zones=[[80000, 79000]]))
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "calls.jsonl"
            self.assertEqual(g.add(p, [call()]), 1)
            self.assertEqual(g.add(p, [call(), call(video_id="xyz")]), 1)
            self.assertEqual([c["video_id"] for c in g.load(p)], ["abc", "xyz"])


class Scoring(unittest.TestCase):
    def test_falling_market_scores_short_bias_zone_trigger_and_target(self):
        closes = [84000 - 30 * i for i in range(120)]                    # steady fall to 80,430
        c = call(long_zones=[[82000, 82500]], short_zones=[[86000, 87000]],
                 triggers=[{"close_below": 83500, "side": "SHORT"}],
                 targets=[{"price": 82000, "side": "SHORT"}, {"price": 79000, "side": "SHORT"}])
        s = g.score_call(c, bars([84000] * 5, T0 - 5 * H) + bars(closes))
        self.assertEqual(s["entry"], 84000)
        self.assertEqual(s["status"], "final")
        self.assertAlmostEqual(s["bias_24h_net_bps"], (1 - closes[23] / 84000) * 1e4 - 10, places=0)
        long_zone, short_zone = s["zones"]
        self.assertEqual(long_zone["fill"], 82500)                       # limit at the zone top
        self.assertLess(long_zone["net_bps"], 0)                         # bought into a falling market
        self.assertLess(long_zone["worst_bps"], 0)
        self.assertIsNone(short_zone["filled"])                          # never rallied to 86K
        t = s["triggers"][0]
        self.assertIsNotNone(t["fired"])
        self.assertGreater(t["net_bps"], 0)
        self.assertEqual([x["reached"] is not None for x in s["targets"]], [True, False])
        summ = g.summarize([s])["by_source"]["Chart Hackers"]
        self.assertEqual(summ["zones"]["n"], 1)
        self.assertEqual(summ["targets"], {"n": 2, "reached": 1})

    def test_only_candles_after_recording_count(self):
        s = g.score_call(call(), bars([90000] * 10, T0 - 20 * H))
        self.assertEqual(s["status"], "pending")
        s = g.score_call(call(bias="LONG"), bars([84000, 84100, 84200]))
        self.assertEqual(s["status"], "running")
        self.assertNotIn("bias_24h_net_bps", s)


if __name__ == "__main__":
    unittest.main()
