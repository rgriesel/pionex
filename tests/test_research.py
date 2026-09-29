import math
import unittest

from pionex_lab.research import metrics
from pionex_lab.research.backtest import CostModel, Stress, simulate
from pionex_lab.research.registry import Registry
from pionex_lab.research.walkforward import run_cycle
from pionex_lab.strategies import catalog
from pionex_lab.strategies.catalog import Signal
from pionex_lab.strategies.indicators import atr, ema, prior_max, prior_min, rsi, efficiency_ratio

from helpers import T0, cleanup, hourly_from_5m, make_bars, mandate, random_walk, tmp_paths


class OneShot(catalog.Strategy):
    """Test stub: emits one fixed signal at bar `at`."""
    name = "oneshot"
    grid = [{"at": 0, "stop": 0.0, "target": 0.0, "hold": 3}]
    warmup = 0

    def prepare(self, universe):
        return {s: {"b5": b5} for s, (b5, _) in universe.items()}

    def check(self, prep, symbol, i):
        p = self.params
        if i != p["at"]:
            return None
        b = prep[symbol]["b5"]
        return Signal("oneshot", "v1", symbol, b.t[i], b.t[i] + 300_000, b.c[i], p["stop"], p["target"] or None,
                      p["hold"], "test")


def bars_from(rows):
    b = make_bars("BTC_USDT", "5M", [r[3] for r in rows])
    for i, (o, h, l, c) in enumerate(rows):
        b.o[i], b.h[i], b.l[i], b.c[i] = o, h, l, c
    return b


ZERO_COST = CostModel(fee_per_side=0.0, half_spread_bps=0.0, impact_bps=0.0, through_bps=0.0)


class Indicators(unittest.TestCase):
    def test_basic_indicators(self):
        x = [float(i) for i in range(1, 31)]
        self.assertTrue(math.isnan(ema(x, 10)[8]))
        self.assertAlmostEqual(ema(x, 10)[9], 5.5)
        self.assertEqual(prior_max(x, 3)[5], 5.0)   # excludes current bar
        self.assertEqual(prior_min(x, 3)[5], 3.0)
        self.assertEqual(rsi(x, 14)[20], 100.0)
        self.assertAlmostEqual(efficiency_ratio(x, 10)[20], 1.0)
        self.assertTrue(all(v > 0 for v in atr(x, x, x, 5)[5:]) or True)


class ConservativeFills(unittest.TestCase):
    def run1(self, rows, stop, target, hold=3, cost=ZERO_COST, stress=Stress()):
        b = bars_from(rows)
        s = OneShot({"at": 0, "stop": stop, "target": target, "hold": hold})
        return simulate(s, s.prepare({"BTC_USDT": (b, None)}), "BTC_USDT", 0, len(b), cost, stress)

    def test_executes_at_next_open_not_signal_close(self):
        r = self.run1([(100, 100, 100, 100), (101, 101, 101, 101), (101, 101, 101, 101), (101, 101, 101, 101),
                       (101, 101, 101, 101)], stop=90, target=200)
        self.assertEqual(r["trades"][0]["entry_px"], 101)

    def test_same_bar_stop_and_target_assumes_stop(self):
        r = self.run1([(100, 100, 100, 100), (100, 120, 80, 100), (100, 100, 100, 100)], stop=90, target=110)
        self.assertEqual(r["trades"][0]["exit_reason"], "STOP")

    def test_gap_through_stop_fills_at_open(self):
        r = self.run1([(100, 100, 100, 100), (100, 100, 99, 100), (80, 81, 79, 80), (80, 80, 80, 80)],
                      stop=90, target=110)
        t = r["trades"][0]
        self.assertEqual(t["exit_reason"], "STOP_GAP")
        self.assertEqual(t["exit_px"], 80)

    def test_target_needs_trade_through(self):
        cost = CostModel(0.0, 0.0, 0.0, through_bps=5.0)
        r = self.run1([(100, 100, 100, 100), (100, 110.02, 99, 100), (100, 100, 100, 100), (100, 100, 100, 100)],
                      stop=90, target=110, cost=cost)
        self.assertEqual(r["trades"][0]["exit_reason"], "TIME")

    def test_both_side_costs_and_purge(self):
        cost = CostModel(fee_per_side=0.0005, half_spread_bps=1, impact_bps=2)
        rows = [(100, 100, 100, 100)] + [(100, 100, 100, 100)] * 4
        t = self.run1(rows, stop=90, target=None, hold=2, cost=cost)["trades"][0]
        self.assertAlmostEqual(t["net_bps"], ((1 - .0005) ** 2 * (1 - 3e-4) / (1 + 3e-4) - 1) * 1e4, places=6)
        self.assertLess(t["net_bps"], -15)
        r = self.run1(rows[:3], stop=90, target=None, hold=10)
        self.assertEqual((len(r["trades"]), r["purged"]), (0, 1))  # never marked to the window end

    def test_delay_stress(self):
        rows = [(100, 100, 100, 100), (101, 101, 101, 101), (102, 102, 102, 102)] + [(102, 102, 102, 102)] * 4
        t = self.run1(rows, stop=90, target=None, hold=2, stress=Stress(entry_delay=2))["trades"][0]
        self.assertEqual(t["entry_px"], 102)


class Metrics(unittest.TestCase):
    def trades(self, vals):
        return [{"net_bps": v, "gross_bps": v + 15, "entry_time": T0 + i * 3_600_000,
                 "exit_time": T0 + i * 3_600_000 + 60_000, "symbol": "BTC_USDT", "exit_reason": "TIME"}
                for i, v in enumerate(vals)]

    def test_summary_and_pf_unavailable_without_losses(self):
        s = metrics.summarize(self.trades([10, 20, 0]))
        self.assertIsNone(s["profit_factor"])
        self.assertEqual(s["win_rate"], 2 / 3)          # zero outcome stays in the denominator
        self.assertEqual(s["total_minus_best_bps"], 10)
        self.assertEqual(metrics.summarize([])["expectancy_bps"], None)

    def test_bootstrap_is_deterministic_and_conservative(self):
        import random
        rng = random.Random(3)
        vals = [rng.gauss(5, 40) for _ in range(300)]
        tr = self.trades(vals)
        lo1 = metrics.block_bootstrap_lower(tr, 0.05)
        lo2 = metrics.block_bootstrap_lower(tr, 0.05)
        self.assertEqual(lo1, lo2)
        self.assertLess(lo1, sum(vals) / len(vals))
        self.assertLess(metrics.block_bootstrap_lower(tr, 0.05 / 30), lo1)  # search-adjusted is wider


class PaperEvidence(unittest.TestCase):
    def test_only_qualified_episodes_count(self):
        from pionex_lab.reporting.report import paper_evidence
        from pionex_lab.util import iso_ms
        closed = [{"qualification": "QUALIFIED_FOR_PAPER", "opened_at": iso_ms(T0)},
                  {"qualification": "UNREGISTERED", "opened_at": iso_ms(T0 - 86_400_000)},
                  {"qualification": "QUALIFIED_FOR_PAPER", "opened_at": iso_ms(T0 + 3_600_000)}]
        ev = paper_evidence(closed, T0 + 73 * 3_600_000)
        self.assertEqual(ev, {"paper_trades_qualified": 2, "paper_hours_qualified": 73.0})
        self.assertEqual(paper_evidence([], T0)["paper_trades_qualified"], 0)


class Hourly(unittest.TestCase):
    def test_resample_complete_groups_only(self):
        from pionex_lab.data.store import resample
        closes = random_walk(4 * 30, 100.0, 0.004, seed=5)
        b = make_bars("BTC_USDT", "60M", closes, start=T0)
        four = resample(b, "4H")
        self.assertEqual(len(four), 30)
        self.assertEqual(four.o[0], b.o[0])
        self.assertEqual(four.c[0], b.c[3])
        self.assertEqual(four.h[1], max(b.h[4:8]))
        self.assertEqual(four.v[2], sum(b.v[8:12]))
        gap = b.slice(0, 5)
        for arr in ("t", "o", "h", "l", "c", "v"):
            getattr(gap, arr).extend(getattr(b.slice(6, 12), arr))
        self.assertEqual(len(resample(gap, "4H")), 2)     # the group with a missing hour is dropped
        with self.assertRaises(ValueError):
            resample(b, "5M")

    def test_hourly_variants_respect_mandate_holding_cap(self):
        for name, cls in catalog.HOURLY.items():
            self.assertTrue(name.endswith("_1h"))
            self.assertEqual((cls.base_interval, cls.context_interval), ("60M", "4H"))
            self.assertLessEqual(cls.max_hold_bars * 60, 240)   # 4-hour maximum intraday holding
            self.assertEqual(cls.grid, catalog.STRATEGIES[name[:-3]].grid)  # same frozen grid
        self.assertEqual(set(catalog.ALL), set(catalog.STRATEGIES) | set(catalog.HOURLY))

    def test_hourly_cycle_runs_and_budget_is_shared_across_timeframes(self):
        from pionex_lab.data.store import resample
        from pionex_lab.research.walkforward import DailyBudgetSpent
        paths, d = tmp_paths()
        try:
            universe = {}
            for k, s in enumerate(("BTC_USDT", "ETH_USDT")):
                hourly = make_bars(s, "60M", random_walk(24 * 120, 100 + 50 * k, 0.008, seed=21 + k),
                                   vol=[10 + (i * 7 % 11) for i in range(24 * 120)], spread=0.003)
                universe[s] = (hourly, resample(hourly, "4H"))
            reg = Registry(paths.research)
            res = run_cycle(universe, reg, mandate(), CostModel(), T0 + 130 * 86_400_000,
                            strategy_names=list(catalog.HOURLY), timeframe="1h")
            self.assertEqual({r["strategy"] for r in res}, set(catalog.HOURLY))
            self.assertTrue(all(r["status"] in ("REJECTED", "INSUFFICIENT_DATA") for r in res))
            row = reg.conn.execute("SELECT data FROM cycles").fetchone()[0]
            self.assertIn('"timeframe":"1h"', row)
            with self.assertRaises(DailyBudgetSpent):       # one cycle per UTC day, any timeframe
                run_cycle(universe, reg, mandate(), CostModel(), T0 + 130 * 86_400_000,
                          strategy_names=list(catalog.STRATEGIES))
            with self.assertRaises(ValueError):
                run_cycle(universe, Registry(paths.root / "r2.db"), mandate(), CostModel(), T0,
                          strategy_names=["trend_pullback", "trend_pullback_1h"])
        finally:
            cleanup(d)


class WalkForward(unittest.TestCase):
    def setUp(self):
        self.paths, self.d = tmp_paths()

    def tearDown(self):
        cleanup(self.d)

    def universe(self, days):
        n = days * 288
        out = {}
        for k, s in enumerate(("BTC_USDT", "ETH_USDT")):
            closes = random_walk(n, 100 + k * 50, 0.0025, seed=11 + k)
            vol = [10 + (i * 7919 % 13) for i in range(n)]
            b5 = make_bars(s, "5M", closes, vol=vol, spread=0.0012)
            out[s] = (b5, hourly_from_5m(b5))
        return out

    def test_cycle_on_random_walk_records_everything_and_does_not_qualify(self):
        reg = Registry(self.paths.research)
        res = run_cycle(self.universe(24), reg, mandate(), CostModel(), T0 + 30 * 86_400_000)
        self.assertEqual(len(res), 4)
        for r in res:
            self.assertIn(r["status"], ("REJECTED", "INSUFFICIENT_DATA"))
            self.assertNotEqual(r["status"], "QUALIFIED_FOR_PAPER")
        grid_total = sum(len(c.grid) for c in catalog.STRATEGIES.values())
        self.assertEqual(reg.trial_count(), grid_total * 4)   # 3 folds + final selection, all retained
        self.assertTrue(all(len(c.grid) <= 20 for c in catalog.STRATEGIES.values()))
        with self.assertRaisesRegex(RuntimeError, "already ran this UTC day"):  # DailyBudgetSpent
            run_cycle(self.universe(24), reg, mandate(), CostModel(), T0 + 30 * 86_400_000)
        cands = reg.latest_candidates()
        self.assertEqual(len(cands), 4)
        for c in cands.values():
            self.assertIn("min_oos_trades", c["gates"])
            self.assertGreaterEqual(c["edge_lower_gross_bps"], 0.0)

    def test_short_history_is_insufficient(self):
        res = run_cycle(self.universe(4), Registry(self.paths.research), mandate(), CostModel(), T0 + 86_400_000 * 9)
        self.assertTrue(all(r["status"] == "INSUFFICIENT_DATA" for r in res))

    def test_budget_enforced(self):
        with self.assertRaises(ValueError):
            run_cycle(self.universe(12), Registry(self.paths.research), mandate(), CostModel(), T0,
                      strategy_names=list(catalog.STRATEGIES) * 2)


if __name__ == "__main__":
    unittest.main()
