"""Candle-based simulator of a Pionex SPOT grid bot (CLO-21, 2a). Research only: no order path, no keys.

Mechanics modelled (from docs/PIONEX_GRID_API.md and the grid bot as documented; anything not in the docs is a choice
stated here):
  * `rows` grids = rows+1 price levels between bottom and top, arithmetic (equal difference) or geometric (equal ratio).
  * Every grid (cell i between level i and i+1) trades the same base quantity q. At the start price p0 the bot buys,
    at market, the base needed for all cells whose buy level is >= p0 (they sit as sell orders above); the remaining
    quote is reserved for buy orders at the levels below p0. The investment is split so that cash never goes negative.
  * A cell holding quote buys when price falls to its lower level; a cell holding base sells when price rises to its
    upper level. Invariant: cells below the price hold quote, cells above hold base, so the state is one boundary
    index and every candle is processed with bisect, not a loop over cells.
  * A candle is walked along an assumed path: open -> low -> high -> close if it closed up, open -> high -> low ->
    close if it closed down, starting from the previous close (gaps are crossed like moves). The real path inside a
    candle is unknown; a level counts as filled when price reaches it (touch fill, no queue risk): optimistic.
  * Costs: `fee` per fill (default 0.05%) plus `slip` against us on grid (limit) fills and `slip_market` on the market
    orders (initial buy, stop-loss exit, close on exit).
  * Stop-loss at a price (market exit when the path reaches it), optional take-profit on realized grid profit as a
    ratio of the investment, close on exit (sell all base at the last close) unless `close_on_exit` is False.

Profit split, as Pionex defines it: GRID PROFIT is what completed buy/sell pairs earned: for every cell that sells,
q * (upper - lower) minus the fee and slip of that pair's two fills. FLOAT PROFIT is everything else: total profit
minus grid profit, i.e. the mark-to-market of the base inventory against its cost (the initial buy included) and
the frictions of fills that have not yet completed a pair. grid + float == final equity - investment exactly.
"""
from __future__ import annotations

import math
from bisect import bisect_left, bisect_right

FEE = 0.0005
MIN_GRID_USDT = 10.0                                   # Pionex: at least 10 USDT per grid


def levels(bottom, top, rows, grid_type="geometric"):
    if not (0 < bottom < top) or rows < 2:
        raise ValueError("need 0 < bottom < top and rows >= 2")
    if grid_type == "arithmetic":
        return [bottom + (top - bottom) * i / rows for i in range(rows + 1)]
    if grid_type == "geometric":
        r = (top / bottom) ** (1.0 / rows)
        return [bottom * r ** i for i in range(rows + 1)]
    raise ValueError("grid_type must be arithmetic or geometric")


def step_pct(bottom, top, rows, grid_type="geometric"):
    """Smallest relative step between neighbouring levels (the number the cost rule compares with)."""
    lv = levels(bottom, top, rows, grid_type)
    return min(lv[i + 1] / lv[i] - 1 for i in range(rows))


def simulate(bars, bottom, top, rows, invest, grid_type="geometric", fee=FEE, slip=0.0, slip_market=0.0,
             stop_price=None, take_profit_ratio=None, close_on_exit=True, mark_every=24):
    """bars: list of (t, o, h, l, c). Returns a dict (see keys at the end). The grid starts at bars[0].open."""
    if not bars:
        raise ValueError("no bars")
    lv = levels(bottom, top, rows, grid_type)
    p0 = bars[0][1]
    b = min(rows, bisect_left(lv, p0))                  # cells 0..b-1 hold quote (buy level < p0), the rest hold base
    n_base = rows - b
    start_px = p0 * (1 + slip_market)
    need = n_base * start_px * (1 + fee) + sum(lv[i] * (1 + fee + slip) for i in range(b))
    q = invest / need
    cash0 = invest - q * n_base * start_px * (1 + fee)
    min_eq = invest
    marks = []
    state = {"b": b, "cash": cash0, "base": q * n_base, "gp": 0.0, "fills": 0, "trips": 0}
    exit_reason = None
    exit_px = None

    def equity(px):
        return state["cash"] + state["base"] * px

    def buy_cells(lo, hi):
        for i in range(lo, hi):
            cost = q * lv[i] * (1 + slip)
            state["cash"] -= cost * (1 + fee)
            state["base"] += q
            state["fills"] += 1

    def sell_cells(lo, hi):
        for i in range(lo, hi):
            got = q * lv[i + 1] * (1 - slip)
            state["cash"] += got * (1 - fee)
            state["base"] -= q
            state["fills"] += 1
            state["trips"] += 1
            state["gp"] += q * (lv[i + 1] - lv[i]) - q * lv[i + 1] * (fee + slip) - q * lv[i] * (fee + slip)

    def move(x, y):
        """Walk price from x to y; returns True if the bot stopped (stop-loss or take-profit) on the way."""
        nonlocal exit_reason, exit_px
        if y < x:
            lo_px = y if stop_price is None else max(y, stop_price)
            lo = bisect_left(lv, lo_px)
            if lo < state["b"]:
                hi = min(state["b"], bisect_left(lv, x))
                buy_cells(lo, hi)
                state["b"] = lo
            if stop_price is not None and y <= stop_price:
                exit_reason, exit_px = "stop_loss", stop_price
                return True
        elif y > x:
            nb = min(rows, max(state["b"], bisect_right(lv, y) - 1))
            if nb > state["b"]:
                sell_cells(state["b"], nb)
                state["b"] = nb
            if take_profit_ratio is not None and state["gp"] >= take_profit_ratio * invest:
                exit_reason, exit_px = "take_profit", min(y, top)
                return True
        return False

    prev = None
    last_close = bars[-1][4]
    for k, (t, o, h, l, c) in enumerate(bars):
        path = ([o, l, h, c] if c >= o else [o, h, l, c])
        if prev is not None:
            path = [prev] + path
        stopped = False
        x = path[0]
        for y in path[1:]:
            if move(x, y):
                stopped = True
                break
            x = y
            min_eq = min(min_eq, equity(y))
        if stopped:
            last_close = exit_px
            break
        prev = c
        if (k + 1) % mark_every == 0 or k == len(bars) - 1:
            marks.append(equity(c) / invest)
    if exit_reason is None:
        exit_reason = "window_end"
        exit_px = last_close
    final_px = exit_px
    cash, base = state["cash"], state["base"]
    if exit_reason != "window_end" or close_on_exit:
        sell_px = final_px * (1 - slip_market)
        cash += base * sell_px * (1 - fee)
        base = 0.0
        closed = True
    else:
        closed = False
    final_eq = cash + base * final_px
    if exit_reason != "window_end":
        marks.append(final_eq / invest)
    elif marks:
        marks[-1] = final_eq / invest
    min_eq = min(min_eq, final_eq)
    total = final_eq - invest
    gp = state["gp"]
    return {"grid_profit": gp, "float_profit": total - gp, "total_profit": total, "return": total / invest,
            "final_equity": final_eq, "fills": state["fills"], "round_trips": state["trips"], "exit": exit_reason,
            "closed": closed, "min_equity_ratio": min_eq / invest, "marks": marks, "q": q, "rows": rows,
            "start_price": p0}
