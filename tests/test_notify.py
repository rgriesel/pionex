"""Owner notifications: anti-spam rules (no network; a fake sender)."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pionex_lab.notify import MAX_PER_DAY, notify

SAST = timezone(timedelta(hours=2))


class Notify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.var = Path(self.tmp.name)
        self.sent = []

    def tearDown(self):
        self.tmp.cleanup()

    def send(self, text, level="important", key=None, at=datetime(2026, 10, 15, 10, 0, tzinfo=SAST)):
        return notify(self.var, text, level=level, key=key, now=at, sender=self.sent.append)

    def test_duplicate_keys_are_sent_once_a_day(self):
        self.assertEqual(self.send("PASS: x", key="pass-x"), "sent")
        self.assertEqual(self.send("PASS: x", key="pass-x"), "skipped (duplicate)")
        self.assertEqual(len(self.sent), 1)

    def test_daily_cap_spares_critical_and_the_morning_summary(self):
        for i in range(MAX_PER_DAY):
            self.send(f"news {i}")
        self.assertEqual(self.send("one too many"), "skipped (daily cap)")
        self.assertEqual(self.send("feed down", level="critical"), "sent")
        self.assertEqual(self.send("summary", level="daily"), "sent")

    def test_quiet_hours_hold_then_deliver_with_the_next_message(self):
        night = datetime(2026, 10, 15, 2, 30, tzinfo=SAST)
        self.assertEqual(self.send("red team: HOLDS", at=night), "held (quiet hours)")
        self.assertEqual(self.send("broken", level="critical", at=night), "sent")       # critical goes now
        self.assertEqual(self.send("books +0.4%", level="daily",
                                   at=datetime(2026, 10, 15, 7, 55, tzinfo=SAST)), "sent")
        self.assertIn("red team: HOLDS", self.sent[-1])                                  # held one delivered
        self.assertIn("Morning summary", self.sent[-1])


class NotifyFailures(unittest.TestCase):
    def test_a_telegram_error_keeps_the_message(self):
        with tempfile.TemporaryDirectory() as d:
            def boom(m):
                raise RuntimeError("no chat yet")
            r = notify(Path(d), "PASS: y", now=datetime(2026, 10, 15, 14, 0, tzinfo=SAST), sender=boom)
            self.assertTrue(r.startswith("held (Telegram"))
            sent = []
            notify(Path(d), "later", now=datetime(2026, 10, 15, 15, 0, tzinfo=SAST), sender=sent.append)
            self.assertIn("PASS: y", sent[0])                                # delivered with the next one


if __name__ == "__main__":
    unittest.main()
