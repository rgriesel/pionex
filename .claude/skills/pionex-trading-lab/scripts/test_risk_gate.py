"""Financial boundary regression tests; not an exchange integration test."""
import copy
import unittest
from decimal import Decimal
from risk_gate import evaluate


def fixture():
    return {
        "context": {
            "mode": "PAPER", "halt_latched": False, "health_ok": True,
            "reconciled": True, "fee_verified": True, "policy_verified": True,
            "live_authorized": False, "strategy_qualified": False,
            "account_isolated": False, "native_protection_verified": False,
            "approved_symbols": ["BTC_USDT"], "book_age_ms": 200,
            "account_age_ms": 500, "slots_used": 0,
            "equity_usd": 100, "initial_capital_usd": 100,
            "day_start_equity_usd": 100, "week_start_equity_usd": 100,
            "high_water_equity_usd": 100, "operating_spend_usd": 0,
            "no_external_cashflows": True, "reserved_planned_risk_usd": 0,
            "reserved_gross_exposure_usd": 0, "free_cash_usd": 100
        },
        "intent": {
            "market_type": "SPOT", "side": "BUY", "symbol": "BTC_USDT",
            "entry_usd": 100, "stop_usd": 98, "spread_bps": 2,
            "roundtrip_cost_bps": 12, "entry_fee_fraction": 0.0005,
            "conservative_gross_edge_bps": 40,
            "quantity_step": "0.0001", "min_quantity": "0.0001",
            "max_quantity": 100, "min_notional_usd": 5
        }
    }


class GateTests(unittest.TestCase):
    def test_planned_risk_includes_costs_and_rounds_down(self):
        r = evaluate(fixture())
        self.assertTrue(r["approved"])
        self.assertLessEqual(Decimal(r["estimated_planned_loss_usd"]), Decimal("0.5"))
        self.assertLessEqual(Decimal(r["notional_usd"]), Decimal("25"))
        self.assertEqual(r["quantity"], "0.2358")

    def test_live_fails_without_all_gates(self):
        p = fixture()
        p["context"]["mode"] = "LIVE"
        self.assertFalse(evaluate(p)["approved"])
        for flag in ("live_authorized", "strategy_qualified", "account_isolated",
                     "native_protection_verified"):
            q = copy.deepcopy(p)
            for other in ("live_authorized", "strategy_qualified", "account_isolated",
                          "native_protection_verified"):
                q["context"][other] = other != flag
            self.assertFalse(evaluate(q)["approved"])

    def test_canary_cap(self):
        p = fixture()
        p["context"].update(mode="LIVE_CANARY", live_authorized=True,
                            strategy_qualified=True, account_isolated=True,
                            native_protection_verified=True)
        r = evaluate(p)
        self.assertTrue(r["approved"])
        self.assertLessEqual(Decimal(r["notional_usd"]), 10)

    def test_missing_nonfinite_negative_and_bool_rejected(self):
        for value in ("NaN", "Infinity", -1, True, None):
            p = fixture()
            p["context"]["equity_usd"] = value
            self.assertFalse(evaluate(p)["approved"])
        p = fixture()
        del p["intent"]["roundtrip_cost_bps"]
        self.assertFalse(evaluate(p)["approved"])

    def test_stale_data_and_halt(self):
        for key, value in (("book_age_ms", 2001), ("account_age_ms", 5001),
                           ("halt_latched", True), ("reconciled", False)):
            p = fixture()
            p["context"][key] = value
            self.assertFalse(evaluate(p)["approved"])

    def test_daily_loss_and_absolute_loss(self):
        p = fixture()
        p["context"].update(equity_usd=98, free_cash_usd=98)
        self.assertEqual(evaluate(p)["reason"], "LOSS_THRESHOLD")
        p["context"].update(equity_usd=90, free_cash_usd=90,
                            day_start_equity_usd=90, week_start_equity_usd=90)
        self.assertEqual(evaluate(p)["reason"], "LOSS_THRESHOLD")

    def test_remaining_day_budget_reserves_existing_risk(self):
        p = fixture()
        p["context"].update(equity_usd=98.3, free_cash_usd=70,
                            reserved_planned_risk_usd=0.2)
        r = evaluate(p)
        self.assertFalse(r["approved"])  # remaining $0.10 cannot meet $5 minimum

    def test_no_rounding_up_to_minimum(self):
        p = fixture()
        p["intent"]["min_notional_usd"] = 30
        self.assertFalse(evaluate(p)["approved"])

    def test_pending_exposure_and_slots_count(self):
        for key, value in (("reserved_gross_exposure_usd", 50),
                           ("reserved_planned_risk_usd", 1), ("slots_used", 2)):
            p = fixture()
            p["context"][key] = value
            self.assertFalse(evaluate(p)["approved"])

    def test_weak_edge_and_cost_budget(self):
        p = fixture()
        p["intent"]["conservative_gross_edge_bps"] = 17
        self.assertFalse(evaluate(p)["approved"])
        p = fixture()
        p["context"]["operating_spend_usd"] = 3
        self.assertFalse(evaluate(p)["approved"])

    def test_no_exit_misclassification(self):
        p = fixture()
        p["intent"]["side"] = "SELL"
        self.assertEqual(evaluate(p)["reason"], "SPOT_BUY_ENTRY_ONLY")

    def test_spot_only_and_approved_symbols(self):
        for key, value in (("market_type", "PERP"), ("symbol", "UNAPPROVED_USDT")):
            p = fixture()
            p["intent"][key] = value
            self.assertFalse(evaluate(p)["approved"])


if __name__ == "__main__":
    unittest.main()
