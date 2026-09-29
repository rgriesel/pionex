"""Paper trading engine: the single writer of the canonical ledger.

Loop (default every second):
  lease renewal -> policy check -> feed health -> marks/equity -> risk thresholds
  -> order processing (simulated fills on later quotes) -> independent exits
  -> new-bar signal evaluation -> risk-gated entries (dry-run preview) -> shadows
  -> snapshots / reconciliation / heartbeat.

Exits never depend on entry admission: halts, weak edge, spent budgets, or stale
entry data do not block stop, target, time, deadline, or risk-unwind exits.
"""
from __future__ import annotations

import json
import logging
import math
import uuid
from decimal import ROUND_CEILING, ROUND_DOWN, Decimal

from ..data.quality import window_ready
from ..execution.dryrun import DryRunError, build_order_request, find_official_cli, preview
from ..execution.paper import PaperBroker
from ..ledger.book import Book
from ..ledger.journal import Journal
from ..research.registry import Registry
from ..risk.service import ProposalError, RiskService, TrustedContext
from ..strategies import catalog
from ..util import iso_ms, parse_iso_ms, round_down, utc_day
from .state import current_state, transition

log = logging.getLogger("pionex_lab.engine")
ZERO = Decimal(0)
FIVE_MIN = 300_000
USDT_USD = Decimal(1)
FX_SOURCE = "ASSUMED 1 USDT = 1 USD (unverified; USDC_USDT cross monitored for depeg when available)"
IMPACT_BPS = Decimal(2)
ENTRY_LIMIT_CUSHION = Decimal("0.0005")
STALE_LATCH_MS = 5_000        # sustained staleness latches DATA_STALE; the gate enforces 2,000 ms per entry
COLLECTOR_DOWN_MS = 15_000
MAX_SKEW_MS = 1_000
DEPEG_TOLERANCE = Decimal("0.01")
EXTERNAL_BOOK_KINDS = {"OPERATING_COST"}


def _ceil_to(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_CEILING) * step


def _floor_to(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


class Engine:
    def __init__(self, cfg: dict, paths, mandate, clock, market, config_dir=None, holder: str | None = None,
                 dry_run_cli: str | None = "auto"):
        self.cfg, self.paths, self.mandate, self.clock = cfg, paths, mandate, clock
        self.market = market
        self.journal = Journal(paths.ledger)
        self.risk = RiskService(mandate, paths.risk, clock, journal=self.journal, config_dir=config_dir)
        self.registry = Registry(paths.research)
        self.fee = mandate.fee_per_side
        self.broker = PaperBroker(market, self.fee, clock)
        self.universe = list(cfg["research_universe"])
        self.depeg_symbol = cfg.get("depeg_monitor_symbol")
        self.ecfg = cfg["engine"]
        self.holder = holder or f"engine-{uuid.uuid4().hex[:8]}"
        self.cli = find_official_cli(None if dry_run_cli == "auto" else dry_run_cli) if dry_run_cli else None
        self.book = Book.replay(self.journal)
        self.token = None
        self.strategies = {}
        self.shadow_open = {}      # opportunity_id -> shadow position
        self.shadow_pending = {}   # opportunity_id -> pending shadow entry order
        self.last_bar = {}
        self.policy_ok = True
        self.reconciled = True
        self.health = {}
        self._due_at = {}
        self.start_hash = None

    # ================================================================ lifecycle
    def start(self) -> None:
        now = self.clock.now_ms()
        self.token = self.risk.acquire_lease(self.holder)
        started = self.journal.last("EXPERIMENT_STARTED")
        loaded = self.journal.last("MANDATE_LOADED")
        self.start_hash = started[2]["mandate_hash"] if started else None
        if loaded is None or loaded[2]["sha256"] != self.mandate.sha256:
            self.journal.append("MANDATE_LOADED", {"sha256": self.mandate.sha256, "path": str(self.mandate.path),
                                                   "live_enabled": self.mandate.live_enabled}, now)
        self.policy_ok = self.risk.verify_policy(self.start_hash)
        self._load_strategies(now)
        self._restore_shadows()
        for row in self.journal.conn.execute("SELECT payload FROM journal WHERE kind='DECISION' ORDER BY seq DESC "
                                             "LIMIT 200"):
            d = json.loads(row[0])
            t = parse_iso_ms(d["bar_time"])
            self.last_bar[d["symbol"]] = max(self.last_bar.get(d["symbol"], 0), t)
        self.journal.append("RECOVERY", {
            "holder": self.holder, "fencing_token": self.token, "journal_head": self.journal.head()[0],
            "open_positions": [p.episode_id for p in self.book.open_positions()],
            "open_orders": [o["client_order_id"] for o in self.book.open_orders()],
            "latches": sorted(self.risk.active_latches()), "dry_run_preview": self.cli or "built-in renderer",
            "note": "state rebuilt by journal replay; open orders resume from their last observed quote"}, now)
        state = current_state(self.journal)
        if state == "SETUP":
            transition(self.journal, "PAPER", "paper trading on public market data", {
                "live_enabled": self.mandate.live_enabled, "mode": self.mandate.mode},
                "engine", self.mandate.sha256, now)
        # Reservations whose entry order no longer exists cannot be pending anymore.
        live_coids = {o["reservation_id"] for o in self.book.open_orders() if o.get("reservation_id")}
        for r in self.risk.active_reservations():
            if r["id"] not in live_coids:
                self.risk.settle_reservation(r["id"], "RELEASED", "recovered without open order")

    def _load_strategies(self, now) -> None:
        latest = self.registry.latest_candidates()
        out = {}
        for name, cls in catalog.STRATEGIES.items():
            cand = latest.get(f"{name}/{cls.version}")
            params = cand["params"] if cand and cand.get("params") else cls.grid[0]
            out[name] = {"strategy": cls(params), "status": cand["status"] if cand else "UNREGISTERED",
                         "edge_bps": Decimal(str(cand["edge_lower_gross_bps"] or 0)) if cand else ZERO,
                         "params": params, "candidate_id": cand["id"] if cand else None}
        self.strategies = out
        self._due_at["strategies"] = now + 3_600_000

    def _due(self, key: str, every_ms: int, now: int) -> bool:
        if now >= self._due_at.get(key, 0):
            self._due_at[key] = now + every_ms
            return True
        return False

    def emit(self, kind: str, payload: dict, now: int) -> int:
        seq = self.journal.append(kind, payload, now)
        self.book.apply(kind, payload, now)
        self.book.last_seq = seq
        return seq

    # ================================================================ health
    def assess_health(self, now: int) -> dict:
        h = {"symbols": {}, "reasons": []}
        coll, _ = self.market.status("collector")
        if coll is None or now - coll["at"] > COLLECTOR_DOWN_MS:
            h["reasons"].append("COLLECTOR_HEARTBEAT_STALE")
        h["collector"] = coll
        skew = coll.get("skew_ms") if coll else None
        h["skew_ms"] = skew
        h["skew_ok"] = skew is None or abs(skew) <= MAX_SKEW_MS
        h["data_source"] = coll.get("base_url") if coll else None
        h["official_source"] = bool(coll and coll.get("official"))
        for s in self.universe:
            book = self.market.latest_book(s)
            age = (now - book["fetched_at"]) if book else None
            b5 = self.market.bars(s, "5M", limit=400, end_ms=now)
            b60 = self.market.bars(s, "60M", limit=120, end_ms=now)
            ok5, why5 = window_ready(b5, catalog.Strategy.warmup + 2, now)
            ok60, why60 = window_ready(b60, 60, now, grace_ms=180_000)
            rules, _ = self.market.symbol_rules(s)
            complete, missing = rules.complete() if rules else (False, ["symbol rules"])
            sym = {"book": book, "book_age_ms": age, "book_fresh": age is not None and age <= STALE_LATCH_MS,
                   "bars_ok": ok5 and ok60, "bars_reason": f"5M:{why5} 60M:{why60}", "b5": b5, "b60": b60,
                   "rules": rules, "tradable": bool(rules and rules.enabled and complete),
                   "rules_note": "OK" if complete else f"missing {missing}"}
            if book and book["ask"] > 0:
                sym["spread_bps"] = (book["ask"] - book["bid"]) / ((book["ask"] + book["bid"]) / 2) * 10000
            h["symbols"][s] = sym
            if not sym["book_fresh"]:
                h["reasons"].append(f"{s}:BOOK_STALE")
            if not sym["bars_ok"]:
                h["reasons"].append(f"{s}:{sym['bars_reason']}")
        h["depeg"] = None
        if self.depeg_symbol:
            d = self.market.latest_book(self.depeg_symbol)
            if d and now - d["fetched_at"] < 600_000:
                mid = (d["bid"] + d["ask"]) / 2
                h["depeg"] = {"symbol": self.depeg_symbol, "mid": str(mid), "ok": abs(mid - 1) <= DEPEG_TOLERANCE}
        h["feed_ok"] = not h["reasons"]
        return h

    # ================================================================ marks
    def marks(self) -> dict:
        out = {}
        for s, d in self.health.get("symbols", {}).items():
            if d["book"]:
                out[s] = d["book"]["bid"]
        return out

    def economic_equity(self, bids: dict) -> Decimal | None:
        try:
            liq = self.book.liquidation_value(bids, self.fee)
        except KeyError:
            return None
        return liq * USDT_USD - self.book.operating_costs

    # ================================================================ step
    def _sync_external(self) -> None:
        """Apply book-affecting events appended by admin commands (record-cost)."""
        for seq, at, kind, p in self.journal.events(since_seq=self.book.last_seq):
            if kind in EXTERNAL_BOOK_KINDS:
                self.book.apply(kind, p, at)
            self.book.last_seq = seq

    def step(self) -> None:
        now = self.clock.now_ms()
        self.risk.renew_lease()
        self._sync_external()
        if self._due("policy", 60_000, now):
            self.policy_ok = self.risk.verify_policy(self.start_hash)
        if now >= self._due_at.get("strategies", 0):
            self._load_strategies(now)
        self.health = self.assess_health(now)
        h = self.health
        self.risk.observe_health("DATA_STALE", h["feed_ok"], ";".join(h["reasons"])[:400], now)
        self.risk.observe_health("CLOCK_SKEW", h["skew_ok"], f"collector skew {h['skew_ms']} ms", now)
        if h["depeg"] is not None:
            self.risk.observe_health("QUOTE_DEPEG", h["depeg"]["ok"], f"{h['depeg']['symbol']} mid {h['depeg']['mid']}", now)
        state = current_state(self.journal)
        if self.book.started is None and state == "PAPER" and h["feed_ok"]:
            self._start_experiment(now)
        bids = self.marks()
        equity = self.economic_equity(bids) if self.book.started else None
        if equity is not None:
            new = self.risk.observe_equity(equity, now, self.book.operating_costs)
            if new:
                self.emit("INCIDENT", {"severity": "HIGH", "kind": "LOSS_THRESHOLD", "latches": new,
                                       "economic_equity_usd": str(equity)}, now)
        self._process_orders(now)
        self._manage_exits(now, state)
        self._process_shadows(now)
        if self.book.started and state == "PAPER":
            self._maybe_deadline(now)
            self._evaluate_new_bars(now)
        if self.book.started and self._due("snapshot", int(self.ecfg["snapshot_seconds"] * 1000), now):
            self._snapshot(now, bids)
        if self._due("reconcile", 60_000, now):
            self._reconcile(now)
        self.risk.observe_health("RECONCILE_PENDING", self.reconciled, "reconciliation or engine step failed", now)
        if current_state(self.journal) == "UNWINDING" and not self.book.positions and not self.book.open_orders():
            self._complete(now)
        self.journal.set_status("engine", {"at": now, "holder": self.holder, "state": current_state(self.journal),
                                           "feed_ok": h["feed_ok"], "reasons": h["reasons"][:10],
                                           "latches": sorted(self.risk.active_latches()),
                                           "dry_run_preview": self.cli or "built-in renderer"}, now)

    # ================================================================ experiment
    def _start_experiment(self, now: int) -> None:
        end = now + self.mandate.duration_days * 86_400_000
        self.emit("EXPERIMENT_STARTED", {
            "start_at": iso_ms(now), "end_at": iso_ms(end), "start_ms": now, "end_ms": end,
            "initial_capital_usd": str(self.mandate.initial_capital),
            "initial_capital_usdt": str(self.mandate.initial_capital / USDT_USD), "usdt_usd": str(USDT_USD),
            "fx_source": FX_SOURCE, "data_source": self.health.get("data_source"),
            "official_data_source": self.health.get("official_source"), "mandate_hash": self.mandate.sha256,
            "mode": "PAPER", "fills": "simulated on later observed quotes; orders are dry-run previews only"}, now)
        self.start_hash = self.mandate.sha256
        btc = self.health["symbols"].get("BTC_USDT", {}).get("book")
        if btc:
            qty = self.mandate.initial_capital / USDT_USD / btc["ask"] * (1 - self.fee)
            self.emit("BENCHMARK_STARTED", {"symbol": "BTC_USDT", "ask": str(btc["ask"]), "qty": str(qty),
                                            "note": "buy-and-hold with the same capital, entry fee, and exit fee at bid"},
                      now)

    def _maybe_deadline(self, now: int) -> None:
        if now >= int(self.book.started["end_ms"]):
            transition(self.journal, "UNWINDING", "experiment deadline reached", {"end_at": self.book.started["end_at"]},
                       "engine", self.mandate.sha256, now)

    def _complete(self, now: int) -> None:
        from ..reporting.report import build_report
        transition(self.journal, "COMPLETE", "all positions closed after deadline", {}, "engine",
                   self.mandate.sha256, now)
        report = build_report(self.paths, self.mandate, now, journal=self.journal, market=self.market,
                              risk=self.risk, registry=self.registry, universe=self.universe)
        from ..util import pretty_json
        out = self.paths.reports / f"final-{utc_day(now)}.json"
        out.write_text(pretty_json(report), encoding="utf-8")
        self.emit("EXPERIMENT_COMPLETE", {"report_file": out.name, "closed_trades": len(self.book.closed),
                                          "dust": {k: str(v) for k, v in self.book.dust.items()}}, now)

    # ================================================================ orders
    def _process_orders(self, now: int) -> None:
        for order in list(self.book.open_orders()):
            filled_before = order["filled"]
            remaining = Decimal(order["size"]) - filled_before
            state = {**order, "size": order["size"], "last_quote_at": order.get("last_quote_at", 0)}
            res = self.broker.try_fill(state, remaining)
            if res is None:
                continue
            coid = order["client_order_id"]
            if res["filled_size"] > 0:
                self.emit("FILL", {"client_order_id": coid, "symbol": order["symbol"], "side": order["side"],
                                   "price": str(res["avg_price"]), "size": str(res["filled_size"]),
                                   "fee": str(res["fee"]), "fee_asset": res["fee_asset"], "levels": res["fills"],
                                   "quote_fetched_at": res["quote_fetched_at"],
                                   "depth_fetched_at": res["depth_fetched_at"], "latency_ms": res["latency_ms"],
                                   "benchmark_bid": str(order.get("benchmark_bid") or res["quote_bid"]),
                                   "simulated": True}, now)
            order["last_quote_at"] = res["quote_fetched_at"] if "quote_fetched_at" in res else now
            if order["purpose"] == "ENTRY":
                self._finish_entry(order, res, now)
            elif res["status"] == "FILLED":
                self.emit("ORDER_FINAL", {"client_order_id": coid, "status": "FILLED",
                                          "filled_size": str(order["filled"]), "reason": res["reason"]}, now)
                self._maybe_close(order["episode_id"], now)

    def _finish_entry(self, order, res, now):
        coid = order["client_order_id"]
        status = res["status"] if res["status"] in ("FILLED", "PARTIAL_CANCELED", "CANCELED") else "CANCELED"
        self.emit("ORDER_FINAL", {"client_order_id": coid, "status": status, "filled_size": str(order["filled"]),
                                  "reason": res["reason"]}, now)
        rid = order.get("reservation_id")
        pos = self.book.positions.get(order["episode_id"])
        if pos is not None and pos.state == "OPEN":
            frac = pos.bought_qty / Decimal(order["size"])
            self.emit("POSITION_OPENED", {"episode_id": pos.episode_id, "symbol": pos.symbol,
                                          "strategy": pos.strategy, "version": pos.version,
                                          "qty": str(pos.qty), "entry_avg": str(pos.entry_avg),
                                          "stop": str(pos.stop), "target": str(pos.target) if pos.target else None,
                                          "max_hold_until": iso_ms(pos.max_hold_until),
                                          "planned_loss_usd": str(pos.planned_loss_usd * frac),
                                          "fill_fraction": str(frac)}, now)
            if rid:
                self.risk.settle_reservation(rid, "CONSUMED", coid)
        elif rid:
            self.risk.settle_reservation(rid, "RELEASED", f"{coid} {res['reason']}")

    def _maybe_close(self, episode_id: str, now: int) -> None:
        pos = self.book.positions.get(episode_id)
        if pos is None or pos.pending_sell > 0:
            return
        rules = self.health["symbols"].get(pos.symbol, {}).get("rules")
        min_sell = (rules.min_dump_size if rules and rules.min_dump_size else Decimal(0))
        step = rules.quantity_step if rules else Decimal("1e-8")
        total = pos.qty + self.book.dust.get(pos.symbol, ZERO)
        sellable = round_down(total, step) if total > 0 else ZERO
        if sellable > 0 and sellable >= min_sell:
            return  # still inventory to sell
        exit_avg = pos.exit_gross / pos.sold_qty if pos.sold_qty else None
        # The episode's own sub-step residual stays as inventory; mark it at the exit price.
        residual_value = pos.qty * exit_avg * (1 - self.fee) if exit_avg else ZERO
        net_usdt = pos.exit_gross - pos.exit_fee_quote - pos.entry_notional + residual_value
        fees_usdt = pos.entry_fee_quote_equiv + pos.exit_fee_quote
        exc = self._excursions(pos, now)
        self.emit("POSITION_CLOSED", {
            "episode_id": episode_id, "id": episode_id, "symbol": pos.symbol, "strategy": f"{pos.strategy} {pos.version}",
            "strategy_name": pos.strategy, "version": pos.version, "qualification": pos.qualification,
            "opened_at": iso_ms(pos.opened_at or now), "closed_at": iso_ms(now),
            "holding_minutes": round(((now - (pos.opened_at or now)) / 60000), 2),
            "qty_bought": str(pos.bought_qty), "qty_sold": str(pos.sold_qty), "residual_qty": str(pos.qty),
            "residual_marked_usdt": str(residual_value),
            "entry_avg": str(pos.entry_avg), "exit_avg": str(exit_avg) if exit_avg else None,
            "decision_price": str(pos.decision_price),
            "net_pnl_usdt": str(net_usdt), "net_pnl_usd": str(net_usdt * USDT_USD),
            "fees_usd": str(fees_usdt * USDT_USD), "slippage_usd": str(pos.slippage_quote * USDT_USD),
            "exit_reason": pos.exit_reason or "UNKNOWN", "mfe_bps": exc[0], "mae_bps": exc[1],
            "planned_loss_usd": str(pos.planned_loss_usd), "usdt_usd": str(USDT_USD)}, now)

    def _excursions(self, pos, now):
        if not pos.entry_avg or not pos.opened_at:
            return None, None
        rows = self.market.conn.execute("SELECT MAX(CAST(bid AS REAL)), MIN(CAST(bid AS REAL)) FROM book_ticks "
                                        "WHERE symbol=? AND fetched_at BETWEEN ? AND ?",
                                        (pos.symbol, pos.opened_at, now)).fetchone()
        if not rows or rows[0] is None:
            return None, None
        e = float(pos.entry_avg)
        return round((rows[0] / e - 1) * 1e4, 2), round((rows[1] / e - 1) * 1e4, 2)

    # ================================================================ exits
    def _manage_exits(self, now: int, state: str) -> None:
        unwind = self.risk.unwind_required()
        for pos in list(self.book.open_positions()):
            if pos.pending_sell > 0:
                continue
            sym = self.health["symbols"].get(pos.symbol, {})
            book = sym.get("book")
            rules = sym.get("rules")
            if book is None or rules is None:
                continue
            bid = book["bid"]
            reason = None
            if bid <= pos.stop:
                reason = "STOP"
            elif pos.target is not None and bid >= pos.target:
                reason = "TARGET"
            elif now >= pos.max_hold_until:
                reason = "TIME_EXIT"
            elif unwind:
                reason = "RISK_UNWIND:" + ",".join(unwind)
            elif state == "UNWINDING":
                reason = "EXPERIMENT_END"
            if reason is None:
                continue
            size = round_down(pos.qty + self.book.dust.get(pos.symbol, ZERO), rules.quantity_step)
            if size <= 0 or (rules.min_dump_size is not None and size < rules.min_dump_size):
                self.emit("INCIDENT", {"severity": "MEDIUM", "kind": "EXIT_BELOW_MINIMUM", "episode_id": pos.episode_id,
                                       "qty": str(pos.qty), "detail": "remaining inventory below market-sell minimum"},
                          now)
                pos.exit_reason = pos.exit_reason or reason
                self._maybe_close(pos.episode_id, now)
                continue
            coid = "pl-x-" + uuid.uuid4().hex[:20]
            try:
                req = preview(rules, self.cli, side="SELL", type_="MARKET", client_order_id=coid, size=size)
            except DryRunError as exc:
                if "OFFICIAL_CLI" not in str(exc):
                    self.emit("INCIDENT", {"severity": "HIGH", "kind": "EXIT_REQUEST_INVALID",
                                           "episode_id": pos.episode_id, "detail": str(exc)}, now)
                    continue
                # Tooling failure must not block a risk-reducing exit; use the built-in renderer.
                req = build_order_request(rules, "SELL", "MARKET", coid, size=size)
                req["preview_source"] = f"built-in renderer (official CLI failed: {exc})"
            self.emit("ORDER_INTENT", {"client_order_id": coid, "purpose": "EXIT", "episode_id": pos.episode_id,
                                       "symbol": pos.symbol, "side": "SELL", "type": "MARKET", "size": str(size),
                                       "price": None, "submitted_at": now, "exit_reason": reason,
                                       "benchmark_bid": str(bid), "dry_run_request": req,
                                       "fencing_token": self.token}, now)

    # ================================================================ entries
    def _evaluate_new_bars(self, now: int) -> None:
        h = self.health
        for s in self.universe:
            sym = h["symbols"][s]
            b5 = sym["b5"]
            if not len(b5):
                continue
            bar_t = b5.t[-1]
            if self.last_bar.get(s, 0) >= bar_t:
                continue
            self.last_bar[s] = bar_t
            self._evaluate_symbol(s, bar_t, now)

    def _evaluate_symbol(self, s: str, bar_t: int, now: int) -> None:
        h = self.health
        sym = h["symbols"][s]
        outcomes = {}
        if not sym["bars_ok"]:
            self.emit("DECISION", {"symbol": s, "bar_time": iso_ms(bar_t), "action": "NO_TRADE",
                                   "reason": "DATA_NOT_READY:" + sym["bars_reason"]}, now)
            return
        universe = {u: (h["symbols"][u]["b5"], h["symbols"][u]["b60"]) for u in self.universe
                    if h["symbols"][u]["bars_ok"]}
        signals = []
        for name, st in self.strategies.items():
            strat = st["strategy"]
            prep = strat.prepare(universe)
            idx = len(universe[s][0]) - 1
            sig = strat.check(prep, s, idx)
            outcomes[name] = "SIGNAL" if sig else "NO_SIGNAL"
            if sig:
                signals.append((st, sig))
        self.emit("DECISION", {"symbol": s, "bar_time": iso_ms(bar_t), "outcomes": outcomes,
                               "action": "EVALUATE" if signals else "NO_TRADE",
                               "reason": f"{len(signals)} signal(s)" if signals else "NO_SIGNAL"}, now)
        for st, sig in signals:
            self._handle_signal(st, sig, now)

    def _handle_signal(self, st: dict, sig, now: int) -> None:
        s = sig.symbol
        sym = self.health["symbols"][s]
        rules, book = sym["rules"], sym["book"]
        decision_id = "dec-" + uuid.uuid4().hex[:16]
        base = {"decision_id": decision_id, "strategy": sig.strategy, "version": sig.version, "symbol": s,
                "bar_time": iso_ms(sig.bar_time), "signal_reason": sig.reason, "features": sig.features,
                "reference_price": repr(sig.reference_price), "stop": repr(sig.stop),
                "target": repr(sig.target) if sig.target else None, "max_hold_bars": sig.max_hold_bars,
                "strategy_status": st["status"], "params": st["params"], "registry_edge_bps": str(st["edge_bps"])}
        self._open_shadow(sig, book, now)
        reason = None
        if st["status"] == "REJECTED":
            reason = "STRATEGY_REJECTED_BY_RESEARCH_GATES"
        elif not sym["tradable"]:
            reason = "SYMBOL_NOT_TRADABLE:" + sym["rules_note"]
        elif book is None:
            reason = "NO_BOOK"
        if reason:
            self.emit("RISK_DECISION", {**base, "approved": False, "reason": reason}, now)
            return
        step = rules.price_step
        stop = _floor_to(Decimal(repr(sig.stop)), step)          # never narrow the stop
        target = _floor_to(Decimal(repr(sig.target)), step) if sig.target else None
        limit = _ceil_to(book["ask"] * (1 + ENTRY_LIMIT_CUSHION), step)
        spread_bps = sym.get("spread_bps", Decimal(10000)).quantize(Decimal("0.0001"), rounding=ROUND_CEILING)
        roundtrip = 2 * self.fee * 10000 + spread_bps + 2 * IMPACT_BPS
        min_qty = max(rules.min_trade_size, _ceil_to(rules.min_dump_size / (1 - self.fee), rules.quantity_step))
        intent = {"entry_usd": str(limit * USDT_USD), "spread_bps": str(spread_bps),
                  "roundtrip_cost_bps": str(roundtrip), "entry_fee_fraction": str(self.fee),
                  "conservative_gross_edge_bps": str(st["edge_bps"]), "quantity_step": str(rules.quantity_step),
                  "min_quantity": str(min_qty), "max_quantity": str(rules.max_trade_size),
                  "min_notional_usd": str(rules.min_amount * USDT_USD)}
        opens = self.book.open_positions()
        bids = self.marks()
        equity = self.economic_equity(bids)
        ctx = TrustedContext(
            mode="PAPER", health_ok=bool(self.health["feed_ok"] and not (set(self.risk.active_latches()) &
                                                                           {"DATA_STALE", "CLOCK_SKEW", "QUOTE_DEPEG"})),
            reconciled=self.reconciled and "UNEXPLAINED_BALANCE" not in self.risk.active_latches(),
            fee_verified=self.fee == self.mandate.fee_per_side,  # paper: simulator charges exactly this fee
            policy_verified=self.policy_ok, approved_symbols=[u for u in self.universe
                                                              if self.health["symbols"][u]["tradable"]],
            book_age_ms=int(now - book["fetched_at"]), account_age_ms=max(0, int(self.clock.now_ms() - now)),
            open_positions=len(opens), equity_usd=equity if equity is not None else ZERO,
            free_cash_usd=self.book.free_cash() * USDT_USD,
            open_planned_risk_usd=sum((p.planned_loss_usd for p in opens), ZERO),
            open_exposure_usd=sum((p.qty * bids.get(p.symbol, p.entry_avg or ZERO) * USDT_USD for p in opens), ZERO),
            operating_spend_usd=self.book.operating_costs,
            strategy_qualified=st["status"] == "QUALIFIED_FOR_PAPER")
        proposal = {"decision_id": decision_id, "strategy": sig.strategy, "version": sig.version, "symbol": s,
                    "side": "BUY", "stop": str(stop), "target": str(target) if target else None,
                    "max_hold_minutes": sig.max_hold_bars * 5, "reason": sig.reason}
        try:
            res = self.risk.evaluate_entry(ctx, proposal, intent, self.token)
        except ProposalError as exc:
            self.emit("RISK_DECISION", {**base, "approved": False, "reason": f"PROPOSAL_INVALID:{exc}"}, now)
            return
        gate_ctx = res.pop("gate_context", {})
        record = {**base, "approved": bool(res.get("approved")), "reason": res.get("reason"), "intent": intent,
                  "gate_inputs": {k: gate_ctx.get(k) for k in ("equity_usd", "free_cash_usd", "slots_used",
                                                               "reserved_planned_risk_usd",
                                                               "reserved_gross_exposure_usd", "halt_latched",
                                                               "health_ok", "book_age_ms")}}
        if not res.get("approved"):
            self.emit("RISK_DECISION", record, now)
            return
        qty = Decimal(res["quantity"])
        coid = "pl-e-" + uuid.uuid4().hex[:20]
        try:
            req = preview(rules, self.cli, side="BUY", type_="LIMIT", client_order_id=coid, size=qty, price=limit,
                          ioc=True)
        except DryRunError as exc:
            self.risk.settle_reservation(res["reservation_id"], "RELEASED", f"dry-run rejected: {exc}")
            self.emit("RISK_DECISION", {**record, "approved": False, "reason": f"DRY_RUN_REJECTED:{exc}"}, now)
            return
        self.emit("RISK_DECISION", {**record, "sizing": res}, now)
        self.emit("ORDER_INTENT", {
            "client_order_id": coid, "purpose": "ENTRY", "episode_id": "ep-" + decision_id[4:], "symbol": s,
            "side": "BUY", "type": "LIMIT", "ioc": True, "size": str(qty), "price": str(limit), "submitted_at": now,
            "reservation_id": res["reservation_id"], "fencing_token": self.token, "dry_run_request": req,
            "entry": {"strategy": sig.strategy, "version": sig.version, "qualification": st["status"],
                      "stop": str(stop), "target": str(target) if target else None,
                      "max_hold_until": now + sig.max_hold_bars * FIVE_MIN, "decision_price": str(book["ask"]),
                      "planned_loss_usd": res["estimated_planned_loss_usd"], "reservation_id": res["reservation_id"],
                      "decision_id": decision_id}}, now)

    # ================================================================ shadows
    def _restore_shadows(self) -> None:
        opened = {}
        for _, _, kind, p in self.journal.events(("SHADOW_OPEN", "SHADOW_CLOSE")):
            if kind == "SHADOW_OPEN":
                opened[p["opportunity_id"]] = p
            else:
                opened.pop(p["opportunity_id"], None)
        self.shadow_open = opened

    def _open_shadow(self, sig, book, now) -> None:
        if book is None or sig.opportunity_id in self.shadow_open or sig.opportunity_id in self.shadow_pending:
            return
        notional = Decimal(str(self.ecfg["shadow_notional_usd"]))
        size = (notional / book["ask"]).quantize(Decimal("1e-8"), rounding=ROUND_DOWN)
        self.shadow_pending[sig.opportunity_id] = {
            "symbol": sig.symbol, "side": "BUY", "purpose": "ENTRY", "size": str(size),
            "price": str(book["ask"] * (1 + ENTRY_LIMIT_CUSHION)), "submitted_at": now, "sig": sig,
            "decision_ask": str(book["ask"])}

    def _process_shadows(self, now: int) -> None:
        for oid, o in list(self.shadow_pending.items()):
            res = self.broker.try_fill(o)
            if res is None:
                continue
            del self.shadow_pending[oid]
            if res["filled_size"] <= 0:
                continue
            sig = o["sig"]
            payload = {
                "opportunity_id": oid, "strategy": sig.strategy, "version": sig.version, "symbol": sig.symbol,
                "qty": str(res["filled_size"] - res["fee"]), "entry_price": str(res["avg_price"]),
                "cost_usdt": str(res["notional"]), "stop": repr(sig.stop), "target": repr(sig.target) if sig.target else None,
                "max_hold_until": now + sig.max_hold_bars * FIVE_MIN, "virtual": True}
            self.journal.append("SHADOW_OPEN", payload, now)
            self.shadow_open[oid] = payload
        for oid, p in list(self.shadow_open.items()):
            sym = self.health["symbols"].get(p["symbol"], {})
            book = sym.get("book")
            exit_order = p.get("exit_order")
            if exit_order is None:
                if book is None:
                    continue
                bid, stop = book["bid"], Decimal(p["stop"])
                target = Decimal(p["target"]) if p["target"] else None
                reason = ("STOP" if bid <= stop else "TARGET" if target is not None and bid >= target
                          else "TIME_EXIT" if now >= int(p["max_hold_until"]) else None)
                if reason:
                    p["exit_order"] = {"symbol": p["symbol"], "side": "SELL", "purpose": "EXIT", "size": p["qty"],
                                       "price": None, "submitted_at": now, "reason": reason, "filled": ZERO,
                                       "proceeds": ZERO, "fees": ZERO, "last_quote_at": 0}
                continue
            remaining = Decimal(exit_order["size"]) - exit_order["filled"]
            res = self.broker.try_fill(exit_order, remaining)
            if res is None:
                continue
            exit_order["last_quote_at"] = res["quote_fetched_at"]
            exit_order["filled"] += res["filled_size"]
            exit_order["proceeds"] += res["notional"]
            exit_order["fees"] += res["fee"]
            if exit_order["filled"] < Decimal(exit_order["size"]):
                continue
            cost = Decimal(p["cost_usdt"])
            net = exit_order["proceeds"] - exit_order["fees"] - cost
            self.journal.append("SHADOW_CLOSE", {
                "opportunity_id": oid, "strategy": p["strategy"], "version": p["version"], "symbol": p["symbol"],
                "exit_price": str(exit_order["proceeds"] / exit_order["filled"]), "net_pnl_usdt": str(net),
                "net_bps": str((net / cost * 10000).quantize(Decimal("0.01"))),
                "exit_reason": exit_order["reason"], "virtual": True}, now)
            del self.shadow_open[oid]

    # ================================================================ snapshots
    def _snapshot(self, now: int, bids: dict) -> None:
        missing = sorted({p.symbol for p in self.book.positions.values() if p.qty > 0 and p.symbol not in bids} |
                         {s for s, q in self.book.dust.items() if q > 0 and s not in bids})
        if missing:
            self.emit("INCIDENT", {"severity": "LOW", "kind": "SNAPSHOT_SKIPPED", "missing_marks": missing}, now)
            return
        liq = self.book.liquidation_value(bids, self.fee)
        bench = None
        b = self.journal.last("BENCHMARK_STARTED")
        if b and "BTC_USDT" in bids:
            bench = Decimal(b[2]["qty"]) * bids["BTC_USDT"] * (1 - self.fee) * USDT_USD
        self.emit("SNAPSHOT", {
            "at": iso_ms(now), "equity_usd": str(liq * USDT_USD), "cash_usdt": str(self.book.cash),
            "economic_value_usd": str(liq * USDT_USD - self.book.operating_costs),
            "cumulative_operating_cost_usd": str(self.book.operating_costs), "net_cashflow_usd": "0",
            "btc_benchmark_usd": str(bench) if bench is not None else None, "usdt_usd": str(USDT_USD),
            "fx_source": FX_SOURCE, "marks": {k: str(v) for k, v in bids.items()},
            "positions": [{"episode_id": p.episode_id, "symbol": p.symbol, "qty": str(p.qty)}
                          for p in self.book.positions.values() if p.qty > 0]}, now)

    def _reconcile(self, now: int) -> None:
        fresh = Book.replay(self.journal)
        ok = fresh.fingerprint() == self.book.fingerprint()
        chain_ok = True
        if self._due("verify_chain", 600_000, now):
            chain_ok, bad, _ = self.journal.verify()
            if not chain_ok:
                self.risk.set_latch("JOURNAL_CORRUPT", f"hash chain broken at seq {bad}", now)
        if not ok:
            self.risk.set_latch("UNEXPLAINED_BALANCE", "in-memory book differs from journal replay", now)
            self.emit("INCIDENT", {"severity": "CRITICAL", "kind": "RECONCILIATION_MISMATCH",
                                   "memory": self.book.fingerprint(), "journal": fresh.fingerprint()}, now)
        self.reconciled = ok and chain_ok
        self.journal.set_status("reconciliation", {"at": now, "ok": self.reconciled, "journal_rows": fresh.last_seq},
                                now)

    def run(self, stop_event) -> None:
        self.start()
        every = float(self.ecfg["loop_seconds"])
        while not stop_event.is_set():
            try:
                self.step()
            except Exception as exc:  # noqa: BLE001 - record, freeze entries, keep monitoring
                log.exception("engine step failed")
                now = self.clock.now_ms()
                try:
                    self.journal.append("INCIDENT", {"severity": "HIGH", "kind": "ENGINE_STEP_ERROR",
                                                     "detail": f"{type(exc).__name__}: {exc}"[:500]}, now)
                    self.risk.observe_health("RECONCILE_PENDING", False, "engine step error", now)
                except Exception:  # noqa: BLE001
                    log.exception("could not record incident")
                if isinstance(exc, (PermissionError,)) or "lease lost" in str(exc):
                    raise
            stop_event.wait(every)


def isfinite_dec(x) -> bool:
    return isinstance(x, Decimal) and x.is_finite() and not math.isnan(float(x))
