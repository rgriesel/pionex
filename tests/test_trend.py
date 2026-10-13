"""Daily trend filter study (synthetic data only)."""
import unittest

from pionex_lab.data.store import Bars
from pionex_lab.swing import trend

D = 86_400_000


def days(closes):
    o = [closes[0]] + closes[:-1]
    return Bars("BTC_USDT", "1D", [i * D for i in range(len(closes))], o,
                [max(a, b) for a, b in zip(o, closes)], [min(a, b) for a, b in zip(o, closes)], closes, [1.0] * len(closes))


class Trend(unittest.TestCase):
    def test_hold_matches_price_and_filter_sits_out_a_fall(self):
        up = [100 * 1.01 ** i for i in range(200)]
        down = [up[-1] * 0.99 ** i for i in range(1, 101)]
        d = days(up + down)
        hold, ema = trend.backtest(d, "hold"), trend.backtest(d, "ema50")
        expect = d.o[-1] / d.o[trend.WARMUP] * (1 - trend.SIDE_COST) - 1
        self.assertAlmostEqual(hold["total"], expect, places=4)          # entry cost taken off day one's return
        self.assertEqual(hold["switches"], 1)
        self.assertGreater(ema["total"], hold["total"])                    # out of the market for most of the fall
        self.assertLess(ema["max_drawdown"], hold["max_drawdown"])
        self.assertEqual(ema["switches"], 2)

    def test_signal_uses_only_the_previous_close(self):
        d = days([100.0] * 150 + [200.0] + [200.0] * 5)
        r = trend.positions(list(d.c), "ema50")
        self.assertEqual(r[149], 0)
        self.assertEqual(r[150], 1)                                        # decided at the jump day's close
        res = trend.backtest(d, "ema50")
        self.assertAlmostEqual(res["total"], (1 - trend.SIDE_COST) - 1)   # entered after the jump, flat after


class VolScaled(unittest.TestCase):
    def test_calm_market_is_full_size_and_wild_market_is_scaled_down(self):
        import math
        calm = days([100 * 1.002 ** i for i in range(300)])                 # steady rise: vol ~0
        self.assertAlmostEqual(trend.vol_scaled(calm, trend.WARMUP)["total"], trend.backtest(calm, "ema50")["total"], places=6)
        wild = days([100 * 1.002 ** i * (1.08 if i % 2 else 0.95) for i in range(300)])
        v, p = trend.vol_scaled(wild, trend.WARMUP), trend.backtest(wild, "ema50")
        self.assertLess(abs(math.log(1 + v["total"])), abs(math.log(1 + p["total"])) + 1e-9)


if __name__ == "__main__":
    unittest.main()
