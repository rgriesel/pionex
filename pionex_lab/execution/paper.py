"""Paper execution: simulated fills against quotes observed AFTER submission.

Conservative rules (research.md / operations.md):
* A decision can only execute at a later available quote: the first book ticker
  fetched at least `min_latency_ms` after the order was submitted.
* Size is limited by the depth snapshot recorded near that quote; without a fresh
  depth snapshot only top-of-book size is available. The rest is not filled.
* Entries are marketable LIMIT IOC orders (price-capped, may be takers). The
  unfilled remainder is cancelled. Exits are MARKET sells by base size; any
  unfilled remainder stays pending and is retried on the next quote.
* Fees are charged on both sides at the mandate's research fee: buys in the base
  asset (reducing quantity received), sells in quote. This fee asset convention
  is an assumption until verified against an account.
Nothing here can reach the exchange; the order request is only a dry-run preview.
"""
from __future__ import annotations

from decimal import Decimal

ZERO = Decimal(0)


class PaperBroker:
    def __init__(self, market, fee_rate: Decimal, clock, min_latency_ms: int = 250,
                 depth_tolerance_ms: int = 3000, entry_timeout_ms: int = 10_000):
        self.market = market
        self.fee_rate = Decimal(fee_rate)
        self.clock = clock
        self.min_latency_ms = min_latency_ms
        self.depth_tolerance_ms = depth_tolerance_ms
        self.entry_timeout_ms = entry_timeout_ms

    def _levels(self, order, tick):
        depth = self.market.depth_near(order["symbol"], order["submitted_at"],
                                       tick["fetched_at"] + self.depth_tolerance_ms)
        if depth is not None and abs(depth["fetched_at"] - tick["fetched_at"]) <= self.depth_tolerance_ms:
            levels = depth["asks"] if order["side"] == "BUY" else depth["bids"]
            if levels:
                return list(levels), depth["fetched_at"]
        top = (tick["ask"], tick["ask_size"]) if order["side"] == "BUY" else (tick["bid"], tick["bid_size"])
        return [top], None

    def try_fill(self, order: dict, remaining: Decimal | None = None) -> dict | None:
        """Return a fill result, a cancellation, or None if no newer quote exists yet."""
        now = self.clock.now_ms()
        remaining = Decimal(order["size"]) if remaining is None else remaining
        after = max(order["submitted_at"] + self.min_latency_ms, order.get("last_quote_at", 0))
        tick = self.market.first_book_after(order["symbol"], after)
        if tick is None or tick["fetched_at"] > now:
            if order["purpose"] == "ENTRY" and now - order["submitted_at"] > self.entry_timeout_ms:
                return {"status": "CANCELED", "reason": "NO_FRESH_QUOTE", "fills": [], "filled_size": ZERO}
            return None
        levels, depth_at = self._levels(order, tick)
        limit = Decimal(order["price"]) if order.get("price") is not None else None
        fills, left = [], remaining
        for price, size in levels:
            if left <= 0:
                break
            if limit is not None and ((order["side"] == "BUY" and price > limit) or
                                      (order["side"] == "SELL" and price < limit)):
                break
            take = min(left, size)
            if take > 0:
                fills.append((price, take))
                left -= take
        filled = remaining - left
        notional = sum((p * s for p, s in fills), ZERO)
        if order["side"] == "BUY":
            fee, fee_asset = filled * self.fee_rate, "BASE"
        else:
            fee, fee_asset = notional * self.fee_rate, "QUOTE"
        if filled == 0:
            status = "CANCELED" if order["purpose"] == "ENTRY" else "UNFILLED"
            reason = "NO_LIQUIDITY_WITHIN_LIMIT" if order["purpose"] == "ENTRY" else "NO_BID_LIQUIDITY"
        elif left > 0:
            status, reason = ("PARTIAL_CANCELED", "IOC_REMAINDER_CANCELED") if order["purpose"] == "ENTRY" \
                else ("PARTIAL", "REMAINDER_PENDING")
        else:
            status, reason = "FILLED", "FILLED"
        return {"status": status, "reason": reason,
                "fills": [(str(p), str(s)) for p, s in fills], "filled_size": filled,
                "avg_price": (notional / filled) if filled else None, "notional": notional,
                "fee": fee, "fee_asset": fee_asset, "remaining": left,
                "quote_fetched_at": tick["fetched_at"], "depth_fetched_at": depth_at,
                "quote_bid": tick["bid"], "quote_ask": tick["ask"],
                "latency_ms": tick["fetched_at"] - order["submitted_at"]}
