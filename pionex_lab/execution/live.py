"""Live trading gate. There is intentionally no live order path in this codebase.

`live_preflight()` evaluates every operational gate from SKILL.md / operations.md
and reports exactly what is missing. `LiveGateway` refuses to construct unless all
gates pass — and even then it raises, because the signer, secret store, separate
service identities, and verified exchange-side protection have not been built.
Installing the skill or passing research gates does not authorize live orders.
"""
from __future__ import annotations

from decimal import Decimal


class LiveTradingDisabled(RuntimeError):
    pass


def _g(name, ok, detail, status=None):
    return {"gate": name, "status": status or ("PASS" if ok else "FAIL"), "detail": detail}


def live_preflight(mandate, registry=None, book=None, risk=None, paper_trades_qualified: int = 0,
                   paper_hours_qualified: float = 0.0) -> list:
    auth = mandate.raw["authority"]
    ex = mandate.raw["execution"]
    q = mandate.qualification
    gates = [
        _g("mandate.live_enabled", auth["live_enabled"] is True, f"live_enabled={auth['live_enabled']}"),
        _g("authorization_record", bool(auth.get("authorization_record")),
           "user authorization covering exact account, capital, instruments, and mandate hash"
           if not auth.get("authorization_record") else "present"),
        _g("account_scope_isolated", bool(auth.get("account_scope")),
           "dedicated account or segregated balance holding only experiment funds (key must not reach unrelated funds)"),
        _g("approved_policy_hash", auth.get("approved_policy_hash") == mandate.sha256,
           f"approved={auth.get('approved_policy_hash')} current={mandate.sha256[:16]}..."),
        _g("allowed_symbols", bool(ex.get("allowed_symbols")), f"live allowlist={ex.get('allowed_symbols')}"),
        _g("verified_fee_source", ex.get("verified_fee_source") is not None,
           "actual pair/account fees not verified (research assumes 0.05% per side)"),
        _g("exchange_side_protection", ex.get("protection_capability_report") is not None,
           "documented spot LIMIT/MARKET orders do not establish native stops; none demonstrated"),
    ]
    qualified = []
    if registry is not None:
        qualified = [k for k, c in registry.latest_candidates().items() if c["status"] == "QUALIFIED_FOR_PAPER"]
    gates.append(_g("strategy_qualified", bool(qualified),
                    f"qualified candidates: {qualified or 'none'} (OOS >= {q['min_oos_trades']} trades / "
                    f"{q['min_oos_days']} days, PF >= {q['min_net_profit_factor']}, positive CI bound, stress)"))
    gates.append(_g("paper_evidence", paper_trades_qualified >= int(q["min_paper_trades"])
                    and paper_hours_qualified >= float(q["min_paper_hours"]),
                    f"{paper_trades_qualified}/{q['min_paper_trades']} closed paper trades, "
                    f"{paper_hours_qualified:.1f}/{q['min_paper_hours']} hours with the frozen qualified candidate"))
    if risk is not None:
        review = [n for n, r in risk.active_latches().items() if r["kind"] == "REVIEW"]
        gates.append(_g("no_review_latches", not review, f"active review latches: {review or 'none'}"))
    for name, detail in (
            ("signer_and_secret_store", "server-side secret store + isolated signer service"),
            ("separate_service_identities", "research/strategy/risk/signer/ledger under different OS identities"),
            ("exchange_capability_report", "observed key permissions (read/trade only, IP-restricted, no withdrawal), "
                                           "symbol filters, order-ID semantics, rate limits"),
            ("reconciliation_against_exchange", "fills/balances reconciled against the exchange account"),
            ("canary_limits_path", "LIVE_CANARY with 0.25% risk / 10% notional before standard limits")):
        gates.append(_g(name, False, detail + " — not implemented in this build", "NOT_IMPLEMENTED"))
    return gates


class LiveGateway:
    def __init__(self, mandate, **kwargs):
        gates = live_preflight(mandate, **kwargs)
        failing = [g for g in gates if g["status"] != "PASS"]
        raise LiveTradingDisabled(
            "live trading is disabled; failing gates: " + ", ".join(g["gate"] for g in failing)
            if failing else "all declared gates pass but no live execution path exists in this build")


ZERO = Decimal(0)
