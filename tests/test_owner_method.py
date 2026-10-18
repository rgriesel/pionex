import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from dataclasses import replace

from pionex_lab.research import owner_method as m
from pionex_lab.research.owner_exit_study import audit_account, exit_context


def flat(n=20):
    return [m.Bar(i * m.HOUR, 100, 101, 99, 100, 100) for i in range(n)]


def position(direction="long", target=110):
    return m.Position(direction, 0, target, 0, 2)


def signal(bars=None, p=None, **kwargs):
    bars = flat() if bars is None else bars
    now = bars[-1].time + m.HOUR
    return m.exit_signal(bars, p or position(), now, m.FlattenMark(now, 1), **kwargs)


class OwnerMarketReadExit(unittest.TestCase):
    def test_stall_and_short_symmetry(self):
        self.assertIn("stall", signal()["reasons"])
        mirrored = [m.Bar(b.time, 200-b.open, 200-b.low, 200-b.high, 200-b.close, b.volume)
                    for b in flat()]
        a = signal()
        b = signal(mirrored, position("short", 90))
        self.assertEqual(a["reasons"], b["reasons"])
        self.assertEqual(b["action"], "CLOSE_RESEARCH_ONLY")

    def test_must_bank_profit_after_costs(self):
        bars, now = flat(), 20 * m.HOUR
        for pnl in (0, -0.1):
            r = m.exit_signal(bars, position(), now, m.FlattenMark(now, pnl))
            self.assertEqual(r["action"], "HOLD")
        for mark in (None, m.FlattenMark(now - 5001, 1), m.FlattenMark(now+1, 1), m.FlattenMark(now, float("nan"))):
            self.assertEqual(m.exit_signal(bars, position(), now, mark)["action"], "UNKNOWN")

    def test_future_bar_gap_and_future_target_rejected(self):
        bars = flat()
        self.assertEqual(m.exit_signal(bars, position(), 19*m.HOUR, m.FlattenMark(19*m.HOUR, 1))["action"], "UNKNOWN")
        self.assertEqual(signal(bars[:5] + bars[6:])["action"], "UNKNOWN")
        self.assertEqual(signal(p=replace(position(), target_known_at=1))["action"], "UNKNOWN")
        bad = list(bars)
        bad[-1] = replace(bad[-1], volume=float("nan"))
        self.assertEqual(signal(bad)["action"], "UNKNOWN")

    def test_causal_news_only(self):
        now = 20*m.HOUR
        e = m.Event("CPI", now+100, now, now)
        self.assertIn("news_ahead", signal(events=[e])["reasons"])
        self.assertNotIn("news_ahead", signal(events=[replace(e, ingested=now+1)])["reasons"])
        self.assertNotIn("news_ahead", signal(events=[replace(e, published=now+1)])["reasons"])
        self.assertNotIn("news_ahead", signal(events=[replace(e, time=now-1)])["reasons"])

    def test_cluster_consumption_move_and_identity(self):
        now = 20*m.HOUR
        initial = m.Cluster("frozen", 0, 110, 1000)
        p = replace(position(), cluster=initial)
        current = m.Cluster("frozen", now, 110, 250)
        self.assertIn("cluster_consumed", signal(p=p, cluster=current)["reasons"])
        moved = replace(current, mass=1000, price=111)
        self.assertIn("cluster_moved_away", signal(p=p, cluster=moved)["reasons"])
        for invalid in (replace(current, identity="other"), replace(current, time=now+1),
                        replace(current, time=now-m.HOUR-1), replace(current, mass=-1)):
            self.assertIn("heatmap_cluster", signal(p=p, cluster=invalid)["unknown"])

    def test_kaplan_meier_censoring_and_training_boundary(self):
        rows = [m.TargetOutcome(-100*m.HOUR, -50*m.HOUR, 2, True) for _ in range(5)]
        self.assertEqual(m.median_target_hours(rows, 0), 2)
        # Ten long censored observations prevent the median from being reached.
        censored = [m.TargetOutcome(-100*m.HOUR, -50*m.HOUR, 24, False) for _ in range(10)]
        self.assertIsNone(m.median_target_hours(rows+censored, 0))
        self.assertIsNone(m.median_target_hours([replace(r, resolved=1) for r in rows], 0))
        self.assertIsNone(m.median_target_hours(rows[:4], 0))
        self.assertIn("time_stop", signal(training=rows)["reasons"])

    def test_failed_retests_require_confirmed_pivots(self):
        bars = flat(8)
        for i, high in enumerate((105,109.8,108,109.4,108,107,106,105)):
            bars[i] = replace(bars[i], high=high)
        self.assertIn("failed_retests", signal(bars)["reasons"])
        self.assertNotIn("failed_retests", signal(bars[:4])["reasons"])

    def test_volume_fade_near_target(self):
        bars = flat()
        for i in range(17,20):
            bars[i] = replace(bars[i], volume=10)
        self.assertIn("momentum_volume_fade", signal(bars,p=position(target=101))["reasons"])
        self.assertNotIn("momentum_volume_fade", signal(bars,p=position(target=120))["reasons"])

    def test_entry_missing_inputs_and_overhead_veto(self):
        self.assertEqual(m.entry_signal({}), "STAND_ASIDE")
        f = dict(causal_complete=True,news_safe=True,analyst_count=2,analyst_bias="long",target_cluster=True,
                 support_touch=True,bullish_ob=True,big_ob_below=True,overhead_veto=False,
                 resistance_touch=False,bearish_ob=False,big_ob_above=False,underfoot_veto=False)
        self.assertEqual(m.entry_signal(f), "LONG_RESEARCH_ONLY")
        self.assertEqual(m.entry_signal(dict(f,overhead_veto=True)), "STAND_ASIDE")
        self.assertEqual(m.entry_signal(dict(f,analyst_count=1)), "STAND_ASIDE")

    def test_next_open_profit_recheck_and_fee_aware_pair(self):
        frames = [m.ReplayFrame(b, 2, 2) for b in flat(24)]
        frames[7] = replace(frames[7], open_net_pnl=-1)
        frames[8] = replace(frames[8], open_net_pnl=3)
        frames[-1] = replace(frames[-1], close_net_pnl=-5)
        result = m.paired_replay(frames,position())
        self.assertEqual(result["market_exit_net_pnl"], 3)
        self.assertEqual(result["hold_net_pnl"], -5)
        self.assertEqual(result["paired_net_benefit"], 8)

    def test_liquidation_gap_beats_pending_but_later_extreme_does_not(self):
        frames = [m.ReplayFrame(b,2,2) for b in flat(24)]
        frames[7] = replace(frames[7], liquidated_at_open=True, liquidation_net_pnl=-100)
        result = m.paired_replay(frames,position())
        self.assertEqual(result["market_exit_net_pnl"], -100)
        self.assertEqual(result["paired_net_benefit"], 0)
        frames[7] = replace(frames[7], liquidated_at_open=False, liquidation_touched=True)
        result = m.paired_replay(frames,position())
        self.assertEqual(result["market_exit_net_pnl"], 2)
        self.assertEqual(result["hold_net_pnl"], -100)

    def test_ambiguous_target_liquidation_and_missing_settlement(self):
        frames = [m.ReplayFrame(replace(flat(1)[0],high=112),2,2,
                               liquidation_touched=True,liquidation_net_pnl=-100,target_net_pnl=10)]
        self.assertEqual(m.paired_replay(frames,position())["hold_net_pnl"], -100)
        with self.assertRaises(ValueError):
            m.paired_replay([replace(frames[0],liquidation_net_pnl=None)],position())
        self.assertFalse(m.paired_replay([m.ReplayFrame(flat(1)[0],2,2)],position())["complete_pair"])

    def test_audit_retains_missing_bots_and_does_not_infer_target_from_range(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/"account.db"
            with sqlite3.connect(p) as c:
                c.execute("CREATE TABLE bots(bu_order_id TEXT,at INTEGER,raw TEXT)")
                c.execute("INSERT INTO bots VALUES('missing',1,NULL)")
                summary = {"status":"canceled","createTime":1,"closeTime":10,"buOrderData":{
                    "trend":"long","reasonBy":"user_cancel","top":"110","closedPrice":"105"}}
                c.execute("INSERT INTO bots VALUES('manual',20,?)",(json.dumps({"summary":summary}),))
            c.close()
            audit = audit_account(p)
        self.assertEqual(audit["observed_distinct_bots"],2)
        self.assertEqual(audit["classification_counts"]["missing_raw"],1)
        self.assertEqual(audit["classification_counts"]["manual_target_unknown"],1)
        self.assertEqual(audit["causal_entry_target_bots"],0)

    def test_context_excludes_the_candle_still_open_at_exit(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root/"var").mkdir()
            c = sqlite3.connect(root/"var"/"market.db")
            c.execute("CREATE TABLE klines(symbol TEXT,interval TEXT,complete INT,open_time INT,"
                      "open REAL,high REAL,low REAL,close REAL,volume REAL)")
            for b in flat(21):
                if b.time == 20*m.HOUR:
                    b = replace(b, high=1000,close=1000)
                c.execute("INSERT INTO klines VALUES('BTC_USDT','60M',1,?,?,?,?,?,?)",
                          (b.time,b.open,b.high,b.low,b.close,b.volume))
            c.commit()
            c.close()
            r = exit_context(root,[dict(id="a",pair="BTC_USDT",direction="long",end=20.5*m.HOUR,
                                        latest_target=110,target_observed_before_exit=False)])
        context = r["rows"][0]
        self.assertEqual(context["last_closed_bar_end"],20*m.HOUR)
        self.assertEqual(context["signed_3h_price_change"],0)
        self.assertTrue(context["latest_target_is_hindsight"])


if __name__ == "__main__":
    unittest.main()
