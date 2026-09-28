"""Paper account state derived exclusively from journal events.

The engine applies each event to the in-memory book as it journals it. Recovery
and reconciliation rebuild a fresh book by replaying the journal; the two must
match exactly (Decimal), otherwise UNEXPLAINED_BALANCE is latched.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

ZERO = Decimal(0)


@dataclass
class Position:
    episode_id: str
    symbol: str
    strategy: str
    version: str
    qualification: str
    stop: Decimal
    target: Decimal | None
    max_hold_until: int
    decision_price: Decimal        # executable ask at decision time (arrival benchmark)
    planned_loss_usd: Decimal
    reservation_id: str
    decision_id: str
    state: str = "PENDING"         # PENDING -> OPEN -> CLOSED
    qty: Decimal = ZERO            # base owned, net of base-denominated fees
    bought_qty: Decimal = ZERO
    entry_notional: Decimal = ZERO  # quote spent
    entry_fee_base: Decimal = ZERO
    entry_fee_quote_equiv: Decimal = ZERO
    sold_qty: Decimal = ZERO
    exit_gross: Decimal = ZERO
    exit_fee_quote: Decimal = ZERO
    slippage_quote: Decimal = ZERO
    opened_at: int | None = None
    pending_sell: Decimal = ZERO
    exit_reason: str | None = None

    @property
    def entry_avg(self) -> Decimal | None:
        return self.entry_notional / self.bought_qty if self.bought_qty else None


@dataclass
class Book:
    cash: Decimal = ZERO
    started: dict | None = None
    positions: dict = field(default_factory=dict)
    orders: dict = field(default_factory=dict)
    closed: list = field(default_factory=list)
    dust: dict = field(default_factory=dict)
    operating_costs: Decimal = ZERO
    dust_swept_usdt: Decimal = ZERO
    last_seq: int = 0

    # ------------------------------------------------------------------ replay
    @classmethod
    def replay(cls, journal) -> "Book":
        book = cls()
        for seq, at, kind, payload in journal.events():
            book.apply(kind, payload, at)
            book.last_seq = seq
        return book

    def apply(self, kind: str, p: dict, at: int) -> None:
        handler = getattr(self, "_on_" + kind.lower(), None)
        if handler:
            handler(p, at)

    def _on_experiment_started(self, p, at):
        if self.started is not None:
            raise ValueError("experiment already started")
        self.started = dict(p)
        self.cash = Decimal(p["initial_capital_usdt"])

    def _on_operating_cost(self, p, at):
        self.operating_costs += Decimal(p["usd"])

    def _on_order_intent(self, p, at):
        coid = p["client_order_id"]
        if coid in self.orders:
            raise ValueError(f"duplicate client order id {coid}")
        self.orders[coid] = {**p, "status": "OPEN", "filled": ZERO, "submitted_at": p["submitted_at"]}
        if p["purpose"] == "ENTRY":
            m = p["entry"]
            self.positions[p["episode_id"]] = Position(
                episode_id=p["episode_id"], symbol=p["symbol"], strategy=m["strategy"], version=m["version"],
                qualification=m["qualification"], stop=Decimal(m["stop"]),
                target=Decimal(m["target"]) if m.get("target") is not None else None,
                max_hold_until=int(m["max_hold_until"]), decision_price=Decimal(m["decision_price"]),
                planned_loss_usd=Decimal(m["planned_loss_usd"]), reservation_id=m["reservation_id"],
                decision_id=m["decision_id"])
        else:
            pos = self.positions[p["episode_id"]]
            pos.pending_sell += Decimal(p["size"])
            pos.exit_reason = pos.exit_reason or p.get("exit_reason")

    def _on_fill(self, p, at):
        order = self.orders[p["client_order_id"]]
        pos = self.positions[order["episode_id"]]
        size, price, fee = Decimal(p["size"]), Decimal(p["price"]), Decimal(p["fee"])
        notional = size * price
        order["filled"] += size
        order["last_quote_at"] = p["quote_fetched_at"]
        if order["side"] == "BUY":
            if p["fee_asset"] != "BASE":
                raise ValueError("paper buys charge base-asset fees")
            self.cash -= notional
            pos.qty += size - fee
            pos.bought_qty += size
            pos.entry_notional += notional
            pos.entry_fee_base += fee
            pos.entry_fee_quote_equiv += fee * price
            pos.slippage_quote += (price - pos.decision_price) * size
        else:
            dust = self.dust.get(pos.symbol, ZERO)
            if size > pos.qty + dust:
                raise ValueError("oversell prevented: fill exceeds owned quantity")
            own = min(size, pos.qty)
            swept = size - own                      # earlier residual inventory sold alongside
            self.cash += notional - fee
            pos.qty -= own
            if swept:
                self.dust[pos.symbol] = dust - swept
                self.dust_swept_usdt += swept * price - fee * swept / size
            pos.sold_qty += own
            pos.exit_gross += own * price
            pos.exit_fee_quote += fee * own / size
            pos.pending_sell -= size
            benchmark = Decimal(p["benchmark_bid"])
            pos.slippage_quote += (benchmark - price) * own

    def _on_order_final(self, p, at):
        order = self.orders[p["client_order_id"]]
        order["status"] = p["status"]
        pos = self.positions.get(order["episode_id"])
        if order["purpose"] == "ENTRY" and pos is not None:
            if order["filled"] > 0:
                pos.state = "OPEN"
                pos.opened_at = at
            else:
                del self.positions[order["episode_id"]]
        elif pos is not None:
            pos.pending_sell -= Decimal(order["size"]) - order["filled"]
            if pos.pending_sell < 0:
                pos.pending_sell = ZERO

    def _on_position_opened(self, p, at):
        pos = self.positions[p["episode_id"]]
        pos.planned_loss_usd = Decimal(p["planned_loss_usd"])

    def _on_position_closed(self, p, at):
        pos = self.positions.pop(p["episode_id"])
        if pos.qty > 0:
            self.dust[pos.symbol] = self.dust.get(pos.symbol, ZERO) + pos.qty
        self.closed.append(dict(p))

    # ------------------------------------------------------------------ views
    def open_positions(self) -> list:
        return [p for p in self.positions.values() if p.state == "OPEN"]

    def open_orders(self) -> list:
        return [o for o in self.orders.values() if o["status"] == "OPEN"]

    def locked_cash(self) -> Decimal:
        total = ZERO
        for o in self.open_orders():
            if o["side"] == "BUY":
                total += (Decimal(o["size"]) - o["filled"]) * Decimal(o["price"])
        return total

    def free_cash(self) -> Decimal:
        return self.cash - self.locked_cash()

    def liquidation_value(self, bids: dict, fee_rate: Decimal) -> Decimal:
        """Cash plus inventory at bid after the closing fee.

        Residual "dust" (the part of a base-fee-reduced quantity below the size step)
        is real inventory; it is swept into the next exit of the same symbol, so it is
        valued like other inventory."""
        value = self.cash
        holdings: dict = {}
        for pos in self.positions.values():
            if pos.qty > 0:
                holdings[pos.symbol] = holdings.get(pos.symbol, ZERO) + pos.qty
        for sym, q in self.dust.items():
            if q > 0:
                holdings[sym] = holdings.get(sym, ZERO) + q
        for sym, q in holdings.items():
            bid = bids.get(sym)
            if bid is None:
                raise KeyError(f"no mark for {sym}")
            value += q * bid * (1 - fee_rate)
        return value

    def fingerprint(self) -> dict:
        """Exact comparable state for reconciliation."""
        return {"cash": str(self.cash), "operating_costs": str(self.operating_costs),
                "positions": {k: [v.state, str(v.qty), str(v.pending_sell), str(v.entry_notional), str(v.exit_gross)]
                              for k, v in sorted(self.positions.items())},
                "open_orders": sorted(o["client_order_id"] for o in self.open_orders()),
                "closed": len(self.closed), "dust": {k: str(v) for k, v in sorted(self.dust.items())},
                "dust_swept": str(self.dust_swept_usdt)}
