"""Read-only owner-bot exit audit for CLO-64; protocol in owner_method.__doc__.

No inferred net grid counterfactual: missing fills/inventory or causal targets
fail closed. Latest settings and cancellation codes are descriptive evidence.
Run: py -m pionex_lab.research.owner_exit_study --root <repo> --output <json>
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from . import luck, owner_method


def number(value):
    import math
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def connect(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def audit_account(path):
    """All ids remain in denominators, including records without raw details."""
    with connect(path) as db:
        observations = db.execute("SELECT bu_order_id, at, raw FROM bots "
                                  "WHERE bu_order_id IS NOT NULL ORDER BY at").fetchall()
    groups = {}
    for oid, at, raw in observations:
        groups.setdefault(oid, []).append((int(at), raw))
    rows = []
    for oid, snapshots in groups.items():
        parsed = []
        invalid = 0
        for at, raw in snapshots:
            if not raw:
                continue
            try:
                summary = json.loads(raw).get("summary", {})
                if isinstance(summary, dict) and summary:
                    parsed.append((at, summary))
            except (ValueError, TypeError, AttributeError):
                invalid += 1
        if not parsed:
            rows.append({"id": oid, "classification": "missing_raw", "invalid_snapshots": invalid})
            continue
        at, summary = parsed[-1]
        bot = summary.get("buOrderData") or {}
        start, end = number(summary.get("createTime")), number(summary.get("closeTime"))
        direction = bot.get("trend")
        target = number(bot.get("profitStop")) if bot.get("profitStopType") == "price" else None
        if target is not None and target <= 0:
            target = None
        price = number(bot.get("closedPrice"))
        reason = bot.get("reasonBy")
        running = summary.get("status") in ("open", "running") or not end
        known_at = next((t for t, s in parsed
                         if target is not None and number((s.get("buOrderData") or {}).get("profitStop")) == target
                         and (s.get("buOrderData") or {}).get("profitStopType") == "price"), None)
        target_before_entry = bool(start is not None and known_at is not None and known_at <= start)
        target_before_exit = bool(end is not None and known_at is not None and known_at < end)
        if running:
            classification = "running_censored"
        elif reason == "force_liquidation" or bot.get("liquidationTriggered") is True:
            classification = "liquidation"
        elif reason == "profit_stop":
            classification = "recorded_profit_stop"
        elif reason == "user_cancel":
            if target is not None and price is not None and direction in ("long", "short"):
                below = price < target if direction == "long" else price > target
                classification = "manual_before_latest_target" if below else "manual_at_or_beyond_latest_target"
            else:
                classification = "manual_target_unknown"
        else:
            classification = "other_or_unknown"
        inv = number(bot.get("initUsdtInvestment"))
        margin = number(bot.get("marginBalance"))
        # This matches the prior bot miner; transfers/withdrawals/fees are NOT
        # reconciled, so this is never labelled banked net profit.
        equity_difference = margin - inv if margin is not None and inv is not None else None
        rows.append({"id": oid, "classification": classification,
                     "pair": f"{summary.get('base', '')}_{summary.get('quote', '')}",
                     "type": summary.get("buOrderType"), "direction": direction,
                     "start": start, "end": end, "latest_snapshot": at,
                     "latest_target": target, "target_first_observed": known_at,
                     "target_observed_before_entry": target_before_entry,
                     "target_observed_before_exit": target_before_exit,
                     "target_is_immutable_entry_target": False,
                     "recorded_close_price": price, "recorded_reason": reason,
                     "reported_margin_minus_initial": equity_difference,
                     "reported_total_fee": number(bot.get("totalFee")),
                     "reported_funding_fee": number(bot.get("totalFundingFee")),
                     "actual_exit_intent": "unavailable",
                     "actual_net_benefit_vs_hold": None,
                     "fee_reconciled": False})
    return {"expected_bots": 65, "observed_distinct_bots": len(groups),
            "raw_detail_bots": sum(r["classification"] != "missing_raw" for r in rows),
            "missing_from_expected": max(0, 65 - len(groups)),
            "classification_counts": dict(Counter(r["classification"] for r in rows)),
            "causal_entry_target_bots": sum(r.get("target_observed_before_entry", False) for r in rows),
            "pre_exit_target_bots": sum(r.get("target_observed_before_exit", False) for r in rows),
            "rows": rows}


def market_coverage(root):
    result = []
    for name in ("market.db", "proxy_market.db"):
        path = root / "var" / name
        if not path.exists():
            continue
        with connect(path) as db:
            for sym, count, first, last in db.execute(
                "SELECT symbol,COUNT(*),MIN(open_time),MAX(open_time) FROM klines "
                "WHERE interval='60M' AND complete=1 AND symbol IN ('BTC_USDT','BTC_USDT_PERP') "
                "GROUP BY symbol"):
                result.append({"database": name, "symbol": sym, "complete_bars": count,
                               "first_open": first, "last_open": last,
                               "source": "Pionex" if name == "market.db" else "Binance PROXY"})
    return result


def study(root):
    root = Path(root)
    account = audit_account(root / "var" / "account.db")
    n = luck.trial_count(root / "var" / "trials.db")
    # Do not call luck_report with another strategy id: it would test the CTA
    # instead of these exits. Unsupported series are explicit missing tests.
    missing = {
        "T1_history": "No causal daily owner-method return series; need >=750 days.",
        "T2_deflated_sharpe": "No reconciled OOS daily return series/parameter variance.",
        "T3_pbo_cscv": "No aligned return panel for five frozen configurations.",
        "T4_timing_null": "No causal exposure/return panel or matched random-entry returns.",
        "T5_sensitivity": "No matched replay for stall4/stall8/fade0.4/fade0.6.",
        "T6_block_bootstrap": "No reconciled paired net exit-benefit series.",
        "T7_regimes": "No validated causal owner-method returns in all four regimes.",
        "T8_cost_stress": "Missing inventory/fills/fee reconciliation and measured spread.",
        "T9_monte_carlo_100usd": "No capital-constrained daily grid returns at each leverage.",
    }
    tests = {key: {"pass": False, "status": "NOT_EVALUABLE", "reason": why}
             for key, why in missing.items()}
    definition = owner_method.__doc__.encode()
    return {"issue": "CLO-64", "at": datetime.now(timezone.utc).isoformat(),
            "verdict": "INCOMPLETE_INPUTS", "luck_eligible": False, "live_eligible": False,
            "definition_sha256": hashlib.sha256(definition).hexdigest(),
            "definition_source": "pionex_lab/research/owner_method.py",
            "account_audit": account, "market_coverage": market_coverage(root),
            "registry_count_before": n, "thresholds": luck.thresholds(n + 5),
            "trial_budget": 5, "luck_suite_coverage": tests,
            "leverage_results": {str(lev): {"net_expectancy": None, "probability_of_ruin": None,
                                           "status": "NOT_EVALUABLE"} for lev in (3, 5, 10, 20, 40)},
            "positive_expectancy_leverage": None,
            "measured_early_exit_benefit": None,
            "dependencies": ["CLO-65: point-in-time S/R/OB/heatmap/news feature pipeline",
                             "Complete 65-bot reader dataset with immutable target versions, fills, inventory, funding and fees",
                             "Point-in-time analyst calls and forward Pionex exit/hold shadow ledger"],
            "limitations": ["Manual cancellation is observed; discretionary intent is not recorded.",
                            "A latest configured profitStop is not an immutable entry target.",
                            "Grid range edges are not profit targets.",
                            "Margin minus initial investment is not reconciled net trading P&L.",
                            "Missing tests fail eligibility; no estimated benefit or ruin substituted."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; preserve the original run")
    report = study(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    luck.record_trial(args.root / "var" / "trials.db", "owner_market_read_exit",
                      report["definition_sha256"], "owner_method_v1",
                      {"configurations": ["base", "stall4", "stall8", "fade0.4", "fade0.6"]},
                      result="INCOMPLETE_INPUTS; no performance evaluated", weight=5)
    print(json.dumps({"verdict": report["verdict"], "counts": report["account_audit"]["classification_counts"],
                      "observed": report["account_audit"]["observed_distinct_bots"],
                      "causal_targets": report["account_audit"]["causal_entry_target_bots"],
                      "output": str(args.output)}))


if __name__ == "__main__":
    main()
