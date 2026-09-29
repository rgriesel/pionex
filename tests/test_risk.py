import json
import threading
import unittest
from decimal import Decimal

from pionex_lab.ledger.journal import Journal
from pionex_lab.mandate import load_mandate
from pionex_lab.risk.service import LeaseError, ProposalError, RiskService, TrustedContext, validate_proposal
from pionex_lab.util import FakeClock

from helpers import T0, cleanup, copy_config, mandate, tmp_paths

DAY = 86_400_000


def ctx(**kw):
    base = dict(mode="PAPER", health_ok=True, reconciled=True, fee_verified=True, policy_verified=True,
                approved_symbols=["BTC_USDT"], book_age_ms=200, account_age_ms=0, open_positions=0,
                equity_usd=Decimal(100), free_cash_usd=Decimal(100), open_planned_risk_usd=Decimal(0),
                open_exposure_usd=Decimal(0), operating_spend_usd=Decimal(0))
    base.update(kw)
    return TrustedContext(**base)


def proposal(i=0, **kw):
    p = {"decision_id": f"d{i}", "strategy": "s", "version": "v1", "symbol": "BTC_USDT", "side": "BUY",
         "stop": "98", "target": "104", "max_hold_minutes": 240, "reason": "test"}
    p.update(kw)
    return p


INTENT = {"entry_usd": "100", "spread_bps": "2", "roundtrip_cost_bps": "12", "entry_fee_fraction": "0.0005",
          "conservative_gross_edge_bps": "40", "quantity_step": "0.0001", "min_quantity": "0.0001",
          "max_quantity": "100", "min_notional_usd": "5"}


class RiskServiceTests(unittest.TestCase):
    def setUp(self):
        self.paths, self.d = tmp_paths()
        self.clock = FakeClock(T0 + 3_600_000)
        self.m = mandate()
        self.j = Journal(self.paths.ledger)
        self.rs = RiskService(self.m, self.paths.risk, self.clock, journal=self.j)
        self.token = self.rs.acquire_lease("engine-a")

    def tearDown(self):
        cleanup(self.d)

    def test_reference_gate_sizing_and_reservation(self):
        r = self.rs.evaluate_entry(ctx(), proposal(), INTENT, self.token)
        self.assertTrue(r["approved"], r)
        self.assertEqual(r["quantity"], "0.2358")  # identical to the skill's reference test
        self.assertLessEqual(Decimal(r["estimated_planned_loss_usd"]), Decimal("0.5"))
        self.assertEqual(len(self.rs.active_reservations()), 1)

    def test_live_mode_refused(self):
        r = self.rs.evaluate_entry(ctx(mode="LIVE"), proposal(), INTENT, self.token)
        self.assertFalse(r["approved"])
        self.assertTrue(r["reason"].startswith("LIVE_GATE_"))

    def test_proposal_cannot_carry_limits_or_balances(self):
        for extra in ({"risk_per_trade_fraction": 0.5}, {"equity_usd": 1e6}, {"conservative_gross_edge_bps": 999},
                      {"strategy_qualified": True}):
            with self.assertRaisesRegex(ProposalError, "PROPOSAL_SCHEMA"):
                validate_proposal(proposal(**extra))
        with self.assertRaises(ProposalError):
            validate_proposal(proposal(side="SELL"))
        with self.assertRaises(ProposalError):
            validate_proposal(proposal(max_hold_minutes=600))

    def test_reservations_are_atomic_across_writers(self):
        """Two concurrent entries with one slot left: exactly one is approved."""
        results = []
        other = RiskService(self.m, self.paths.risk, self.clock)
        other.token, other.holder = self.token, "engine-a"

        def go(svc, i):
            results.append(svc.evaluate_entry(ctx(open_positions=1), proposal(i), INTENT, self.token))
        ts = [threading.Thread(target=go, args=(svc, i)) for i, svc in enumerate((self.rs, other))]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(sum(1 for r in results if r["approved"]), 1, results)
        self.assertEqual({r["reason"] for r in results if not r["approved"]}, {"POSITION_LIMIT"})

    def test_existing_reservations_consume_budget(self):
        self.assertTrue(self.rs.evaluate_entry(ctx(), proposal(1), INTENT, self.token)["approved"])
        # 2 x 0.5% planned risk fits the 1% aggregate cap and 2 x 23.6% fits 50% exposure
        second = self.rs.evaluate_entry(ctx(), proposal(2), INTENT, self.token)
        self.assertTrue(second["approved"])
        self.assertEqual(second["gate_context"]["reserved_planned_risk_usd"],
                         str(Decimal(self.rs.active_reservations()[0]["planned_risk"])))
        third = self.rs.evaluate_entry(ctx(), proposal(3), INTENT, self.token)
        self.assertEqual(third["reason"], "POSITION_LIMIT")  # two reservations occupy both slots
        self.rs.settle_reservation(self.rs.active_reservations()[0]["id"], "RELEASED")
        # remaining aggregate budget: 1.00 - 0.60 open - ~0.50 reserved < 0 -> nothing left
        fourth = self.rs.evaluate_entry(ctx(open_planned_risk_usd=Decimal("0.6")), proposal(4), INTENT, self.token)
        self.assertEqual(fourth["reason"], "NO_REMAINING_BUDGET")

    def test_stale_fencing_token_rejected(self):
        self.clock.advance(20)
        other = RiskService(self.m, self.paths.risk, self.clock)
        new_token = other.acquire_lease("engine-b")
        self.assertGreater(new_token, self.token)
        self.assertEqual(self.rs.evaluate_entry(ctx(), proposal(), INTENT, self.token)["reason"],
                         "STALE_FENCING_TOKEN")
        with self.assertRaises(LeaseError):
            self.rs.renew_lease()

    def test_lease_blocks_second_writer(self):
        with self.assertRaises(LeaseError):
            RiskService(self.m, self.paths.risk, self.clock).acquire_lease("engine-b")

    def test_daily_latch_persists_and_clears_only_after_period(self):
        self.rs.observe_equity(Decimal(100), self.clock.now_ms())
        new = self.rs.observe_equity(Decimal("97.9"), self.clock.now_ms())
        self.assertEqual(new, ["DAILY_LOSS"])
        self.assertIn("HALT_LATCHED", self.rs.evaluate_entry(ctx(equity_usd=Decimal("97.9")), proposal(), INTENT,
                                                             self.token)["reason"])
        # restart: latch survives
        rs2 = RiskService(self.m, self.paths.risk, self.clock)
        self.assertIn("DAILY_LOSS", rs2.active_latches())
        self.rs.observe_equity(Decimal("99"), self.clock.now_ms())   # recovery same day does not clear
        self.assertIn("DAILY_LOSS", self.rs.active_latches())
        self.clock.advance(DAY / 1000)
        self.rs.observe_equity(Decimal("99"), self.clock.now_ms())
        self.assertNotIn("DAILY_LOSS", self.rs.active_latches())

    def test_review_latches_never_auto_clear(self):
        self.rs.observe_equity(Decimal(100), self.clock.now_ms())
        self.rs.observe_equity(Decimal("89.9"), self.clock.now_ms())
        latches = self.rs.active_latches()
        self.assertIn("ABSOLUTE_LOSS", latches)
        self.assertIn("PEAK_DRAWDOWN", latches)
        for _ in range(3):
            self.clock.advance(8 * DAY / 1000)
            self.rs.observe_equity(Decimal("95"), self.clock.now_ms())
        self.assertIn("ABSOLUTE_LOSS", self.rs.active_latches())
        self.assertIn("DAILY_LOSS", self.rs.active_latches())  # blocked by the review latch
        with self.assertRaises(ValueError):
            self.rs.review_clear("ABSOLUTE_LOSS", "me", "short", self.clock.now_ms())
        self.rs.review_clear("ABSOLUTE_LOSS", "reviewer", "Reviewed the loss and mandate; decided to continue paper",
                             self.clock.now_ms())
        self.assertNotIn("ABSOLUTE_LOSS", self.rs.active_latches())
        kinds = [k for _, _, k, _ in self.j.events(("LATCH_SET", "LATCH_CLEARED"))]
        self.assertIn("LATCH_CLEARED", kinds)

    def test_fixed_dollar_ceiling_does_not_compound(self):
        self.rs.observe_equity(Decimal(150), self.clock.now_ms())
        f = self.rs.floors()
        self.assertEqual(f["absolute"], Decimal(90))           # never initial+gains-10
        self.assertEqual(f["peak"], Decimal(135))

    def test_transient_latch_needs_sixty_healthy_seconds(self):
        now = self.clock.now_ms()
        self.rs.observe_health("DATA_STALE", False, "gap", now)
        self.rs.observe_health("DATA_STALE", True, "", now + 1000)
        self.rs.observe_health("DATA_STALE", True, "", now + 30_000)
        self.assertIn("DATA_STALE", self.rs.active_latches())
        self.rs.observe_health("DATA_STALE", False, "gap again", now + 40_000)
        self.rs.observe_health("DATA_STALE", True, "", now + 41_000)
        self.rs.observe_health("DATA_STALE", True, "", now + 100_000)
        self.assertIn("DATA_STALE", self.rs.active_latches())
        self.rs.observe_health("DATA_STALE", True, "", now + 101_001)
        self.assertNotIn("DATA_STALE", self.rs.active_latches())

    def test_policy_tamper_latches(self):
        cfg = copy_config(self.paths.root / "cfg")
        rs = RiskService(load_mandate(cfg), self.paths.root / "r2.db", self.clock, config_dir=cfg)
        self.assertTrue(rs.verify_policy(None))
        raw = json.loads((cfg / "mandate.v1.json").read_text())
        raw["risk"]["max_positions"] = 5
        (cfg / "mandate.v1.json").write_text(json.dumps(raw))
        self.assertFalse(rs.verify_policy(None))
        self.assertIn("POLICY_TAMPER", rs.active_latches())

    def test_operating_cost_ceiling(self):
        self.rs.observe_equity(Decimal(100), self.clock.now_ms(), operating_spend=Decimal(3))
        self.assertIn("OPERATING_COST_CEILING", self.rs.active_latches())


if __name__ == "__main__":
    unittest.main()
