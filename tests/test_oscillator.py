"""WL Oscillator: point-in-time maths, and the Wave Lab chart computing the same numbers (synthetic data)."""
import json
import math
import random
import shutil
import subprocess
import unittest

from pionex_lab.util import PROJECT_ROOT
from pionex_lab.waves import oscillator as osc

from tests.helpers import make_bars, random_walk


def bars(n=700, seed=3):
    closes = random_walk(n, 60000.0, 0.006, seed=seed)
    rng = random.Random(seed)
    b = make_bars("BTC_USDT", "60M", closes, spread=0.004, vol=[rng.uniform(50, 500) for _ in range(n)])
    return list(b.o), list(b.h), list(b.l), list(b.c), list(b.v)


def nan_to_none(x):
    return [None if isinstance(v, float) and math.isnan(v) else v for v in x]


class Maths(unittest.TestCase):
    def test_signals_exist_and_stay_in_range(self):
        r = osc.calc(*bars())
        for key in ("rev", "div", "fair", "trend", "mfdiv"):
            self.assertTrue(any(r[key]), key)
        arrows = [s for s in r["trend"] if s]
        self.assertTrue(all(a != b for a, b in zip(arrows, arrows[1:])))   # trend arrows alternate
        self.assertTrue(all(0 <= b <= 7 for b in r["bull"] if not math.isnan(b)))
        for i, s in enumerate(r["rev"]):
            if s:                                                        # a cross of the signal line
                self.assertEqual(s > 0, r["wt1"][i] > r["wt2"][i])
                self.assertEqual(s > 0, r["wt1"][i - 1] <= r["wt2"][i - 1])

    def test_no_repainting(self):
        full = osc.calc(*bars())
        for cut in (120, 333, 555):
            part = osc.calc(*[x[:cut] for x in bars()])
            for key, vals in part.items():
                self.assertEqual(nan_to_none(vals), nan_to_none(full[key][:cut]), f"{key} changed at cut {cut}")


class ProModes(unittest.TestCase):
    def test_each_mode_draws_its_signals_without_repainting(self):
        b = bars(1500, 11)
        expect = {"prime": ("brk", "tri", "obos", "div"), "fusion": ("dot", "div"), "mvp": ("sigs", "bs")}
        for fn, keys in expect.items():
            full = getattr(osc, fn)(*b)
            for key in keys:
                self.assertTrue(any(full[key]), f"{fn}.{key} never fires")
            part = getattr(osc, fn)(*[x[:900] for x in b])
            for key, vals in part.items():
                self.assertEqual(nan_to_none(vals), nan_to_none(full[key][:900]), f"{fn}.{key} repaints")
        pr = osc.prime(*b)
        self.assertTrue(all(0 <= x <= 100 for x in pr["fast"] if not math.isnan(x)))
        mv = osc.mvp(*b)
        self.assertTrue(all(-100 <= x <= 100 for x in mv["line"] if not math.isnan(x)))
        self.assertTrue(set(osc.divs(pr["fast"], b[1], b[2], 5, 5, 35)["div"]) <= {0, 1, -1, 2, -2, 3, -3})


class Study(unittest.TestCase):
    def test_trades_follow_signals_one_at_a_time_with_costs(self):
        from pionex_lab.swing import osc_study as st
        b = make_bars("BTC_USDT", "60M", random_walk(900, 60000.0, 0.006, seed=5), spread=0.004, vol=[100.0] * 900)
        r = osc.calc(list(b.o), list(b.h), list(b.l), list(b.c), list(b.v))
        for name in st.SIGNALS:
            tr = st.simulate(b, r, name)
            for t in tr:
                self.assertAlmostEqual(t["gross_bps"] - t["net_bps"], 2 * (st.FEE_BPS + st.SLIP_BPS))
                self.assertEqual(t["exit_time"] - t["entry_time"], st.HOLD * 3_600_000)
            for a, c in zip(tr, tr[1:]):
                self.assertLess(a["exit_time"], c["entry_time"] + 1)
        self.assertTrue(st.simulate(b, r, "reversal"))
        rep = st.evaluate(b, r)
        self.assertEqual(set(rep["signals"]), set(st.SIGNALS))
        self.assertTrue(all(v["status"] == "FAIL" for v in rep["signals"].values()))   # noise never passes

    def test_tutorial_method_trades(self):
        from pionex_lab.swing import osc_study as st
        b = make_bars("BTC_USDT", "60M", random_walk(3000, 60000.0, 0.006, seed=9), spread=0.004, vol=[100.0] * 3000)
        r = osc.calc(list(b.o), list(b.h), list(b.l), list(b.c), list(b.v))
        tr = st.simulate_v2(b, b, r, "trend_pullback") + st.simulate_v2(b, b, r, "diamond")
        self.assertTrue(tr)
        for t in tr:
            self.assertAlmostEqual(t["gross_bps"] - t["net_bps"], 2 * (st.FEE_BPS + st.SLIP_BPS))
            self.assertGreaterEqual(t["r_multiple"], -1.0 - 1e-9)                   # never worse than the stop
            self.assertLessEqual(t["r_multiple"], 0.5 * 1.5 + 0.5 * 3.0 + 1e-9)    # never better than both targets
            self.assertLessEqual(t["exit_time"] - t["entry_time"], 30 * 3_600_000)


class ChartParity(unittest.TestCase):
    def test_wavelab_block_matches_python(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        page = (PROJECT_ROOT / "wavelab" / "index.html").read_text(encoding="utf-8")
        block = page[page.index("/* WLOSC-BEGIN"):page.index("/* WLOSC-END */")]
        script = block + """
const inp = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(inp.map(b => WLOSC[b.fn](b.o, b.h, b.l, b.c, b.v, b.p))));"""
        cases = []
        for fn in ("calc", "prime", "fusion", "mvp"):
            for seed, p in ((3, {}), (8, {"n1": 9, "n2": 12, "pivot": 3, "ob": 40, "vwap": 30, "mindist": 3, "maxdist": 50})):
                o, h, l, c, v = bars(500, seed)
                cases.append({"fn": fn, "o": o, "h": h, "l": l, "c": c, "v": v, "p": p})
        res = subprocess.run([node, "-e", script], input=json.dumps(cases), capture_output=True, text=True, timeout=120)
        self.assertEqual(res.returncode, 0, res.stderr)
        for case, js in zip(cases, json.loads(res.stdout)):
            py = getattr(osc, case["fn"])(case["o"], case["h"], case["l"], case["c"], case["v"], case["p"])
            self.assertEqual(set(py), set(js), case["fn"])
            for key in py:
                for i, (a, b) in enumerate(zip(nan_to_none(py[key]), js[key])):
                    if a is None or b is None:
                        self.assertEqual(a, b, f"{key}[{i}]")
                    else:
                        self.assertTrue(math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9), f"{key}[{i}]: {a} vs {b}")


if __name__ == "__main__":
    unittest.main()
