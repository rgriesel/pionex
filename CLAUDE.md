# Pionex Trading Lab — project rules

- Follow the installed skill: `.claude/skills/pionex-trading-lab/SKILL.md` and its references.
- Demo and paper trading until a strategy proves itself; then live (owner policy 2026-10-17, no minimum
  paper period). "Proven" = a pre-registered test that PASSES, a Red Team HOLDS (fixes re-run) and the
  Risk Officer's READY FOR OWNER REVIEW; forward/shadow results are reported alongside. The owner then
  sets the mandate (`config/mandate.v1.json`: live_enabled, mode, allowed symbols, limits, lock) and live
  trading starts. Agents never edit the mandate or its lock, never raise limits, and never place live
  orders while the mandate says `live_enabled=false` (its state on 2026-10-17).
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
