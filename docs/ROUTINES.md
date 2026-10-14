# Routines — now in Paperclip

Since 2026-10-14 every routine runs in Paperclip (company "Cloudworks Technologies AI trading",
http://127.0.0.1:3100), defined in `paperclip/setup_company.py`, times in Africa/Johannesburg.
Missed runs (PC asleep or off) are caught up when Paperclip is back (`enqueue_missed_with_cap`).

| Time | Routine | Agent (model) |
|---|---|---|
| daily 02:20 | Paper books & daily check (`py -m pionex_lab guidance`, Wave Lab health) | Trading Desk (haiku) |
| daily 03:40 | Nightly research cycle: scout → ≤2 quant tests → red team on any PASS | CEO (opus) |
| daily 07:55 | Morning report to the board (`docs/status/<date>.md` + comment) | Trading Desk (haiku) |
| daily 21:45 | YouTube BTC calls + guidance scorecard | Research Scout (sonnet) |
| Mon 09:05 | Weekly risk review of the paper books | Risk Officer (opus) |
| Sun 10:05 | Weekly firm review & improvement proposals to the CEO | Firm Improvement (sonnet) |

What each agent does on these runs is in `paperclip/agents/<agent>.md`; the shared rules are in
`paperclip/FIRM_RULES.md`. To change a routine or instruction: edit those files and re-run
`py paperclip/setup_company.py`.

Retired on 2026-10-14: the Claude-session crons (they never fire while the PC sleeps or the app is
closed), the `PionexLab` supervisor (collector, intraday paper engine, lab dashboard on 8765, account
view), the live order-book recorder and the Pionex Trader panel. `pionex_lab firm due|stamp` is no
longer used.
