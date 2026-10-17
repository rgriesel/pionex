"""Perpetual-futures simulator on the Binance proxy perp data (research only; no order path).

Written 2026-10-17 07:30 SAST (CLO-34), before any futures test is run. Every futures test reuses it.

Data (labelled PROXY, not Pionex): Binance USD-M perpetual 1h klines (`BTC_USDT_PERP`, `ETH_USDT_PERP`)
and settled funding rates (`funding` table, BTC and ETH only) from `var/proxy_market.db`.

Model, one isolated-margin position at a time, decided on closed bars, filled at an hourly OPEN:
  size      margin = equity * margin_frac; notional = margin * leverage (1..5x allowed)
  costs     Pionex futures fee per side: taker 5 bps (default) or maker 2 bps, on notional, at entry
            and at a normal exit; a liquidation pays LIQ_FEE of notional instead of the exit fee
  funding   settled at the exchange timestamps (00/08/16 UTC): long pays rate x notional, short
            receives it; notional is marked at that hour's open. A settlement counts when
            entry_t < settlement <= exit_t (the position entered at a settlement hour misses it, the
            one exited then has paid/received it - same convention as swing/carry.py)
  liquidation  per bar, after funding, at the bar's worst price (low for a long, high for a short):
            margin + unrealised pnl + funding paid - entry fee <= (MMR + LIQ_FEE) x notional at that
            price. If hit, the whole margin is lost (isolated: the loss cannot exceed the margin) and
            the trade exits at the closed-form liquidation price. Worst-price-in-bar is conservative.
  result    `net_bps` is the return on EQUITY (margin_frac of it was at risk), so it feeds the
            risk-of-ruin Monte Carlo (`research/ruin.py`) directly.
ASSUMPTIONS (Pionex does not publish its tiers in the public API; unverified, set conservatively):
  MMR = 0.5% of notional, LIQ_FEE = 0.5% of notional. With these a 5x long is liquidated about 19.0%
  below entry before costs; 1x is liquidated only about 99% below (a long) - effectively never.
"""
from __future__ import annotations

TAKER_BPS = 5.0
MAKER_BPS = 2.0
MMR = 0.005
LIQ_FEE = 0.005
HOUR_MS = 3_600_000
MAX_LEVERAGE = 5.0


def liquidation_price(entry: float, side: int, leverage: float, mmr: float = MMR, liq_fee: float = LIQ_FEE,
                      fee_bps: float = TAKER_BPS) -> float:
    """Price at which an isolated position with no funding accrued is liquidated.

    side +1 long, -1 short. Equity = margin*(1 + ...) solved against (mmr + liq_fee) x notional,
    ignoring the small price-dependence of the threshold notional (it is evaluated at the liq price,
    exactly, below)."""
    if leverage <= 0:
        raise ValueError("leverage must be positive")
    m = 1.0 / leverage - fee_bps / 1e4           # margin per unit notional after the entry fee
    k = mmr + liq_fee
    # long:  m + (p/e - 1) = k * p/e   ->  p/e = (1 - m) / (1 - k)
    # short: m + (1 - p/e) = k * p/e   ->  p/e = (1 + m) / (1 + k)
    return entry * ((1 - m) / (1 - k) if side > 0 else (1 + m) / (1 + k))


def simulate_trade(bars: list, side: int, leverage: float, entry_idx: int, exit_idx: int, funding: list,
                   margin_frac: float = 1.0, entry_fee_bps: float = TAKER_BPS, exit_fee_bps: float = TAKER_BPS,
                   mmr: float = MMR, liq_fee: float = LIQ_FEE) -> dict:
    """Hold from the OPEN of bars[entry_idx] to the OPEN of bars[exit_idx].

    bars: [(t, o, h, l, c)] hourly; funding: [(settlement_ms, rate)] oldest first.
    Bars entry_idx .. exit_idx-1 are held in full and checked for liquidation."""
    if side not in (1, -1):
        raise ValueError("side must be +1 or -1")
    if not 0 < leverage <= MAX_LEVERAGE:
        raise ValueError("leverage must be in (0, 5]")
    if not 0 < margin_frac <= 1:
        raise ValueError("margin_frac must be in (0, 1]")
    if not 0 <= entry_idx < exit_idx < len(bars):
        raise ValueError("need 0 <= entry_idx < exit_idx < len(bars)")
    entry = bars[entry_idx][1]
    t0, t1 = bars[entry_idx][0], bars[exit_idx][0]
    qty = leverage / entry                       # per 1 unit of margin
    margin = 1.0
    fee_in = qty * entry * entry_fee_bps / 1e4
    fund_cum = 0.0                               # in margin units; positive = received
    fund_by_hour = {}
    for ft, rate in funding:
        if t0 < ft <= t1:
            fund_by_hour.setdefault(ft // HOUR_MS * HOUR_MS, []).append(rate)
    def settle(hour_t: int, price: float) -> float:
        return -side * sum(fund_by_hour.get(hour_t, ())) * qty * price

    liquidated, exit_price, exit_t = False, bars[exit_idx][1], t1
    for i in range(entry_idx, exit_idx):
        t, o, h, l, c = bars[i]
        if i > entry_idx:
            fund_cum += settle(t, o)             # a settlement at this bar's open, marked at that open
        worst = l if side > 0 else h
        equity = margin + side * qty * (worst - entry) + fund_cum - fee_in
        if equity <= (mmr + liq_fee) * qty * worst:
            liquidated, exit_t = True, t
            exit_price = liquidation_price(entry, side, leverage, mmr, liq_fee, entry_fee_bps)
            break
    if not liquidated:
        fund_cum += settle(t1, exit_price)       # settlement at the exit open
    if liquidated:
        pnl = -margin                            # isolated margin lost; nothing more can be lost
        fee_out = 0.0
    else:
        fee_out = qty * exit_price * exit_fee_bps / 1e4
        pnl = side * qty * (exit_price - entry) + fund_cum - fee_in - fee_out
        pnl = max(pnl, -margin)
    return {"side": side, "leverage": leverage, "entry_time": t0, "exit_time": exit_t, "entry": entry,
            "exit": exit_price, "liquidated": liquidated, "funding_on_margin": fund_cum,
            "return_on_margin": pnl, "net_bps": pnl * margin_frac * 1e4}


def load_perp(paths, symbol: str, start_ms: int | None = None):
    """(bars, funding) for 'BTC_USDT' or 'ETH_USDT' from the proxy DB: bars [(t,o,h,l,c)] 1h."""
    from ..data.proxy import funding_series
    from ..data.store import MarketView
    view = MarketView(paths.proxy_market)
    b = view.bars(symbol + "_PERP", "60M", start_ms=start_ms)
    return list(zip(b.t, b.o, b.h, b.l, b.c)), funding_series(view.conn, symbol)
