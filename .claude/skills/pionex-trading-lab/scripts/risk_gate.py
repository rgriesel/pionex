#!/usr/bin/env python3
"""Offline spot BUY sizing reference. No exchange, signer, reservations, or exits.

All monetary inputs are USD valuations from a trusted, reconciled gateway.
Invoke with one {context, intent} JSON object on stdin. Missing/invalid data fails
closed. Approval is a sizing result, not authority or evidence to place an order.
"""
import json
import sys
from decimal import Decimal, InvalidOperation, ROUND_DOWN, getcontext

getcontext().prec = 40
D = Decimal


def number(obj, key, positive=False):
    raw = obj[key]
    if isinstance(raw, bool):
        raise ValueError(key)
    val = D(str(raw))
    if not val.is_finite() or val < 0 or (positive and val == 0):
        raise ValueError(key)
    return val


def reject(reason):
    return {"approved": False, "reason": reason}


def evaluate(payload):
    try:
        return _evaluate(payload["context"], payload["intent"])
    except (KeyError, TypeError, ValueError, InvalidOperation, OverflowError):
        return reject("INVALID_OR_MISSING_INPUT")


def _evaluate(c, o):
    if c["mode"] not in ("PAPER", "LIVE_CANARY", "LIVE"):
        return reject("INVALID_MODE")
    if c["halt_latched"] is not False:
        return reject("HALT_LATCHED")
    for flag in ("health_ok", "reconciled", "fee_verified", "policy_verified"):
        if c[flag] is not True:
            return reject("PREFLIGHT_" + flag.upper())
    if c["mode"] != "PAPER":
        for flag in ("live_authorized", "strategy_qualified", "account_isolated",
                     "native_protection_verified"):
            if c[flag] is not True:
                return reject("LIVE_GATE_" + flag.upper())
    if o["market_type"] != "SPOT" or o["side"] != "BUY":
        return reject("SPOT_BUY_ENTRY_ONLY")
    if not isinstance(c["approved_symbols"], list) or o["symbol"] not in c["approved_symbols"]:
        return reject("SYMBOL_NOT_APPROVED")
    if number(c, "book_age_ms") > 2000 or number(c, "account_age_ms") > 5000:
        return reject("STALE_STATE")
    if number(o, "spread_bps") > 10:
        return reject("SPREAD_TOO_WIDE")
    slots = number(c, "slots_used")
    if slots != slots.to_integral_value() or slots >= 2:
        return reject("POSITION_LIMIT")
    spend = number(c, "operating_spend_usd")
    if spend >= 3:
        return reject("OPERATING_COST_CEILING")

    equity = number(c, "equity_usd", True)
    initial = number(c, "initial_capital_usd", True)
    if initial != 100:
        return reject("REFERENCE_MANDATE_IS_100_USD")
    # Economic equity includes externally paid operating costs. Period and peak
    # baselines use the same valuation. Extra cash flows are prohibited here.
    if c["no_external_cashflows"] is not True:
        return reject("CASHFLOW_REQUIRES_REVIEW")
    day = number(c, "day_start_equity_usd", True)
    week = number(c, "week_start_equity_usd", True)
    peak = number(c, "high_water_equity_usd", True)
    if peak < max(equity, initial, day, week):
        return reject("INCONSISTENT_HIGH_WATER")
    open_risk = number(c, "reserved_planned_risk_usd")
    exposure = number(c, "reserved_gross_exposure_usd")
    cash = number(c, "free_cash_usd")
    cash = min(cash, equity)  # reserve external operating costs economically
    floors = [day * D("0.98"), week * D("0.96"),
              peak * D("0.90"), initial - D("10")]
    if equity <= max(floors):
        return reject("LOSS_THRESHOLD")
    headroom = equity - max(floors) - open_risk
    canary = c["mode"] == "LIVE_CANARY"
    trade_fraction = D("0.0025") if canary else D("0.005")
    position_fraction = D("0.10") if canary else D("0.25")
    risk_budget = min(equity * trade_fraction,
                      equity * D("0.01") - open_risk, headroom)
    gross_headroom = equity * D("0.50") - exposure
    if risk_budget <= 0 or gross_headroom <= 0:
        return reject("NO_REMAINING_BUDGET")

    price = number(o, "entry_usd", True)
    stop = number(o, "stop_usd", True)
    if stop >= price:
        return reject("INVALID_LONG_STOP")
    cost = number(o, "roundtrip_cost_bps", True) / 10000
    entry_fee = number(o, "entry_fee_fraction")
    if cost >= 1 or entry_fee >= 1 or cost < entry_fee:
        return reject("INVALID_COST_MODEL")
    edge = number(o, "conservative_gross_edge_bps")
    if edge <= cost * 10000 + 5:
        return reject("INSUFFICIENT_EDGE_AFTER_COSTS")
    step = number(o, "quantity_step", True)
    minimum = number(o, "min_quantity", True)
    maximum = number(o, "max_quantity", True)
    min_notional = number(o, "min_notional_usd", True)
    if maximum < minimum:
        return reject("INVALID_SYMBOL_FILTERS")
    # min_quantity must cover entry AND eventual net exit minimums, including
    # any base-currency entry fee, as established by the production adapter.
    loss_per_unit = price - stop + price * cost
    raw = min(risk_budget / loss_per_unit,
              cash / (price * (1 + entry_fee)),
              equity * position_fraction / price,
              gross_headroom / price, maximum)
    qty = (raw / step).to_integral_value(rounding=ROUND_DOWN) * step
    notional = qty * price
    if qty <= 0 or qty < minimum or notional < min_notional:
        return reject("BELOW_EXCHANGE_MINIMUM_AFTER_ROUNDING")
    risk = qty * loss_per_unit
    return {"approved": True, "reason": "SIZING_ONLY_REQUIRES_ATOMIC_GATEWAY",
            "quantity": str(qty), "notional_usd": str(notional),
            "estimated_planned_loss_usd": str(risk),
            "cash_reservation_usd": str(notional * (1 + entry_fee)),
            "remaining_risk_budget_usd": str(risk_budget - risk),
            "mode": c["mode"]}


if __name__ == "__main__":
    try:
        result = evaluate(json.load(sys.stdin))
    except (ValueError, TypeError):
        result = reject("INVALID_JSON")
    print(json.dumps(result, allow_nan=False))
    sys.exit(0 if result["approved"] else 2)
