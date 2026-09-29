import hashlib
import json
import sqlite3
import unittest
from decimal import Decimal
from pathlib import Path

from pionex_lab.cli import SKILL_DIR, SKILL_HASHES
from pionex_lab.data.quality import check_bars, window_ready
from pionex_lab.exchange import pionex_public as pp
from pionex_lab.exchange.ratelimit import WeightedLimiter
from pionex_lab.execution import dryrun
from pionex_lab.ledger.journal import Journal
from pionex_lab.mandate import PolicyError, load_mandate
from pionex_lab.util import PROJECT_ROOT, FakeClock

from helpers import T0, cleanup, copy_config, make_bars, tmp_paths


class SkillIntegrity(unittest.TestCase):
    def test_installed_skill_hashes_match_handoff(self):
        for rel, expected in SKILL_HASHES.items():
            self.assertEqual(hashlib.sha256((SKILL_DIR / rel).read_bytes()).hexdigest(), expected, rel)

    def test_vendored_gate_is_byte_identical(self):
        vendored = PROJECT_ROOT / "pionex_lab/risk/risk_gate_ref.py"
        self.assertEqual(vendored.read_bytes(), (SKILL_DIR / "scripts/risk_gate.py").read_bytes())

    def test_config_mandate_is_the_skill_mandate(self):
        self.assertEqual((PROJECT_ROOT / "config/mandate.v1.json").read_bytes(),
                         (SKILL_DIR / "assets/mandate.json").read_bytes())
        m = load_mandate(PROJECT_ROOT / "config")
        self.assertFalse(m.live_enabled)
        self.assertEqual(m.mode, "PAPER")


class MandateTamper(unittest.TestCase):
    def setUp(self):
        self.paths, self.d = tmp_paths()
        self.cfg = copy_config(self.paths.root / "config")

    def tearDown(self):
        cleanup(self.d)

    def test_edit_breaks_lock(self):
        p = self.cfg / "mandate.v1.json"
        raw = json.loads(p.read_text())
        raw["risk"]["risk_per_trade_fraction"] = 0.05  # an agent trying to raise a limit
        p.write_text(json.dumps(raw))
        with self.assertRaises(PolicyError):
            load_mandate(self.cfg)

    def test_relocked_raised_limit_still_rejected(self):
        p = self.cfg / "mandate.v1.json"
        raw = json.loads(p.read_text())
        raw["risk"]["daily_loss_fraction"] = 0.2
        p.write_text(json.dumps(raw))
        lock = json.loads((self.cfg / "mandate.lock.json").read_text())
        lock["sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
        (self.cfg / "mandate.lock.json").write_text(json.dumps(lock))
        with self.assertRaisesRegex(PolicyError, "REFERENCE_GATE_MISMATCH"):
            load_mandate(self.cfg)

    def test_live_enabled_without_authorization_rejected(self):
        p = self.cfg / "mandate.v1.json"
        raw = json.loads(p.read_text())
        raw["authority"]["live_enabled"] = True
        p.write_text(json.dumps(raw))
        lock = json.loads((self.cfg / "mandate.lock.json").read_text())
        lock["sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
        (self.cfg / "mandate.lock.json").write_text(json.dumps(lock))
        with self.assertRaisesRegex(PolicyError, "LIVE_ENABLED_WITHOUT_AUTHORIZATION"):
            load_mandate(self.cfg)


class JournalChain(unittest.TestCase):
    def setUp(self):
        self.paths, self.d = tmp_paths()

    def tearDown(self):
        cleanup(self.d)

    def test_append_only_and_verifiable(self):
        j = Journal(self.paths.ledger)
        for i in range(5):
            j.append("INCIDENT", {"i": i, "amount": Decimal("1.10")}, T0 + i)
        self.assertEqual(j.verify(), (True, None, 5))
        with self.assertRaises(sqlite3.DatabaseError):
            j.conn.execute("UPDATE journal SET payload='{}' WHERE seq=2")
        with self.assertRaises(sqlite3.DatabaseError):
            j.conn.execute("DELETE FROM journal WHERE seq=2")
        ro = Journal(self.paths.ledger, readonly=True)
        with self.assertRaises(PermissionError):
            ro.append("INCIDENT", {}, T0)
        self.assertEqual(list(ro.events(("INCIDENT",)))[1][3]["amount"], "1.10")

    def test_out_of_band_edit_detected(self):
        j = Journal(self.paths.ledger)
        for i in range(4):
            j.append("INCIDENT", {"i": i}, T0 + i)
        j.close()
        raw = sqlite3.connect(self.paths.ledger)
        raw.execute("DROP TRIGGER journal_no_update")
        raw.execute("UPDATE journal SET payload='{\"i\":99}' WHERE seq=3")
        raw.commit()
        raw.close()
        ok, bad, _ = Journal(self.paths.ledger, readonly=True).verify()
        self.assertFalse(ok)
        self.assertEqual(bad, 3)

    def test_unknown_kind_rejected(self):
        with self.assertRaises(ValueError):
            Journal(self.paths.ledger).append("SET_LIMIT", {}, T0)


class Parsers(unittest.TestCase):
    def test_envelope_rejects_failure(self):
        with self.assertRaises(pp.ExchangeError):
            pp.parse_envelope({"result": False, "code": "X", "message": "no"})

    def test_book_ticker_validation(self):
        ok = {"tickers": [{"symbol": "BTC_USDT", "bidPrice": "100", "bidSize": "1", "askPrice": "100.1",
                           "askSize": "1", "timestamp": 1}]}
        bt = pp.parse_book_tickers(ok)[0]
        self.assertEqual(bt.bid, Decimal("100"))
        for bad in ({"bidPrice": "101"}, {"askPrice": "NaN"}, {"bidSize": "-1"}, {"askPrice": None},
                    {"bidPrice": True}):
            t = json.loads(json.dumps(ok))
            t["tickers"][0].update(bad)
            with self.assertRaises(pp.SchemaError, msg=bad):
                pp.parse_book_tickers(t)

    def test_depth_ordering_and_klines(self):
        with self.assertRaises(pp.SchemaError):
            pp.parse_depth({"bids": [["1", "1"], ["2", "1"]], "asks": [["3", "1"]]})
        with self.assertRaises(pp.SchemaError):
            pp.parse_klines({"klines": [{"time": 1, "open": "2", "high": "1.5", "low": "1", "close": "1.2",
                                         "volume": "1"}]})
        kl = pp.parse_klines({"klines": [{"time": 600, "open": "1", "high": "2", "low": "1", "close": "2",
                                          "volume": "3"}, {"time": 300, "open": "1", "high": "1", "low": "1",
                                                           "close": "1", "volume": "0"}]})
        self.assertEqual([k.open_time for k in kl], [300, 600])

    def test_symbol_rules_incomplete_flagged(self):
        r = pp.parse_symbols({"symbols": [{"symbol": "X_USDT", "enable": True, "basePrecision": 4,
                                           "quotePrecision": 2}]})[0]
        complete, missing = r.complete()
        self.assertFalse(complete)
        self.assertIn("minAmount", missing)

    def test_plain_http_only_for_loopback(self):
        with self.assertRaises(ValueError):
            pp.PionexPublic("http://api.pionex.com")
        pp.PionexPublic("http://127.0.0.1:9")


class DryRun(unittest.TestCase):
    rules = pp.parse_symbols({"symbols": [{"symbol": "BTC_USDT", "enable": True, "basePrecision": 6,
                                           "quotePrecision": 2, "amountPrecision": 2, "minAmount": "10",
                                           "minTradeSize": "0.000001", "maxTradeSize": "1000",
                                           "minTradeDumping": "0.00001", "maxTradeDumping": "100"}]})[0]

    def test_official_field_rules(self):
        r = dryrun.build_order_request(self.rules, "BUY", "LIMIT", "c1", size=Decimal("0.0002"),
                                       price=Decimal("60000.10"), ioc=True)
        self.assertEqual(r["args"], {"symbol": "BTC_USDT", "side": "BUY", "type": "LIMIT", "clientOrderId": "c1",
                                     "size": "0.0002", "price": "60000.1", "IOC": True})
        self.assertFalse(r["sent"])
        self.assertEqual(r["path"], "/api/v1/trade/order")
        for kwargs, code in (({"size": Decimal("0.0002")}, "LIMIT_REQUIRES"),
                             ({"size": Decimal("0.0000001"), "price": Decimal("60000")}, "SIZE_PRECISION"),
                             ({"size": Decimal("0.0001"), "price": Decimal("60000")}, "NOTIONAL_BELOW"),
                             ({"size": Decimal("0.001"), "price": Decimal("60000.001")}, "PRICE_PRECISION")):
            with self.assertRaisesRegex(dryrun.DryRunError, code):
                dryrun.build_order_request(self.rules, "BUY", "LIMIT", "c", **kwargs)
        with self.assertRaisesRegex(dryrun.DryRunError, "MARKET_BUY_REQUIRES_AMOUNT"):
            dryrun.build_order_request(self.rules, "BUY", "MARKET", "c", size=Decimal("1"))
        with self.assertRaisesRegex(dryrun.DryRunError, "SIZE_BELOW_MINIMUM"):
            dryrun.build_order_request(self.rules, "SELL", "MARKET", "c", size=Decimal("0.000001"))
        with self.assertRaisesRegex(dryrun.DryRunError, "CLIENT_ORDER_ID"):
            dryrun.build_order_request(self.rules, "SELL", "MARKET", "x" * 65, size=Decimal("0.001"))

    def test_official_cli_cross_check(self):
        cli = dryrun.find_official_cli()
        if not cli:
            self.skipTest("official pionex-trade-cli not installed (npm ci --prefix tools/pionex-cli)")
        req = dryrun.preview(self.rules, cli, side="SELL", type_="MARKET", client_order_id="pl-x-test",
                             size=Decimal("0.00123"))
        self.assertEqual(req["preview_source"], "official pionex-trade-cli --dry-run")
        req = dryrun.preview(self.rules, cli, side="BUY", type_="LIMIT", client_order_id="pl-e-test",
                             size=Decimal("0.0005"), price=Decimal("61000.5"), ioc=True)
        self.assertEqual(req["args"]["IOC"], True)


class Limiter(unittest.TestCase):
    def test_exit_headroom_and_ban(self):
        clock = FakeClock(T0)
        lim = WeightedLimiter(5.0, exit_reserve=1.0, clock=clock)
        grants = sum(lim.try_acquire(1) for _ in range(10))
        self.assertEqual(grants, 4)             # one weight held back for exits
        self.assertTrue(lim.try_acquire(1, "exit"))
        pause = lim.ban(7)
        self.assertEqual(pause, 7)
        clock.advance(6)
        self.assertFalse(lim.try_acquire(1, "exit"))
        clock.advance(2)
        self.assertTrue(lim.try_acquire(1))


class Quality(unittest.TestCase):
    def test_gaps_invalid_and_freshness(self):
        b = make_bars("BTC_USDT", "5M", [100 + i * 0.1 for i in range(30)])
        self.assertTrue(check_bars(b).ok)
        g = b.slice(0, 10)
        g2 = b.slice(12, 30)
        for arr in ("t", "o", "h", "l", "c", "v"):
            getattr(g, arr).extend(getattr(g2, arr))
        q = check_bars(g)
        self.assertEqual(q.missing_bars, 2)
        now = b.t[-1] + 300_000 + 1000
        self.assertEqual(window_ready(b, 20, now)[0], True)
        self.assertEqual(window_ready(b, 20, now + 3_600_000), (False, "STALE_BARS"))
        self.assertEqual(window_ready(g, 25, now), (False, "DATA_GAP"))
        b.h[5] = b.l[5] * 0.5
        self.assertTrue(check_bars(b).invalid)


if __name__ == "__main__":
    unittest.main()
