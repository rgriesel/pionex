# CLO-237-v2 — new test, pre-registered 2026-11-07 11:53:16 SAST

**NOT RUN.** This is a separate trial after CLO-237's FAIL, not a replacement
result or a re-judgment. No historical returns were computed for this rule.

WHY: the 40x approximation lost 69.3% of total capital, including one isolated
liquidation, while turnover consumed small wins. The owner also earns on shorts,
which long-only cannot reproduce. WHAT: test lower exposure and both directions
with wider grid spacing, rather than assuming the win rate is an edge.

The first automated NEXT placeholder suggested 5x / 60 rows / $25 margin.
Static notional arithmetic rejects that combination: $125/60 is only $2.08
per row before rounding, below the existing $10 minimum. That placeholder was
never run and is superseded by this complete specification. This is not a
parameter chosen from historical variant performance.

- BTC_USDT_PERP, starting capital $100, one isolated bot at a time, no topups.
- Every eight hours UTC, use the prior closed hour. Long when its close exceeds
  both EMA50 and the close 168 hours earlier; short when below both; else cash.
  Enter at the next open. Minimum 168-hour contiguous warmup.
- Exactly 5x leverage, margin min($50, available equity/2), 10 arithmetic rows
  across entry +/-1/15. Signed linear inventory accounting for shorts; do not
  reflect prices and treat reciprocal returns as linear short P&L.
- Round quantities and levels to public Pionex contract rules. Each row must
  satisfy max($10, public minimum notional), minimum size and order limits;
  skip any infeasible entry, never increase size to force a fill.
- Net flatten profit >=$1, net loss >=25% margin, eight-hour time limit or
  closed-bar range break: flatten at next open. No discretionary stall exit.
- Same fee, spread, slippage, funding assumptions and 2x/4x stresses as CLO-237.
  Funding debited conservatively for both sides. Inventory-dependent liquidation
  with current symbol liquidation fee, 0.5% assumed maintenance and adverse
  mark basis 10bp for each direction. Full isolated margin loss on liquidation.
  Gaps and both OHLC paths remain conservative; cash reserve never funds a bot.
- Fixed sensitivity neighbours: leverage4, 8 rows, hold12h, each one change
  from the primary and all counted separately; no selection among outcomes.
- Controls: same-entry initial inventory hold and unconditional direction-
  balanced grids. Full nonlinear entry-null replay needs an independent
  pre-registered implementation; a notional timing approximation cannot pass it.
- Require all existing luck-1 gates, >=100 trades, zero liquidations, intrabar
  drawdown <=35%, mean rolling30 return >=100%, adjusted trade bootstrap lower
  bound >0, positive final third and outperformance of the same-entry hold.
  Insufficient history or missing causal/forward inputs remains insufficient.
- Reusing CLO-237 history is development evidence only. First eligible
  untouched test date is after this registration; maintain a prospective
  Pionex input/fill record and run once under a newly assigned issue. Do not
  call historical development a fresh untouched holdout or relax 750 days.

Before any run, put this full specification with the actual SAST timestamp in
the new evaluator's docstring and reserve all four trials. The new issue must
complete implementation/synthetic validation and data feasibility first.
