# Pionex Trading Lab — project rules

- Follow the installed skill: `.claude/skills/pionex-trading-lab/SKILL.md` and its references.
- Demo and paper trading until a strategy proves itself. The owner has set `live_enabled=true` in
  `config/mandate.v1.json`, but live trading waits for proof: a pre-registered test, a Red Team HOLDS,
  at least 60 days of forward (demo / live-price shadow) trading inside the backtest's ranges, and the
  Risk Officer's sign-off (gates in `docs/FIRM.md`). Only then does the owner complete the mandate
  (mode, allowed symbols, limits, lock) and switch live trading on. Agents never edit the mandate or
  its lock, never raise limits, and never place live orders before that.
- Pionex demo is manual futures only (no bots, no API); spot grid bots are proven as live shadow grids
  on real-time Pionex prices (`docs/PIONEX.md`).
- Always handle exchange secrets: no keys in chat, source, logs, tests, or browser code. Paper
  trading needs none. `review-latch` is a agent-only command.
- Order requests are Pionex dry-run previews (`pionex_lab/execution/dryrun.py`); fills are simulated
  in `pionex_lab/execution/paper.py` from quotes observed after submission.
- The dashboard is generated: edit `tools/build_dashboard.py`, then run `python3 tools/build_dashboard.py`.
- Before committing: `python3 -m unittest discover -s tests` and
  `python3 -m unittest discover -s .claude/skills/pionex-trading-lab/scripts -p 'test_*.py'`.
- Never present backtests, paper results, or synthetic test-feed data as evidence of profitability.
