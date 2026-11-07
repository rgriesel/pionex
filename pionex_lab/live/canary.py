"""CLO-243 canary qualification, research/decision code only. No transport or order path.

Registration is historical evidence, not current market/account state. Runtime observations
must be fetched by the executor from Pionex at each decision, never loaded from a report.
"""
from __future__ import annotations

import math
import sqlite3
from pathlib import Path

from .gate import Check, GateResult, _ro, params_hash

POLICY = {
    "version": "CLO-243-v1", "initial_margin": 5.0, "scaled_margin": 10.0,
    "scale_closed_bots": 5, "scale_net_usdt": 1.0, "strategy_loss_usdt": 1.0,
    "capital_usdt": 100.0, "daily_loss_usdt": 2.0, "absolute_loss_usdt": 10.0,
}


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("finite numeric value required")
    return value


def review_hash(candidate):
    """Registry params_sha256 pins parameters, evidence AND pre-registered policy."""
    return params_hash({"candidate": candidate, "policy": POLICY})


def qualify(sid, candidate, verdicts, mandate, now_ms, observer=None):
    """PRE-REGISTERED 2026-11-07 11:44 SAST, before any test of this function.

    Fixed loose screen: owner-method net expectancy > 0, at least one observation,
    fees/slippage/spread/funding/exit/inventory included, causal closed-bar decisions
    and next-open fills, all certified by latest exact HOLDS pinning full candidate
    and policy. PROXY must be labelled. No paper duration, trade-count or luck gate
    is substituted for this distinct real-money experiment tier.

    Initial total margin $5; scale to $10 only after >=5 closed live bots and >=$1
    realized NET profit, no losing closed bot, and total marked strategy P&L >=$0.
    Retire permanently for this id on ANY losing closed bot or strategy marked P&L
    <=-$1. History is full lifetime, so restarting cannot reset retirement or scale.
    No larger tier or automatic promotion to forward tier. New rule needs new id/review.

    Total committed margin including extra margin and the proposed bot <=min($100,
    mandate capital). Daily drawdown >=min($2, mandate daily limit), total net loss
    >=min($10, mandate absolute limit), or active halt rejects. Fresh, complete Pionex
    observations only (account <=5min, quote <=5sec, rules <=1day, never future).
    Mandatory TP/SL and leverage <= independently certified cap AND mandate cap.
    Adapter must enforce versioned policy atomically at create, poll, and restart.
    PASS means all checks true; missing/malformed inputs fail closed. Unit fixtures
    are synthetic; this is not a strategy backtest or proof of profit.
    """
    r = GateResult(sid, "canary_grid", tier="LIVE_CANARY")

    def check(name, ok, value, need):
        r.checks.append(Check(name, bool(ok), value, need))

    try:
        p, e = candidate["params"], candidate["evidence"]
        r.params = dict(p)
        costs = ("fees", "slippage", "spread", "funding", "exit", "inventory")
        check("owner_method_after_costs", e["method"] == "owner-method" and
              number(e["observations"]) >= 1 and int(e["observations"]) == e["observations"] and
              number(e["net_expectancy"]) > 0 and all(e["includes"].get(k) is True for k in costs),
              e["net_expectancy"], "positive total-equity expectancy after all costs")
        check("causal", e["closed_bar_decisions"] is True and e["next_open_fills"] is True,
              e["closed_bar_decisions"], "closed bars, next-open fills, reviewed no look-ahead")
        check("data_label", e["venue"] in ("PIONEX", "PROXY"), e["venue"], "PIONEX or labelled PROXY")
        v, pin = verdicts.get(sid, (None, ""))
        check("redteam_bookkeeping_holds", v == "HOLDS" and pin == review_hash(candidate), v,
              "latest HOLDS pins candidate evidence + params + policy")
        bottom, top = number(p["bottom"]), number(p["top"])
        stop, take = number(p["loss_stop"]), number(p["profit_stop"])
        trend = p["trend"]
        bracket = (0 < stop < bottom < top < take) if trend == "long" else (
            0 < take < bottom < top < stop if trend == "short" else False)
        check("bracket", bracket, trend, "long/short futures grid with both TP/SL outside range")
        check("futures_grid", isinstance(p["symbol"], str) and p["symbol"].endswith(".PERP_USDT") and
              2 <= number(p["rows"]) <= 200 and int(p["rows"]) == p["rows"] and
              p.get("type", "geometric") == "geometric", p["symbol"], "supported geometric futures grid")
        # Certification must cover this exact strategy, not an unrelated leverage report.
        lev, certified = number(p["leverage"]), number(e["certified_max_leverage"])
        check("leverage", 1 <= lev <= certified <= number(mandate.get("risk", "max_leverage")), lev,
              "<= independently reviewed strategy-specific leverage cap <= mandate cap")
        check("mandate_futures", mandate.get("risk", "futures_allowed") is True, None, "futures allowed")
        # Reject unsupported callers instead of allowing legacy planners to treat this as a grid.
        if observer is None:
            check("executor_adapter", False, None, "CLO-238 Pionex observer + atomic CLO-243-v1 enforcement")
            return r
        obs = observer(sid, dict(p), dict(POLICY))
        check("executor_adapter", obs["enforced_policy"] == POLICY["version"], obs["enforced_policy"], POLICY["version"])
        check("pionex_source", obs["source"] == "PIONEX" and obs["complete"] is True, obs["source"],
              "fresh full lifetime live bots, account, funding, fees and marked inventory")
        for key, age in (("account_ts", 300_000), ("quote_ts", 5_000), ("rules_ts", 86_400_000)):
            check(key, 0 <= now_ms - number(obs[key]) <= age, obs[key], f"age in [0,{age}] ms")
        bots = obs["closed_bots"]
        ids = [b["id"] for b in bots]
        valid_ids = all(isinstance(x, str) and x for x in ids) and len(set(ids)) == len(ids)
        pnl = [number(b["net_pnl"]) for b in bots]
        realized, total = sum(pnl), number(obs["strategy_total_pnl"])
        retired = any(x < 0 for x in pnl) or total <= -POLICY["strategy_loss_usdt"]
        check("live_retirement", valid_ids and not retired, total, "no losing closed bot; marked strategy P&L > -$1")
        margin = POLICY["scaled_margin"] if (len(bots) >= POLICY["scale_closed_bots"] and
            realized >= POLICY["scale_net_usdt"] and total >= 0 and not retired) else POLICY["initial_margin"]
        extra = number(p.get("extra_margin", 0))
        check("margin_split", 0 <= extra < margin, extra, "extra margin included inside $5/$10 allocation")
        r.params.update(invest=margin - extra, extra_margin=extra)
        committed = number(obs["committed_margin"])
        capital = min(POLICY["capital_usdt"], number(mandate.get("experiment", "initial_capital")))
        check("margin_cap", 0 <= committed and committed + margin <= capital, committed + margin,
              f"total margin <= {capital}")
        day_drop = number(obs["day_peak_pnl"]) - number(obs["firm_total_pnl"])
        day_limit = min(POLICY["daily_loss_usdt"], capital * number(mandate.get("risk", "daily_loss_fraction")))
        abs_limit = min(POLICY["absolute_loss_usdt"], number(mandate.get("risk", "absolute_experiment_loss_usd")))
        check("loss_halts", obs["halted"] is False and day_limit > 0 and abs_limit > 0 and
              0 <= day_drop < day_limit and obs["firm_total_pnl"] > -abs_limit, obs["firm_total_pnl"],
              "no active halt; daily and absolute loss below stricter canary/mandate limit")
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError, OSError) as exc:
        check("canary_inputs", False, type(exc).__name__, "complete valid evidence and fresh Pionex inputs")
    except Exception as exc:
        check("observer_error", False, type(exc).__name__, "observer succeeded; fail closed")
    return r


def evaluate_canaries(var, verdicts, mandate, now_ms, observer=None):
    """Read-only canary_registry.db candidates(id TEXT PRIMARY KEY, candidate TEXT JSON).

    Empty/missing registry adds no strategies. A corrupt registry emits a failed sentinel,
    never eligibility. Registration is performed by research after its single test and
    independent bookkeeping/no-look-ahead review; this reader never registers or trades.
    """
    import json

    db = None
    try:
        db = _ro(Path(var) / "canary_registry.db")
        if db is None:
            return []
        out = []
        for sid, raw in db.execute("SELECT id, candidate FROM candidates ORDER BY id"):
            try:
                candidate = json.loads(raw)
            except (ValueError, TypeError):
                candidate = {}
            out.append(qualify(sid, candidate, verdicts, mandate, now_ms, observer))
        return out
    except (OSError, sqlite3.Error):
        return [GateResult("__canary_registry_error__", "canary_grid",
                           [Check("canary_registry", False, None, "readable valid registry")], tier="LIVE_CANARY")]
    finally:
        if db is not None:
            db.close()
