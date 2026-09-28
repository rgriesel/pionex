"""End-to-end paper runtime tests against a local fake exchange (synthetic data)."""
import json
import threading
import unittest
import urllib.request
from decimal import Decimal

from pionex_lab.data.collector import Collector
from pionex_lab.data.store import MarketStore, MarketView
from pionex_lab.exchange.pionex_public import PionexPublic
from pionex_lab.exchange.ratelimit import WeightedLimiter
from pionex_lab.ledger.book import Book
from pionex_lab.reporting.report import build_report, validate_report
from pionex_lab.reporting.server import make_handler
from pionex_lab.risk.service import LeaseError
from pionex_lab.runtime.engine import Engine
from pionex_lab.runtime.state import current_state
from pionex_lab.strategies import catalog
from pionex_lab.util import FakeClock

from fake_pionex import FakePionex
from helpers import T0, cleanup, mandate, runtime_cfg, tmp_paths


class Stub(catalog.Strategy):
    """Deterministic test strategy: one BTC signal on the first evaluated bar."""
    name = "stub"
    grid = [{"stop_frac": 0.01, "target_frac": 0.003, "hold": 6}]
    warmup = 0

    def __init__(self, params=None):
        super().__init__(params)
        self.fired = False

    def prepare(self, universe):
        return {s: {"b5": b5} for s, (b5, _) in universe.items()}

    def check(self, prep, symbol, i):
        if self.fired or symbol != "BTC_USDT":
            return None
        self.fired = True
        b = prep[symbol]["b5"]
        c = b.c[i]
        p = self.params
        return catalog.Signal("stub", "v1", symbol, b.t[i], b.t[i] + 300_000, c, c * (1 - p["stop_frac"]),
                              c * (1 + p["target_frac"]), p["hold"], "test signal")


class Harness:
    def __init__(self, start_ms=T0 + 10 * 86_400_000):
        self.paths, self.dir = tmp_paths()
        self.clock = FakeClock(start_ms)
        self.fake = FakePionex(self.clock.now_ms).__enter__()
        self.cfg = runtime_cfg()
        self.cfg["base_url"] = self.fake.url
        self.store = MarketStore(self.paths.market)
        lim = WeightedLimiter(10_000, exit_reserve=0, clock=self.clock)
        self.collector = Collector(PionexPublic(self.fake.url, limiter=lim, clock=self.clock), self.store, self.cfg,
                                   self.clock)
        self.collector.refresh_symbols()
        for s in self.cfg["research_universe"]:
            self.collector.backfill(s, "5M", 2)
            self.collector.backfill(s, "60M", 4)
        self.m = mandate()

    def engine(self, stub=True, edge="25", status="QUALIFIED_FOR_PAPER", holder=None):
        eng = Engine(self.cfg, self.paths, self.m, self.clock, MarketView(self.paths.market), holder=holder)
        self.collector.poll_once()
        eng.start()
        if stub:
            eng.strategies = {"stub": {"strategy": Stub(), "status": status, "edge_bps": Decimal(edge),
                                       "params": Stub.grid[0], "candidate_id": None}}
            eng._due_at["strategies"] = 1 << 62
        return eng

    def run(self, eng, seconds, step=2.0, until=None):
        for _ in range(int(seconds / step)):
            self.clock.advance(step)
            self.collector.poll_once()
            eng.step()
            if until and until():
                return True
        return False

    def kinds(self, eng, kind):
        return [p for _, _, k, p in eng.journal.events((kind,))]

    def close(self):
        self.fake.__exit__()
        cleanup(self.dir)


class FullCycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h = Harness()
        cls.eng = cls.h.engine()
        cls.closed = cls.h.run(cls.eng, 3600, until=lambda: cls.eng.journal.count("POSITION_CLOSED") > 0)
        cls.h.run(cls.eng, 120)

    @classmethod
    def tearDownClass(cls):
        cls.h.close()

    def test_lifecycle_journaled(self):
        e = self.eng
        self.assertTrue(self.closed)
        self.assertEqual(current_state(e.journal), "PAPER")
        started = self.h.kinds(e, "EXPERIMENT_STARTED")[0]
        self.assertFalse(started["official_data_source"])
        self.assertEqual(self.h.kinds(e, "BENCHMARK_STARTED")[0]["symbol"], "BTC_USDT")
        intents = self.h.kinds(e, "ORDER_INTENT")
        entry = [i for i in intents if i["purpose"] == "ENTRY"][0]
        self.assertEqual(entry["type"], "LIMIT")
        self.assertTrue(entry["ioc"])
        self.assertFalse(entry["dry_run_request"]["sent"])
        self.assertEqual(entry["dry_run_request"]["path"], "/api/v1/trade/order")
        from pionex_lab.execution.dryrun import find_official_cli
        expected = ("official pionex-trade-cli --dry-run" if find_official_cli() else
                    "built-in renderer (official CLI not installed)")
        self.assertEqual(entry["dry_run_request"]["preview_source"], expected)
        exits = [i for i in intents if i["purpose"] == "EXIT"]
        self.assertEqual(exits[0]["type"], "MARKET")

    def test_fills_use_later_quotes_and_sizing_limits(self):
        e = self.eng
        entry = [i for i in self.h.kinds(e, "ORDER_INTENT") if i["purpose"] == "ENTRY"][0]
        fill = [f for f in self.h.kinds(e, "FILL") if f["client_order_id"] == entry["client_order_id"]][0]
        self.assertGreater(fill["quote_fetched_at"], entry["submitted_at"])
        self.assertGreaterEqual(fill["latency_ms"], 250)
        self.assertEqual(fill["fee_asset"], "BASE")
        opened = self.h.kinds(e, "POSITION_OPENED")[0]
        notional = Decimal(opened["qty"]) * Decimal(opened["entry_avg"])
        self.assertLessEqual(notional, Decimal("25.01"))           # 25% of $100
        self.assertLessEqual(Decimal(opened["planned_loss_usd"]), Decimal("0.5"))
        rd = [r for r in self.h.kinds(e, "RISK_DECISION") if r.get("approved")][0]
        self.assertEqual(rd["sizing"]["reason"], "SIZING_ONLY_REQUIRES_ATOMIC_GATEWAY")
        self.assertEqual(e.risk.active_reservations(), [])

    def test_closed_episode_accounting(self):
        e = self.eng
        c = self.h.kinds(e, "POSITION_CLOSED")[0]
        self.assertIn(c["exit_reason"], ("TARGET", "STOP", "TIME_EXIT"))
        self.assertGreater(Decimal(c["fees_usd"]), 0)
        # cash + the episode's own sub-step residual (marked at exit) reconciles with net P&L
        self.assertEqual(e.book.cash + Decimal(c["residual_marked_usdt"]), Decimal(100) + Decimal(c["net_pnl_usdt"]))
        step = Decimal("0.000001")
        self.assertLess(e.book.dust["BTC_USDT"], step)          # residual is below one size step
        bid = e.market.latest_book("BTC_USDT")["bid"]
        self.assertEqual(e.book.liquidation_value({"BTC_USDT": bid}, e.fee),
                         e.book.cash + e.book.dust["BTC_USDT"] * bid * (1 - e.fee))
        self.assertEqual(Book.replay(e.journal).fingerprint(), e.book.fingerprint())
        self.assertEqual(e.journal.verify()[0], True)

    def test_snapshots_and_shadow(self):
        e = self.eng
        snaps = self.h.kinds(e, "SNAPSHOT")
        self.assertGreater(len(snaps), 10)
        self.assertIsNotNone(snaps[-1]["btc_benchmark_usd"])
        self.assertTrue(self.h.kinds(e, "SHADOW_OPEN"))
        decisions = self.h.kinds(e, "DECISION")
        self.assertGreater(len(decisions), 5)

    def test_report_validates_and_is_labeled_test_feed(self):
        e = self.eng
        r = build_report(self.h.paths, self.h.m, self.h.clock.now_ms(), journal=e.journal, market=e.market,
                         risk=e.risk, registry=e.registry)
        validate_report(r)
        self.assertIn("TEST FEED", r["source_label"])
        self.assertEqual(r["mode"], "PAPER")
        self.assertEqual(len(r["trades"]), 1)
        self.assertTrue(r["operations"]["reconciled"])
        self.assertIn("NONE (paper)", r["operations"]["protection"])
        self.assertTrue(any(g["status"] != "PASS" for g in r["live_gates"]))
        self.assertEqual(r["learning"]["status"], "UNPROVEN")

    def test_dashboard_server_read_only_and_authenticated(self):
        from http.server import ThreadingHTTPServer
        token = "t" * 40
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.h.paths, self.h.m, self.h.cfg, token,
                                                                   self.h.clock))
        th = threading.Thread(target=httpd.serve_forever, daemon=True)
        th.start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        rows_before = self.eng.journal.count()
        try:
            with urllib.request.urlopen(base + "/") as r:
                self.assertIn("default-src 'none'", r.headers["Content-Security-Policy"])
                self.assertIn(b"CONNECTED LEDGER", r.read())
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(base + "/api/report")
            self.assertEqual(cm.exception.code, 401)
            req = urllib.request.Request(base + "/api/report", headers={"Authorization": "Bearer " + token})
            with urllib.request.urlopen(req) as r:
                report = json.loads(r.read())
            validate_report(report)
            self.assertEqual(report["mode"], "PAPER")
            post = urllib.request.Request(base + "/api/report", data=b"{}", method="POST",
                                          headers={"Authorization": "Bearer " + token})
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(post)
            self.assertEqual(cm.exception.code, 405)
        finally:
            httpd.shutdown()
            httpd.server_close()
        self.assertEqual(self.eng.journal.count(), rows_before)


class Recovery(unittest.TestCase):
    def setUp(self):
        self.h = Harness()

    def tearDown(self):
        self.h.close()

    def open_position(self):
        eng = self.h.engine()
        self.assertTrue(self.h.run(eng, 60, until=lambda: eng.book.open_positions()))
        return eng

    def test_restart_recovers_position_and_fences_old_writer(self):
        eng = self.open_position()
        ep = eng.book.open_positions()[0].episode_id
        with self.assertRaises(LeaseError):
            self.h.engine(holder="second")               # lease still held
        self.h.clock.advance(20)                          # old writer silent past the lease TTL
        eng2 = self.h.engine(holder="second")
        self.assertEqual([p.episode_id for p in eng2.book.open_positions()], [ep])
        with self.assertRaises(LeaseError):
            eng.step()
        self.assertTrue(self.h.kinds(eng2, "RECOVERY"))
        # the restarted engine does not re-evaluate the already-decided bar
        before = eng2.journal.count("DECISION")
        eng2.step()
        self.assertEqual(eng2.journal.count("DECISION"), before)

    def test_loss_latch_blocks_entries_but_unwinds(self):
        eng = self.open_position()
        eng.risk.set_latch("DAILY_LOSS", "test-forced breach", self.h.clock.now_ms())
        self.assertTrue(self.h.run(eng, 60, until=lambda: eng.journal.count("POSITION_CLOSED") > 0))
        closed = self.h.kinds(eng, "POSITION_CLOSED")[0]
        self.assertEqual(closed["exit_reason"], "RISK_UNWIND:DAILY_LOSS")
        eng.strategies["stub"]["strategy"].fired = False
        eng.last_bar.clear()
        self.h.run(eng, 4)
        rejected = [r for r in self.h.kinds(eng, "RISK_DECISION") if not r["approved"]]
        self.assertEqual(rejected[-1]["reason"], "HALT_LATCHED")

    def test_stale_feed_freezes_entries_and_recovers_after_60s(self):
        eng = self.h.engine(stub=False)
        self.h.run(eng, 10)
        self.h.fake.mode = "down"
        self.h.run(eng, 12)
        self.assertIn("DATA_STALE", eng.risk.active_latches())
        self.h.fake.mode = "ok"
        self.h.run(eng, 30)
        self.assertIn("DATA_STALE", eng.risk.active_latches())
        self.h.run(eng, 40)
        self.assertNotIn("DATA_STALE", eng.risk.active_latches())

    def test_rate_limit_ban_is_honored(self):
        self.h.fake.mode = "429"
        n = len(self.h.fake.requests)
        self.h.collector.poll_book("BTC_USDT")
        self.assertGreater(self.h.collector.client.limiter.banned_until_ms, self.h.clock.now_ms() - 1)
        self.h.fake.mode = "ok"
        self.assertEqual(len(self.h.fake.requests), n + 1)

    def test_unqualified_or_zero_edge_strategy_never_trades(self):
        eng = self.h.engine(edge="0", status="UNREGISTERED")
        self.h.run(eng, 20)
        rd = self.h.kinds(eng, "RISK_DECISION")
        self.assertEqual(rd[0]["reason"], "INSUFFICIENT_EDGE_AFTER_COSTS")
        self.assertEqual(eng.journal.count("ORDER_INTENT"), 0)
        self.assertEqual(len(self.h.kinds(eng, "SHADOW_OPEN")), 1)   # still measured, virtually

    def test_deadline_unwinds_and_freezes_report(self):
        eng = self.open_position()
        end = int(self.h.kinds(eng, "EXPERIMENT_STARTED")[0]["end_ms"])
        self.h.clock.t = end + 1000
        # the collector backfills the jump so bars stay current
        for s in self.h.cfg["research_universe"]:
            self.h.collector.backfill(s, "5M", 1)
            self.h.collector.backfill(s, "60M", 3)
        self.assertTrue(self.h.run(eng, 120, until=lambda: current_state(eng.journal) == "COMPLETE"))
        self.assertTrue(self.h.kinds(eng, "EXPERIMENT_COMPLETE"))
        self.assertTrue(list(self.h.paths.reports.glob("final-*.json")))
        self.assertEqual(eng.book.open_positions(), [])


if __name__ == "__main__":
    unittest.main()
