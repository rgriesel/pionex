"""Firm status for the dashboard (temporary files only)."""
import json
import tempfile
import unittest
from pathlib import Path

from pionex_lab.reporting.firm import firm_status

LOG = """# Strategy log
## Live candidates (paper)
| Date | Strategy | Hold | Result | Status |
|---|---|---|---|---|
| 2026-10-13 | **Trend basket** (`x.py`): rules | days | numbers | **PASS** → paper |
## Tested and not good enough
| Date | Strategy | Timeframe / hold | Result | Verdict |
|---|---|---|---|---|
| 2026-10-13 | Scalper | 1m | loses | FAIL |
| 2026-10-12 | Carry | weeks | small | real but small |
"""
AGENT = "---\nname: red-team\ndescription: Adversarial reviewer. Tries to break any PASS. More.\nmodel: opus\n---\nbody\n"


class Firm(unittest.TestCase):
    def test_books_pipeline_and_agents(self):
        with tempfile.TemporaryDirectory() as d:
            root, var = Path(d) / "repo", Path(d) / "var"
            (root / "docs").mkdir(parents=True)
            (root / ".claude" / "agents").mkdir(parents=True)
            (var / "swing_book").mkdir(parents=True)
            (root / "docs" / "STRATEGY_LOG.md").write_text(LOG, encoding="utf-8")
            (root / ".claude" / "agents" / "red-team.md").write_text(AGENT, encoding="utf-8")
            hist = [{"equity": 1100.0}, {"equity": 990.0}, {"equity": 1050.0}]
            (var / "swing_book" / "state.json").write_text(json.dumps(
                {"start": "2026-10-14", "paper_usdt": 1000.0, "equity": 1050.0, "history": hist,
                 "weights": {"ETH_USDT": 0.1, "BTC_USDT": 0.2}}), encoding="utf-8")
            f = firm_status(var, 1_800_000_000_000, root=root)
        b = f["books"][0]
        self.assertEqual((b["return_pct"], b["max_drawdown_pct"], b["paper_days"]), (5.0, 10.0, 3))  # 1100 -> 990
        self.assertEqual(b["holdings"], "BTC 20%, ETH 10%")
        self.assertAlmostEqual(b["invested_pct"], 30.0)
        self.assertEqual(f["review_after"], "2026-12-13")
        self.assertEqual(f["pipeline"]["tested"], 2)
        self.assertEqual(f["pipeline"]["failed"], 1)
        self.assertEqual(f["pipeline"]["candidates"][0]["strategy"], "Trend basket")
        self.assertEqual([a["role"] for a in f["agents"]], ["lead (main session)", "red-team"])
        self.assertEqual(f["agents"][1]["does"], "Tries to break any PASS.")
        self.assertEqual(len(f["routines"]), 5)                           # supervisor job + 4 Claude routines

    def test_missed_routines_come_due_after_sleep(self):
        from datetime import datetime, timedelta, timezone
        from pionex_lab.reporting.firm import due, stamp
        sast = timezone(timedelta(hours=2))
        with tempfile.TemporaryDirectory() as d:
            var = Path(d)
            ran_evening = datetime(2026, 10, 13, 22, 0, tzinfo=sast)       # everything ran last evening
            for name in ("nightly_check", "research", "morning_summary", "youtube_calls"):
                stamp(var, name, ran_evening)
            self.assertEqual(due(var, datetime(2026, 10, 13, 23, 0, tzinfo=sast)), [])
            woke = datetime(2026, 10, 14, 9, 40, tzinfo=sast)               # PC slept 00:00-09:34
            self.assertEqual(due(var, woke), ["nightly_check", "research", "morning_summary"])
            stamp(var, "research", woke)
            self.assertNotIn("research", due(var, woke))
            self.assertIn("youtube_calls", due(var, datetime(2026, 10, 14, 21, 50, tzinfo=sast)))


if __name__ == "__main__":
    unittest.main()
