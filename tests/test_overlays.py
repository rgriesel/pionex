"""CTA overlays: the scale hook leaves v1.1 unchanged by default, the overlays cannot see the future,
the DVOL backfill never rewrites stored rows (synthetic data only, no network)."""
import copy
import json
import math
import random
import sqlite3
import statistics
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pionex_lab.data import altdata
from pionex_lab.strategies.indicators import ema
from pionex_lab.swing import cta, overlays as ov

DAY = 86_400_000
HOUR = 3_600_000


def make_data(seed=7, coins=("A", "B", "C", "D"), days=320, drift=0.002, sigma=0.03):
    """Daily rows shaped like cta.load(): open = previous close, so open-to-open == close-to-close."""
    rng = random.Random(seed)
    common = [rng.gauss(0, sigma) for _ in range(days)]
    data = {}
    for s in coins:
        c, p = [], 100.0
        for i in range(days):
            p *= 1 + drift + 0.6 * common[i] + 0.8 * rng.gauss(0, sigma)
            c.append(p)
        e = ema(c, 50)
        rets = [0.0] + [c[i] / c[i - 1] - 1 for i in range(1, days)]
        rows = {}
        for i in range(days):
            vol = float("nan")
            if i >= 30:
                xs = rets[i - 29:i + 1]
                m = sum(xs) / 30
                vol = math.sqrt(sum((x - m) ** 2 for x in xs) / 30 * 365.25)
            nan = float("nan")
            rows[i * DAY] = {"o": c[i - 1] if i else c[0], "c": c[i], "ema": e[i], "vol": vol, "age": i,
                             "r20": c[i] / c[i - 20] - 1 if i >= 20 else nan, "r60": c[i] / c[i - 60] - 1 if i >= 60 else nan,
                             "r120": c[i] / c[i - 120] - 1 if i >= 120 else nan}
        data[s] = rows
    return data


COINS = ("A", "B", "C", "D")
ZERO = {s: 0.0 for s in COINS}


def sim(data, **kw):
    return cta.simulate(data, "tsmom_vote", "vol", coins=COINS, cost=ZERO, **kw)


class Hook(unittest.TestCase):
    def test_default_and_unit_factor_are_identical(self):
        d = make_data()
        base = sim(d)
        self.assertTrue(base)
        self.assertEqual(base, sim(d, scale=None))
        self.assertEqual(base, sim(d, scale=lambda t, w, data: 1.0))        # same numbers, bit for bit

    def test_factor_only_cuts_exposure(self):
        d = make_data()
        full = sim(d, band=0.0)
        half = sim(d, band=0.0, scale=lambda t, w, data: 0.5)
        self.assertEqual([x[0] for x in full], [x[0] for x in half])
        for a, b in zip(full[1:], half[1:]):
            self.assertAlmostEqual(b[1], 0.5 * a[1], places=9)             # zero costs, daily rebalance: exactly half
            self.assertLessEqual(b[2], a[2] + 1e-12)
        self.assertTrue(all(x[2] <= 1.0 + 1e-9 for x in half))
        flat = sim(d, scale=lambda t, w, data: 0.0)
        self.assertTrue(all(x[2] == 0.0 and x[1] == 0.0 for x in flat[2:]))

    def test_bad_factors_raise(self):
        d = make_data(days=200)
        for bad in (1.5, -0.1, float("nan")):
            with self.assertRaises(ValueError):
                sim(d, scale=lambda t, w, data, b=bad: b)

    def test_hook_gets_a_copy_and_a_decision_day(self):
        d = make_data(days=200)
        seen = []

        def spy(t, w, data):
            seen.append((t, dict(w)))
            w.clear()                                                       # must not reach the simulation
            return 1.0
        self.assertEqual(sim(d, scale=spy), sim(d))
        self.assertTrue(seen and all(t % DAY == 0 for t, _ in seen))


class CovarianceCap(unittest.TestCase):
    def setUp(self):
        self.d = make_data(seed=3)
        self.t = 200 * DAY
        self.w = {"A": 0.10, "B": 0.08, "C": 0.05}

    def test_forecast_matches_the_formula(self):
        # two coins with the same alternating +-1% returns: perfectly correlated, vol adds linearly
        def path(sign):
            c = [100.0]
            for i in range(1, 100):
                c.append(c[-1] * (1 + sign * (0.01 if i % 2 else -0.01)))
            return {i * DAY: {"c": c[i]} for i in range(100)}
        data = {"A": path(1), "B": path(1), "N": path(-1)}
        t = 90 * DAY
        rets = [data["A"][u]["c"] / data["A"][u - DAY]["c"] - 1 for u in (t - k * DAY for k in range(1, 61))]
        sd = statistics.stdev(rets) * math.sqrt(365.25)
        self.assertAlmostEqual(ov.basket_vol(t, {"A": 0.2, "B": 0.1}, data), 0.3 * sd, places=9)
        self.assertLess(ov.basket_vol(t, {"A": 0.1, "N": 0.1}, data), 1e-6)      # exact hedge: no risk
        self.assertEqual(ov.basket_vol(t, {}, data), 0.0)

    def test_factor_is_min_of_one_and_cap_over_forecast(self):
        vol = ov.basket_vol(self.t, self.w, self.d)
        self.assertGreater(vol, 0)
        self.assertEqual(ov.CovCap(10.0)(self.t, self.w, self.d), 1.0)
        self.assertAlmostEqual(ov.CovCap(vol / 2)(self.t, self.w, self.d), 0.5)
        self.assertEqual(ov.CovCap(0.1)(self.t, {}, self.d), 1.0)                # nothing held: nothing to cap

    def test_no_lookahead_in_forecast(self):
        before = ov.basket_vol(self.t, self.w, self.d)
        fut = copy.deepcopy(self.d)
        for s in fut:
            for t in list(fut[s]):
                if t >= self.t:                                              # today's bar and everything later
                    fut[s][t].update(o=1e9, c=random.random() * 1e9)
        self.assertEqual(ov.basket_vol(self.t, self.w, fut), before)
        past = copy.deepcopy(self.d)                                         # the test has power: yesterday matters
        past["A"][self.t - DAY]["c"] *= 1.3
        self.assertNotEqual(ov.basket_vol(self.t, self.w, past), before)

    def test_too_little_history_means_no_cap(self):
        short = {s: {t: r for t, r in rows.items() if t >= 190 * DAY} for s, rows in self.d.items()}
        self.assertIsNone(ov.basket_vol(self.t, self.w, short))
        self.assertEqual(ov.CovCap(0.01)(self.t, self.w, short), 1.0)

    def test_end_to_end_future_data_does_not_change_the_past(self):
        cap = 0.5 * ov.basket_vol(self.t, self.w, self.d)
        base = sim(self.d, scale=ov.CovCap(cap))
        fut = copy.deepcopy(self.d)
        cut = 250 * DAY
        for s in fut:
            for t in list(fut[s]):
                if t >= cut:
                    fut[s][t].update(o=fut[s][t]["o"] * 3, c=fut[s][t]["c"] * 0.2)
        alt = sim(fut, scale=ov.CovCap(cap))
        keep = [x for x in base if x[0] <= cut - 2 * DAY]                   # interval t0 books open(t0) -> open(t0 + 1 day)
        self.assertGreater(len(keep), 50)
        self.assertEqual(keep, [x for x in alt if x[0] <= cut - 2 * DAY])

    def test_low_cap_cuts_exposure_high_cap_changes_nothing(self):
        base = sim(self.d)
        self.assertEqual(base, sim(self.d, scale=ov.CovCap(math.inf)))
        low = sim(self.d, scale=ov.CovCap(0.05))
        self.assertLess(sum(x[2] for x in low), sum(x[2] for x in base))


class DvolShockTests(unittest.TestCase):
    def setUp(self):
        self.daily = {k * DAY: 50.0 for k in range(200)}
        self.hook = ov.DvolShock(self.daily)
        self.w = {"A": 0.1}

    def test_threshold_is_at_least_1_25_times_the_median(self):
        self.daily[149 * DAY] = 62.4
        self.assertEqual(self.hook(150 * DAY, self.w, None), 1.0)
        self.daily[149 * DAY] = 62.5                                         # exactly 1.25 x 50 triggers
        self.assertEqual(self.hook(150 * DAY, self.w, None), 0.5)
        self.assertTrue(self.hook.log[150 * DAY]["trigger"])
        self.daily[150 * DAY] = 50.0                                         # back below -> full size again
        self.assertEqual(self.hook(151 * DAY, self.w, None), 1.0)

    def test_value_of_day_u_is_used_from_day_u_plus_one(self):
        self.daily[149 * DAY] = 80.0
        self.assertEqual(self.hook(149 * DAY, self.w, None), 1.0)            # day 149's own value is not known yet
        self.assertEqual(self.hook(150 * DAY, self.w, None), 0.5)

    def test_no_lookahead_in_dvol(self):
        base = {t: self.hook(t, self.w, None) for t in (100 * DAY, 120 * DAY, 150 * DAY)}
        fut = dict(self.daily)
        for k in range(150, 200):
            fut[k * DAY] = 500.0 + k                                         # everything from decision day 150 on
        hook2 = ov.DvolShock(fut)
        self.assertEqual({t: hook2(t, self.w, None) for t in base}, base)
        fut[149 * DAY] = 500.0                                               # yesterday matters
        self.assertEqual(ov.DvolShock(fut)(150 * DAY, self.w, None), 0.5)

    def test_median_uses_a_trailing_90_day_window(self):
        old_high = {k * DAY: (100.0 if k < 100 else 50.0) for k in range(200)}   # days 0..99 high, then calm
        old_high[199 * DAY] = 70.0
        # window days 110..199: median 50 -> 70 >= 62.5 triggers; a 300-day window would see median 75 and not
        self.assertEqual(ov.DvolShock(old_high)(200 * DAY, self.w, None), 0.5)
        self.assertEqual(ov.DvolShock(old_high, window=300)(200 * DAY, self.w, None), 1.0)

    def test_missing_history_means_full_size(self):
        sparse = {k * DAY: 50.0 for k in range(30)}
        sparse[29 * DAY] = 500.0
        self.assertEqual(ov.DvolShock(sparse)(30 * DAY, self.w, None), 1.0)

    def test_end_to_end_future_dvol_does_not_change_the_past(self):
        d = make_data(seed=5)
        daily = {k * DAY: 50.0 + (k % 7) for k in range(330)}
        for k in range(180, 200):
            daily[k * DAY] = 90.0
        base = sim(d, scale=ov.DvolShock(daily))
        fut = dict(daily)
        for k in range(250, 330):
            fut[k * DAY] = 5.0 + 400.0 * (k % 2)
        alt = sim(d, scale=ov.DvolShock(fut))
        self.assertEqual([x for x in base if x[0] <= 249 * DAY], [x for x in alt if x[0] <= 249 * DAY])
        self.assertLess(sum(x[2] for x in base), sum(x[2] for x in sim(d)))   # the spike cut exposure

    def test_placebo_mask_halves_only_its_days(self):
        m = ov.MaskScale({5 * DAY})
        self.assertEqual((m(5 * DAY, {}, None), m(6 * DAY, {}, None)), (0.5, 1.0))

    def test_hourly_to_daily_uses_the_2300_bar_and_skips_unfinished_days(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "alt.db"
            con = sqlite3.connect(db)
            con.executescript(altdata.SCHEMA)
            rows = [("dvol_1h", h * HOUR, float(h)) for h in range(24 + 20)]  # day 0 complete, day 1 only up to 19:00
            con.executemany("INSERT INTO alt VALUES(?,?,?)", rows)
            con.commit()
            con.close()
            self.assertEqual(ov.load_dvol_daily(db), {0: 23.0})


class Statistics(unittest.TestCase):
    def test_episodes_merge_short_gaps(self):
        days = [k * DAY for k in (0, 1, 2, 5, 6, 20, 21)]
        self.assertEqual(ov.episodes(days), 2)                                # 0-6 is one episode (gap 2 < 7), 20-21 another
        self.assertEqual(ov.episodes(days, gap_days=2), 3)
        self.assertEqual(ov.episodes([]), 0)

    def test_bootstrap_is_deterministic_and_sensible(self):
        rng = random.Random(1)
        b = [rng.gauss(0.001, 0.01) for _ in range(400)]
        a = [x + 0.0005 for x in b]
        r1 = ov.paired_block_bootstrap(a, b, resamples=500)
        self.assertEqual(r1, ov.paired_block_bootstrap(a, b, resamples=500))
        self.assertAlmostEqual(r1["mean_diff"]["lower"], 0.0005, places=3)    # a constant edge is certain
        self.assertGreater(r1["sharpe_diff"]["lower"], 0)
        same = ov.paired_block_bootstrap(b, b, resamples=200)
        self.assertEqual((same["mean_diff"]["lower"], same["mean_diff"]["upper"]), (0.0, 0.0))

    def test_gates_need_every_condition_and_three_episodes(self):
        self.assertEqual(ov._verdict({"a": True, "b": True}, 3), "PASS")
        self.assertEqual(ov._verdict({"a": True, "b": False}, 5), "FAIL")
        self.assertEqual(ov._verdict({"a": True}, 2), "INSUFFICIENT")


class Backfill(unittest.TestCase):
    def test_only_older_rows_are_added_and_stored_rows_never_change(self):
        first = altdata.DVOL_FIRST
        t_first = altdata._ms(first)
        stored_t = t_first + 5 * HOUR
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "alt.db"
            con = sqlite3.connect(db)
            con.executescript(altdata.SCHEMA)
            con.execute("INSERT INTO alt VALUES('dvol_1h', ?, 77.0)", (stored_t,))
            con.execute("INSERT INTO alt VALUES('fng', ?, 10.0)", (stored_t,))
            con.commit()
            con.close()
            calls = []

            def fake(url, tries=4):
                calls.append(url)
                rows = [[t_first + h * HOUR, 1, 1, 1, 50.0 + h] for h in range(0, 9)]   # also returns bars at/after stored_t
                return json.dumps({"result": {"data": rows}}).encode()
            with mock.patch.object(altdata, "_get", fake), mock.patch.object(altdata.time, "sleep", lambda s: None):
                r = altdata.dvol_backfill(db)
            self.assertEqual(r["inserted"], 5)                                # hours 0..4 only; hour 5 is the stored row
            self.assertIn("resolution=3600", calls[0])
            con = sqlite3.connect(db)
            got = dict(con.execute("SELECT t, v FROM alt WHERE series='dvol_1h'"))
            fng = con.execute("SELECT COUNT(*) FROM alt WHERE series='fng'").fetchone()[0]
            con.close()
            self.assertEqual(got[stored_t], 77.0)                              # untouched
            self.assertEqual(len(got), 6)
            self.assertEqual(fng, 1)


if __name__ == "__main__":
    unittest.main()
