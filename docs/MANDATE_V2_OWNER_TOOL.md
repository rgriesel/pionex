# Mandate v2 owner setup (CLO-239)

`tools/owner_enable_live_v2.py` is an interactive owner-authorized setup tool.
Quant tests it exclusively against temporary configurations. It does not read a key,
contact Pionex, submit orders, or change the forward proof gate or executor.

The default invocation previews the field-by-field changes and the strategies
that the current gate considers eligible. No files are written without `--write`
and the exact typed owner/delegate confirmation. Authorization and account scope must be
nonempty. The key prompt accepts a file path only; the file is never opened.

The write creates `config/mandate.v2.json`, replaces the mandate lock with its
SHA-256, and creates `var/live.json` last, pinning that hash and the current gate
allowlist. Existing v2 or live configuration refuses another run. Ordinary write
errors roll back the lock and new files. An exclusive setup guard prevents
concurrent writers, and a changed source hash invalidates the preview. A process/power failure during setup
requires manual reconciliation: a hash mismatch or missing live config fails
closed. An interrupted guard requires reconciliation before retrying; never
remove existing owner configuration to force a rerun.

The owner's binding 2026-11-07 directive delegates the real invocation to the
CEO, after **all** of: CLO-243 merged, CLO-238 and CLO-239 done, CLO-241 HOLDS,
and at least one ELIGIBLE (canary) strategy from the gate. The CEO checks these
issue/review/merge prerequisites; the tool itself rechecks strategy eligibility
immediately before writing. This tool does not approve those prerequisites.
The CEO uses `--write`, adding `--futures` only with certified leverage, and
supplies these authorized prompt answers:

- Authorization: `Owner chat 2026-11-07: total control, keys in .env, arm when gates pass`
- Account scope: `Pionex test account, max 100 USDT`
- Key file path: `C:\Users\Desj Griesel\pionex\.env`
- Confirmation: `I AM THE OWNER OR AUTHORIZED CEO: WRITE MANDATE V2`

The program's credential loader uses `PIONEX_API_KEY` / `PIONEX_API_SECRET`;
the setup stores only the file path. After successful arming the CEO schedules
`py -m pionex_lab live-poll` plus the executor loop, adds them to the watchdog,
sends the owner's one Telegram notice, and records it in the board report as
required by `paperclip/FIRM_RULES.md`. These are dependent operational tasks,
not actions performed by the setup tool or Quant's fixture tests.

Schema 1 loading is preserved. Schema 2 adds `risk.futures_allowed`, integer
`risk.max_leverage`, top-level `allowed_bot_types`, mandatory
`risk.per_bot_tp_sl_required`, and margin caps (`position_margin_fraction`,
`canary_position_margin_fraction`, `gross_margin_fraction`). The caps may be
smaller than, but never exceed, their existing notional equivalents. Margin
means investment plus extra margin. The $100 capital cap, loss limits, agent
authority restrictions and all reference risk constants stay fixed. The
existing executor must independently implement and enforce new product support;
schema permission alone does not make a product executable.

Without `--futures`, the proposal permits spot grids at 1x. With `--futures`, the
tool reads the frozen `var/reports/perp_grid_2026-10-18.json` study and requires
PASS, every predefined gate true, a selected leverage from the registered grid,
zero liquidations and drawdown no greater than 35%. It uses the selected leverage,
never the highest tested leverage. The actual report is FAIL with no selected
leverage, so futures setup currently refuses. A backtest PASS alone would still
not supply forward eligibility, Red Team approval or evidence of future profit.

Validation uses synthetic gate results and temporary directories, including
confirmation refusal, gate revocation between preview and write, rollback,
one-shot refusal, v1 preservation, v2 hash loading and invalid policy fields.
No trading strategy was run or re-tested for this implementation task.
