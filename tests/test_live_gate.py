"""CLO-43: proof gate + capped live executor. Synthetic data only; no network, no real keys."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pionex_lab.live import executor as ex
from pionex_lab.live import gate
from pionex_lab.mandate import load_mandate
from pionex_lab.paths import Paths

DAY = 86_400_000
NOW = 1_800_000_000_000
LOG_HEAD = "# log\n\n## Red Team registry\n\n| strategy_id | verdict | date | evidence |\n|---|---|---|---|\n"
BASE_MANDATE = Path(__file__).resolve().parent.parent / "config" / "mandate.v1.json"


def mk_mandate(cfg: Path, **over):
    """A LIVE-armed test mandate in a temp config dir (the real mandate is never touched)."""
    raw = json.loads(BASE_MANDATE.read_text(encoding="utf-8"))
    raw["risk"].update({"spot_only": True, "leverage": 1})
    raw["authority"].update({"mode": "LIVE", "live_enabled": True, "authorization_record": "owner-test",
                             "account_scope": "spot"})
    raw["execution"]["allowed_symbols"] = ["BTC_USDT"]
    for k, v in over.items():
        sec, key = k.split("__")
        raw[sec][key] = v
    data = json.dumps(raw, indent=1).encode()
    sha = hashlib.sha256(data).hexdigest()
    (cfg / "mandate.v1.json").write_bytes(data)
    (cfg / "mandate.lock.json").write_text(json.dumps({"mandate_file": "mandate.v1.json", "schema_version": 1,
                                                       "sha256": sha}))
    return sha


def mk_grid_db(var: Path, gid="g1", days=31, trips=25, end_eq=1010.0, dip=None, invest=1000.0, age_h=1):
    db = sqlite3.connect(var / "shadow_grid.db")
    db.executescript(
        "CREATE TABLE IF NOT EXISTS grids(id TEXT PRIMARY KEY, symbol TEXT, params TEXT, created_ts INTEGER, start_price REAL);"
        "CREATE TABLE IF NOT EXISTS snaps(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, grid_id TEXT, price REAL, equity REAL, trips INTEGER);")
    p = {"symbol": "BTC_USDT", "invest": invest, "rows": 10, "top": 70000, "bottom": 60000}
    db.execute("INSERT INTO grids VALUES(?,?,?,?,?)", (gid, "BTC_USDT", json.dumps(p), 0, 65000))
    t1 = NOW - age_h * 3_600_000
    t0 = t1 - int(days * DAY)
    db.execute("INSERT INTO snaps(ts,grid_id,price,equity,trips) VALUES(?,?,?,?,?)", (t0, gid, 65000, invest, 0))
    if dip:
        db.execute("INSERT INTO snaps(ts,grid_id,price,equity,trips) VALUES(?,?,?,?,?)", ((t0 + t1) // 2, gid, 1, dip, 5))
    db.execute("INSERT INTO snaps(ts,grid_id,price,equity,trips) VALUES(?,?,?,?,?)", (t1, gid, 65000, end_eq, trips))
    db.commit()
    db.close()


class GateRules(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.var = Path(self.d.name)
        self.cfg = self.var / "cfg"
        self.cfg.mkdir()
        mk_mandate(self.cfg)
        self.m = load_mandate(self.cfg)
        self.log = self.var / "log.md"
        self.log.write_text(LOG_HEAD + "| g1 | HOLDS | 2026-10-20 | r.md |\n", encoding="utf-8")

    def tearDown(self):
        self.d.cleanup()

    def res(self):
        return {x.strategy_id: x for x in gate.evaluate_all(self.var, self.log, self.m, NOW)}

    def failed(self, sid="g1"):
        return {c.rule for c in self.res()[sid].checks if not c.ok}

    def test_all_pass_is_eligible(self):
        mk_grid_db(self.var)
        self.assertTrue(self.res()["g1"].eligible)

    def test_too_few_days(self):
        mk_grid_db(self.var, days=29.5)
        self.assertEqual(self.failed(), {"forward_days"})

    def test_too_few_trades(self):
        mk_grid_db(self.var, trips=19)
        self.assertEqual(self.failed(), {"closed_trades"})

    def test_not_profitable(self):
        mk_grid_db(self.var, end_eq=1000.0)
        self.assertEqual(self.failed(), {"net_profit_after_fees"})

    def test_drawdown_limit_from_mandate(self):
        mk_grid_db(self.var, dip=880.0, end_eq=1010.0)          # 12% > 10%
        self.assertEqual(self.failed(), {"max_drawdown"})
        mk_grid_db(self.var, gid="g2", dip=920.0, end_eq=1010.0)   # 8% <= 10%
        self.log.write_text(LOG_HEAD + "| g2 | HOLDS | d | e |\n", encoding="utf-8")
        self.assertTrue(self.res()["g2"].eligible)

    def test_stale_record(self):
        mk_grid_db(self.var, age_h=49)
        self.assertEqual(self.failed(), {"record_fresh"})

    def test_no_redteam_row(self):
        mk_grid_db(self.var)
        self.log.write_text(LOG_HEAD, encoding="utf-8")
        self.assertEqual(self.failed(), {"redteam_holds"})

    def test_missing_log_file(self):
        mk_grid_db(self.var)
        self.log.unlink()
        self.assertEqual(self.failed(), {"redteam_holds"})

    def test_later_row_revokes(self):
        mk_grid_db(self.var)
        self.log.write_text(LOG_HEAD + "| g1 | HOLDS | d | a |\n| g1 | BREAKS | d | b |\n", encoding="utf-8")
        self.assertEqual(self.failed(), {"redteam_holds"})

    def test_verdict_must_be_exact(self):
        mk_grid_db(self.var)
        for v in ("HOLDS WITH FIXES", "holds", "NOT HOLDS", "HOLDS?"):
            self.log.write_text(LOG_HEAD + f"| g1 | {v} | d | e |\n", encoding="utf-8")
            self.assertEqual(self.failed(), {"redteam_holds"}, v)

    def test_holds_text_outside_registry_ignored(self):
        mk_grid_db(self.var)
        self.log.write_text("| g1 | HOLDS | d | e |\n" + LOG_HEAD, encoding="utf-8")
        self.assertEqual(self.failed(), {"redteam_holds"})

    def test_row_in_later_section_ignored(self):
        mk_grid_db(self.var)
        self.log.write_text(LOG_HEAD + "\n## Other\n\n| g1 | HOLDS | d | e |\n", encoding="utf-8")
        self.assertEqual(self.failed(), {"redteam_holds"})

    def test_unknown_strategy_never_eligible(self):
        mk_grid_db(self.var)
        self.assertNotIn("zzz", self.res())
        self.assertEqual(gate.eligible_ids(gate.evaluate_all(self.var, self.log, self.m, NOW)), {"g1"})

    def test_no_snapshots(self):
        mk_grid_db(self.var)
        db = sqlite3.connect(self.var / "shadow_grid.db")
        db.execute("DELETE FROM snaps")
        db.commit()
        db.close()
        self.assertFalse(self.res()["g1"].eligible)

    def test_book_rules(self):
        db = sqlite3.connect(self.var / "forward_shadow.db")
        db.executescript("CREATE TABLE books(id TEXT PRIMARY KEY, params TEXT, created_ts INTEGER);"
                         "CREATE TABLE fills(id INTEGER PRIMARY KEY, ts INTEGER, book TEXT, side TEXT);"
                         "CREATE TABLE equity(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, book TEXT, equity REAL);")
        db.execute("INSERT INTO books VALUES('b1',?,0)", (json.dumps({"usdt": 100.0}),))
        t1 = NOW - 3_600_000
        db.execute("INSERT INTO equity(ts,book,equity) VALUES(?,?,?)", (t1 - 35 * DAY, "b1", 100.0))
        db.execute("INSERT INTO equity(ts,book,equity) VALUES(?,?,?)", (t1, "b1", 103.0))
        for i in range(20):
            db.execute("INSERT INTO fills(ts,book,side) VALUES(?,?,?)", (i, "b1", "SELL"))
        db.commit()
        db.close()
        self.log.write_text(LOG_HEAD + "| b1 | HOLDS | d | e |\n", encoding="utf-8")
        self.assertTrue(self.res()["b1"].eligible)
        self.assertEqual(self.res()["b1"].kind, "book")

    def test_max_drawdown_counts_start_as_peak(self):
        self.assertAlmostEqual(gate.max_drawdown([90, 120, 108], 100), 0.10)


class FakeTransport:
    def __init__(self):
        self.calls = []

    def request(self, method, path, query=None, body=None):
        self.calls.append((method, path, body))
        return {"result": True, "data": {"buOrderId": "BU1", "orderId": "O1", "min_investment": "10"}}


class ExecutorRules(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.var = Path(self.d.name)
        self.cfg = self.var / "cfg"
        self.cfg.mkdir()
        self.sha = mk_mandate(self.cfg)
        self.log = self.var / "log.md"
        self.log.write_text(LOG_HEAD + "| g1 | HOLDS | d | e |\n", encoding="utf-8")
        mk_grid_db(self.var, end_eq=1010.0)
        self.pin(self.sha)
        self.notes = []
        self.made = []
        self.paths = Paths(self.var)

    def tearDown(self):
        for e in self.made:
            e.journal.db.close()
        self.d.cleanup()

    def pin(self, sha, **extra):
        (self.var / "live.json").write_text(json.dumps({"approved_mandate_sha256": sha, "key_file": "x.env", **extra}))

    def mk(self, armed=True, **kw):
        tr = FakeTransport()
        kw.setdefault("clock", lambda: NOW / 1000)
        kw.update(notifier=lambda t, level="important": self.notes.append(t), config_dir=self.cfg)
        e = (ex.Executor.armed(self.paths, self.log, transport=tr, **kw) if armed
             else ex.Executor(self.paths, self.log, **kw))
        self.made.append(e)
        return e, tr

    def grid(self, invest=10.0, sid="g1", symbol="BTC_USDT"):
        return ex.Action(sid, "grid_create", symbol, {"invest": invest, "rows": 10, "top": 70000, "bottom": 60000})

    def test_happy_path_sends_grid(self):
        e, tr = self.mk()
        self.assertEqual(e.execute(self.grid())["status"], "SENT")
        self.assertEqual(tr.calls[-1][1], "/api/v1/bot/orders/spotGrid/create")
        self.assertTrue(self.notes)

    def test_kill_switch_file_blocks_arming(self):
        (self.var / "LIVE_STOP").write_text("x")
        with self.assertRaises(ex.Refused):
            self.mk()

    def test_kill_switch_after_arming(self):
        e, tr = self.mk()
        (self.var / "LIVE_STOP").write_text("x")
        self.assertEqual(e.execute(self.grid())["status"], "REFUSED")
        self.assertEqual(tr.calls, [])

    def test_live_disabled(self):
        self.pin(mk_mandate(self.cfg, authority__live_enabled=False))
        with self.assertRaises(ex.Refused):
            self.mk()

    def test_mode_paper(self):
        self.pin(mk_mandate(self.cfg, authority__mode="PAPER"))
        with self.assertRaises(ex.Refused):
            self.mk()

    def test_lock_mismatch(self):
        p = self.cfg / "mandate.v1.json"
        p.write_text(p.read_text() + " ")
        with self.assertRaises(ex.Refused):
            self.mk()

    def test_owner_pin_mismatch_and_missing(self):
        self.pin("0" * 64)
        with self.assertRaises(ex.Refused):
            self.mk()
        (self.var / "live.json").unlink()
        with self.assertRaises(ex.Refused):
            self.mk()

    def test_mandate_with_leverage_or_futures_does_not_load(self):
        self.pin(mk_mandate(self.cfg, risk__leverage=40, risk__spot_only=False))
        with self.assertRaises(ex.Refused):
            self.mk()

    def test_empty_allowed_symbols(self):
        self.pin(mk_mandate(self.cfg, execution__allowed_symbols=[]))
        with self.assertRaises(ex.Refused):
            self.mk()

    def test_ineligible_strategy_refused(self):
        e, tr = self.mk()
        self.log.write_text(LOG_HEAD, encoding="utf-8")
        self.assertEqual(e.execute(self.grid())["status"], "REFUSED")
        self.assertEqual(tr.calls, [])

    def test_unknown_strategy_refused(self):
        e, tr = self.mk()
        self.assertEqual(e.execute(self.grid(sid="nope"))["status"], "REFUSED")
        self.assertEqual(tr.calls, [])

    def test_owner_allowlist(self):
        self.pin(self.sha, strategy_allowlist=["other"])
        e, _ = self.mk()
        self.assertEqual(e.execute(self.grid())["status"], "REFUSED")

    def test_symbol_not_allowed(self):
        e, _ = self.mk()
        self.assertEqual(e.execute(self.grid(symbol="ETH_USDT"))["status"], "REFUSED")

    def test_position_cap(self):
        e, tr = self.mk()                      # canary: 10% of 100 = 10
        self.assertEqual(e.execute(self.grid(invest=10.01))["status"], "REFUSED")
        self.assertEqual(tr.calls, [])

    def test_capital_is_at_most_100(self):
        e, _ = self.mk()
        self.assertLessEqual(e.limits(e.preflight()[1])["capital"], 100)
        self.assertEqual(ex.LIVE_CAP_USDT, 100)
        self.assertEqual(e.execute(self.grid(invest=50))["status"], "REFUSED")

    def test_max_positions(self):
        e, _ = self.mk()
        self.assertEqual(e.execute(self.grid())["status"], "SENT")
        self.assertEqual(e.execute(self.grid())["status"], "SENT")
        self.assertEqual(e.execute(self.grid())["status"], "REFUSED")

    def test_leverage_param_refused(self):
        e, _ = self.mk()
        a = ex.Action("g1", "spot_order", "BTC_USDT", {"side": "BUY", "type": "MARKET", "amount": 5, "leverage": 2})
        self.assertEqual(e.execute(a)["status"], "REFUSED")

    def test_futures_refused(self):
        e, tr = self.mk()
        self.assertEqual(e.execute(ex.Action("g1", "futures_order", "BTC_USDT", {}))["status"], "REFUSED")
        self.assertEqual(tr.calls, [])

    def test_endpoint_allowlist(self):
        t = ex.Transport(object())
        for m, p in (("POST", "/api/v1/account/withdraw"), ("GET", "/api/v1/account/balances"),
                     ("DELETE", "/api/v1/trade/order")):
            with self.assertRaises(ex.Refused):
                t.request(m, p)

    def test_cancel_own_bot_only_and_exempt_from_gate(self):
        e, _ = self.mk()
        self.assertEqual(e.execute(self.grid())["status"], "SENT")
        self.log.write_text(LOG_HEAD, encoding="utf-8")            # revoked: new risk refused, cancel allowed
        self.assertEqual(e.execute(self.grid())["status"], "REFUSED")
        bad = ex.Action("g1", "grid_cancel", "BTC_USDT", {"bu_order_id": "someone-else"})
        self.assertEqual(e.execute(bad)["status"], "REFUSED")
        ok = ex.Action("g1", "grid_cancel", "BTC_USDT", {"bu_order_id": "BU1"})
        self.assertEqual(e.execute(ok)["status"], "SENT")
        self.assertEqual(e.journal.open_bots(), [])

    def test_daily_loss_halts_and_blocks(self):
        e, tr = self.mk()
        e.observe_pnl(0.0)
        n = len(tr.calls)
        self.assertEqual(e.observe_pnl(-2.5)["halt"], "DAY")       # > 2% of 100
        self.assertEqual(e.execute(self.grid())["status"], "REFUSED")
        self.assertEqual(len(tr.calls), n)

    def test_absolute_loss_halts_permanently(self):
        e, _ = self.mk()
        self.assertEqual(e.observe_pnl(-10.0)["halt"], "ABS")
        with self.assertRaises(ex.Refused):
            self.mk()

    def test_dry_run_has_no_transport_and_journals(self):
        e, tr = self.mk(armed=False)
        self.assertIsNone(e.transport)
        self.assertEqual(e.execute(self.grid())["status"], "PLANNED")
        self.assertEqual(tr.calls, [])
        self.assertEqual(e.journal.db.execute("SELECT mode FROM actions").fetchone()[0], "DRYRUN")

    def test_dry_run_reports_why_live_is_blocked(self):
        self.pin(mk_mandate(self.cfg, authority__mode="PAPER", authority__live_enabled=False,
                            authority__authorization_record=None))
        e, _ = self.mk(armed=False)
        r = e.execute(self.grid())
        self.assertEqual(r["status"], "PLANNED")
        self.assertTrue(r["blocked_by"])

    def test_plan_clamps_to_caps(self):
        e, _ = self.mk(armed=False)
        m = e.preflight()[1]
        plans = ex.plan_grid_creates(e, gate.evaluate_all(self.var, self.log, m, NOW), m)
        self.assertEqual([a.strategy_id for a in plans], ["g1"])
        self.assertLessEqual(plans[0].params["invest"], 10.0)

    def test_credentials_never_leak(self):
        from pionex_lab.exchange.account import Credentials

        def boom(*a, **k):
            raise OSError("boom")
        t = ex.Transport(Credentials("KEYVALUE123", "SECRETVALUE456", "src"), opener=boom)
        self.assertNotIn("SECRETVALUE456", repr(t))
        with self.assertRaises(ex.Refused) as cm:
            t.request("GET", "/api/v1/bot/orders")
        self.assertNotIn("SECRETVALUE456", str(cm.exception))
        self.assertNotIn("KEYVALUE123", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
