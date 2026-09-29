# Pionex Trading Lab — project rules

- Follow the installed skill: `.claude/skills/pionex-trading-lab/SKILL.md` and its references.
- Paper only. `config/mandate.v1.json` has `live_enabled=false`; never edit the mandate or its lock
  (edits are denied in `.claude/settings.json`), never add a live order path, never raise limits.
- Never handle exchange secrets: no keys in chat, source, logs, tests, or browser code. Paper
  trading needs none. `review-latch` is a human-only command.
- Order requests are Pionex dry-run previews (`pionex_lab/execution/dryrun.py`); fills are simulated
  in `pionex_lab/execution/paper.py` from quotes observed after submission.
- The dashboard is generated: edit `tools/build_dashboard.py`, then run `python3 tools/build_dashboard.py`.
- Before committing: `python3 -m unittest discover -s tests` and
  `python3 -m unittest discover -s .claude/skills/pionex-trading-lab/scripts -p 'test_*.py'`.
- Never present backtests, paper results, or synthetic test-feed data as evidence of profitability.
