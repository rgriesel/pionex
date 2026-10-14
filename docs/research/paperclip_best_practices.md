# Paperclip best practices for the Cloudworks Technologies AI trading firm

Research date 2026-10-14. Instance: Paperclip 2026.1012.0, `local_trusted`, `claude_local` adapter, engine `cli`.
Status: **research only. Nothing was changed** in Paperclip, the repo settings, the mandate, or any agent. Only
read-only GET requests, file reads and web fetches were used. Nothing here is applied until the lead or owner does it.

## 0. How to read this

Evidence tags used on every claim that matters:

| Tag | Meaning |
|---|---|
| [docs] | Stated on a public Paperclip or Claude Code docs page (URL in section d). Docs were read through a summarising fetch tool, so exact field names were cross-checked where they matter. |
| [local] | Observed on this machine: the running API (read-only GET), the installed package (`...\npm\node_modules\paperclipai`), or a run log under `~\.paperclip\instances\default\data\run-logs`. |
| [repo] | Seen in this repository. |
| [community] | Blog, forum, GitHub issue or video summary. Anecdotal; not independently verified. |
| [UNVERIFIED] | Reasoned or inferred, or a route/field I could not confirm. Test before relying on it. |

Hard limits respected by every recommendation: paper only; no live order path; no exchange or API keys handled by
agents; the owner's $100 live cap; `config/mandate.v1.json` and its lock untouched. Where a recommendation touches a
secret (the Telegram token), section c states exactly who handles it and what the residual risk is.

Docs pages that did not load (404) and were therefore not used: `/reference/api/goals/`, `/administration/costs-budgets/`,
`/llms.txt`, `/sitemap-index.xml`. Search snippets and the installed code were used instead and are tagged.

## Top findings in 12 lines

1. The binding budget is the owner's Claude subscription window, not dollars. Paperclip cent-budgets cannot trip:
   subscription runs report `costCents: 0` (`billingType: subscription_included`). The account was at 78% of the weekly
   window and 72% of the 5-hour window at research time [local]. Use per-run caps, daily run caps and a quota guard instead.
2. The CEO (Opus) has an 8-hour timer heartbeat enabled [local]; Paperclip's own guidance is heartbeats off, wake by assignment [docs].
3. All 7 agents can create agents and skills, and `requireBoardApprovalForNewAgents` is false, although CEO.md says the board approves hires [local].
4. Red Team review is by convention only; no issue carries an `executionPolicy` [local]. Paperclip can enforce reviewer/approver stages [docs].
5. A successful Scout run left CLO-1 `in_progress` (no disposition set); the instructions never say to set a status [local].
6. All six routines use `enqueue_missed_with_cap`; the docs default is `skip_missed`. `setup_company.py` never updates an existing routine [repo, local].
7. Every agent run loads 34 tools, 39 skills (finance, docx, pptx, computer-use...), 75 slash commands: a 34K-token first-turn prefix [local].
8. `.claude/settings.json` has an empty deny list although CLAUDE.md says mandate edits are denied [repo]. FIRM.md already flags it.
9. Telegram: the notifier code exists (`pionex_lab/notify.py`) but neither `~/.telegram.env` nor `~/.wave-alerts.env` exists and no agent calls it [repo, local]. Paperclip's own Telegram connector needs a public HTTPS URL (not suitable for `local_trusted`).
10. The evidence standard says "correct for the number of tests" but only within one test family (Bonferroni); there is no firm-level trial count or deflated Sharpe for the one candidate [repo].
11. No Paperclip trading/quant company pack exists; Clipmart is not launched. The one community "trading firm" template is a prompt with a thin validation bar. Do not import anything [docs, community].
12. Skills: install only `reflection-coach` (bundled) and 3 vetted methodology skills for the Red Team; write one own evidence-standard skill. Avoid anything needing pandas, vectorbt, TA-Lib, API keys, or sending telemetry.

---

## (a) Gap analysis: our setup vs best practice

### a1. What we already do right (keep)

| Practice | Source | Ours |
|---|---|---|
| Start with 5-6 focused agents; avoid importing large prebuilt orgs (dotta's talk advises against a 130-agent template) | [community] ai.engineer talk | 7 agents, hand-built [repo] |
| Frontier model for the CEO, cheaper models for simple roles; model per role | [community] dotta; [docs] adapter config | opus/sonnet/haiku split [repo] |
| The agent that does the work is not the agent that checks it; reviewers only where it matters | [community] dotta talk, Lewis Jackson x dotta video summary | Quant vs Red Team vs Risk Officer; review only on PASS [repo] |
| Risk limits in hard-coded logic the LLM cannot modify; LLMs "did not reliably follow risk rules" | [community] video summary; template README | mandate + hash lock + no order path [repo] |
| Paper by default; risk sign-off before real capital; human decision for live | [community] template README | >= 60 paper days, risk officer, owner, $100 cap [repo] |
| Append-only log of every test including failures | [community] template README | `docs/STRATEGY_LOG.md` [repo] |
| Routines for scheduled work, heartbeats off for workers | [docs] routines page | 6 routines, only CEO has a timer [local] |
| Instructions short and role-specific, not a pasted generic manual | [docs] agents guide | each AGENTS.md is 20-40 lines [repo] |

### a2. Gaps

Severity: H = fix this week, M = fix in 2 weeks, L = nice to have.

| # | Area | Our setup (evidence) | Best practice (source) | Sev |
|---|---|---|---|---|
| G1 | Idle heartbeats | CEO `runtimeConfig.heartbeat = {enabled: true, intervalSec: 28800}` on Opus [local] | Keep agent heartbeats off; wake by routine/assignment [docs routines]. Community advice: workers off, CEO long interval only while learning [community newsletter]. A GitHub issue measured idle agents burning most context tokens for ~6% of delivered issues [community #3401] | H |
| G2 | Budget model | Company and agent budgets are 0 / unset [local]. Even if set, they cannot trip: `GET /costs/by-agent` shows `costCents: 0` for a run whose `usageJson.costUsd` is 0.256 and `billingType: subscription_included` [local]. Budget policy metric is `billed_cents` [docs] | Per-agent monthly budgets with 80% warn / 100% hard stop [docs]. For subscription use treat the plan window as the budget and watch token counts, not dollars [community] | H |
| G3 | Per-run brakes | `adapterConfig` has only model/cwd/timeouts; `maxTurnsPerRun` default 300, no `effort`, no `--max-budget-usd`, no `maxDailyRuns` [local, docs] | `maxTurnsPerRun`, `effort` are documented claude_local fields [docs]; `--max-turns`, `--effort`, `--max-budget-usd` are passed to the CLI [local code, docs]; `heartbeat.maxDailyRuns` hard-cancels extra wakes [local code] | H |
| G4 | Governance | All 7 agents: `canCreateAgents: true`, `canCreateSkills: true`; company `requireBoardApprovalForNewAgents: false` [local]. CEO.md says "The board approves hires" [repo] | With the policy on, hires land in `pending_approval` and the new agent stays inert until the board decides [docs]. Agents may only do what their responsible user can [docs] | H |
| G5 | Review enforcement | Red Team review is requested by CEO instruction; CLO-1 and all issues have `executionPolicy: null` [local] | Execution policy: runtime moves a finished issue to `in_review`, assigns the reviewer, can add an approval stage, caps review rounds (`maxReviewRounds`, default 3) and escalates to a human [docs] | M |
| G6 | Run close-out | Run succeeded (14 turns) but CLO-1 is still `in_progress` [local]. No instruction says to set a status | A run must set a valid disposition; a progress comment does not count; otherwise one corrective wake, then a recovery owner [docs debug-stuck-heartbeat] | M |
| G7 | Routine config | All six: `catchUpPolicy: enqueue_missed_with_cap` (cap 25) [local, docs]. `setup_company.py` creates routines only if missing (`routine exists` -> skip) so edits never propagate [repo]. No company goal, no projects [local] | Default `skip_missed`; `always_enqueue` "stacks backlogs" [docs]. Goal = shared reference for all agents [docs first-company] | M |
| G8 | Prompt prefix | `system/init` of the Scout run: 34 tools, 39 skills (graphify, finance:*, docx, pptx, computer-use, chrome...), 75 slash commands, 2 Paperclip MCP servers; first turn 20,040 cache-creation + 14,175 cache-read tokens [local run log] | Context hygiene: lean instructions, only needed skills [docs agents]. Claude Code `--setting-sources` limits settings loaded [docs]. (`--bare` is not usable: it ignores the subscription login [docs headless]) | M |
| G9 | Notifications | `pionex_lab/notify.py` implements critical/important/daily with anti-spam [repo]; token files absent [local]; no AGENTS.md calls it [repo]; FIRM_RULES rule 5 lists `~/.wave-alerts.env` but not `~/.telegram.env` [repo]. Chat connectors flag is off [local] | Paperclip pushes nothing outbound; the documented pattern is a routine plus notifier agent polling the API [docs how-to]. Telegram connector is webhook-only and needs a public HTTPS origin [docs, local code] | M |
| G10 | Harness-level limits | `.claude/settings.json` -> `"deny": []`; CLAUDE.md claims mandate edits are denied [repo]. Agents run `dangerouslySkipPermissions: true` [local]. Red Team / Risk Officer are "read-only" by instruction only [repo] | Deny rules are evaluated first and `--disallowedTools` removes a tool from context; but Read/Edit deny rules do not stop a Python script that opens a file itself [docs permissions]. Hard limits in code, not prompts [community] | H |
| G11 | Evidence standard | Bonferroni exists inside single studies (`research/metrics.py`, `walkforward.py`) [repo]; no firm-level trial counter or deflated Sharpe; the one candidate's rules were "written with the first results" after ~20 failed ideas and 93+21 zoo/WL tests [repo STRATEGY_LOG] | Report trial count and deflate the Sharpe ratio for selection bias [Bailey & Lopez de Prado 2014]; minimum backtest length vs trials [Bailey, Borwein, Lopez de Prado, Zhu 2014] | M |
| G12 | Scout reliability | The first YouTube-calls run took 24.4 min for 14 turns and recorded only 2 of 4 calls because YouTube blocked two transcripts [local CLO-1 comment, run log] | Do mechanical, repeatable fetching in code; keep the LLM for judgement [general practice; UNVERIFIED benefit here] | M |
| G13 | Skills and learning | Only Paperclip bundled skills; user-level skills (`graphify`, `karpathy-guidelines`) leak into every run as "external" [local]. Weekly Firm Improvement review asks for "cost per agent" but cents are 0 [repo, local] | Encode repeated corrections as skills; a "skill consultant" agent diagnoses skills not being used [community dotta]. Paperclip ships `reflection-coach` for this [local catalog] | L |

### a3. What other people's setups show

| Source | What it shows | Use for us |
|---|---|---|
| dotta, AI Engineer talk [community] | Start small; add agents only for proven needs; separate verifier; budgets per agent and per project; do not treat subscription $0 as zero cost; approvals at major steps; keep editing agent instructions from observed mistakes | Confirms our shape; supports C1-C5 |
| Lewis Jackson x dotta video (third-party AI summary page only) [community, unverified] | Risk limits must be hard-coded; LLMs did not reliably follow risk rules; reviewers for high-stakes tasks only; subscription terms for local Claude Code use described as unclear; "thousands of strategies yielded only a few that worked" | Supports mandate-in-code and review-only-on-PASS. Subscription-terms point: [UNVERIFIED], check Anthropic's current terms for 24/7 unattended use |
| `jackson-video-resources/paperclip-zero-human-trading-firm` (129 stars, prompt-only repo) [community] | CEO + research + backtest + risk + execution + cost-optimizer; all agents Sonnet 4.6, 40 turns max, `dangerouslySkipPermissions`; paper default; 30 paper days; `risk-thresholds.json` the user edits. Critique: risk file sits in the agents' own folder, API key persisted in plaintext, no out-of-sample or overfitting guard | We already exceed it on validation. Borrow only: a weekly cost-optimizer (= our Firm Improvement) and the `maxTurns` cap |
| Community token-cost newsletter and GitHub #3401 / discussion #449 [community] | Idle heartbeats are the main cost driver; CEO 4h while learning, workers off, reviewers off or daily; "if no concrete blocker or decision exists, do not comment"; cap new issues per run at 3 | C1, C5. Note the comment rule conflicts with Paperclip's comment backstop for issue-bound runs (see C5) |
| `paperclipai/companies` repo [docs/community] | 17 packs; closest to finance: ClawTeam Capital (analysis, no trade execution stated), K-Dense Science Lab, Aeon Intelligence (crypto monitoring). None is a trading/quant system. Import: `npx companies.sh add paperclipai/companies/<name>` or `paperclipai company import <folder>`; imported agents arrive paused | Do not import. A pack would bring dozens of agents and skills we have not vetted |
| Clipmart | Announced marketplace; third-party articles say not fully available; the official docs and changelog never mention it [community] | Nothing to use |
| TradingAgents (arXiv 2412.20138) [paper] | Role-based LLM agents with bull/bear debate; backtest Jan-Mar 2024 on 5 large-cap tech stocks; authors' own results; a GitHub issue notes model weights may already contain the future [community] | Not evidence for debate-style agents. Our design (LLMs propose and review; deterministic code trades) is the sound part |
| Profit Mirage (arXiv 2510.07920) [paper] | LLM trading agents look good on backtests inside the model's training period and fail past the knowledge cutoff (authors' audit) | Keep LLMs out of signal generation and out of labelling test-window data. Forward (paper) data is the honest test |
| AlphaAgent (2502.16789), RD-Agent(Q) (2505.15155) [paper, self-reported] | Regularise LLM idea generation: originality vs existing factors, complexity limits, bandit-style allocation of research effort | We already do "read the log, skip repeats". Add a free-parameter limit to pre-registration (C10) |

---

## (b) Prioritised changes (12)

Company id `5e6a1546-5971-4f76-afd5-408d94bed26f`. Agent ids (from `var/paperclip_ids.json`):
CEO `00bfa70d-993f-464c-b1ae-15a5eb484afd`, Research Scout `4cbbec6d-f69a-431c-9323-220c514cefdf`,
Quant `d4d3eae4-8c6d-4234-8cc5-6e008119a8c6`, Red Team `8478bc00-5b1f-4ae9-a4a2-87cda1bdac6b`,
Risk Officer `1322be79-39b5-4257-a6d3-33dab35fa55b`, Trading Desk `868c8d23-fc93-41ac-8534-5bfe188dc7ad`,
Firm Improvement `29e5964c-f383-46d0-b3f8-35b775ee7897`. The local API needs no token on loopback [repo setup script, docs CLI].
Where the setup script owns a setting, change it in `paperclip/setup_company.py` (and the agent .md files) and re-run it; the
live API calls below show the equivalent. `adapterConfig` PATCHes merge with existing keys unless `replaceAdapterConfig: true` [docs agents API];
`runtimeConfig` is replaced as a whole [community #3401; our script already sends the full block].

### C1 (P0). Stop the idle CEO heartbeat; wake the CEO by assignment

- Set CEO heartbeat seconds to 0 in `AGENTS` (script then sends `{"heartbeat": {"enabled": false, "intervalSec": 86400}}`). Live equivalent:
  `PATCH /api/agents/00bfa70d-993f-464c-b1ae-15a5eb484afd` with `{"runtimeConfig": {"heartbeat": {"enabled": false, "intervalSec": 86400}}}`.
- Everything that must reach the CEO must be an issue *assigned* to it (assignment and review requests wake; @-mentions do not) [docs issues API].
  Firm Improvement already "addresses proposals to the CEO": make it say "create one issue titled `Weekly proposals <date>` assigned to the CEO and put the proposals in it". That replaces the CEO's unscheduled "Weekly (Sunday)" step.
- Safety-net alternative if you want a timer: `{"enabled": true, "intervalSec": 28800, "skipTimerWhenNoActionableWork": true}`. This flag exists in the installed server (`services/heartbeat.js`) but is not in the public docs [local, UNVERIFIED in behaviour]; it only skips when the agent has no `todo`/`in_progress` issue assigned [community #3401].
- Source: https://docs.paperclip.ing/guides/projects-workflow/routines/ (best practices), https://paperclip.community/newsletter/your-ceo-is-spending-your-tokens, https://github.com/paperclipai/paperclip/issues/3401.
- Benefit: removes 3 Opus wake-ups a day that have no work. Magnitude [UNVERIFIED]: the CEO has had zero runs so far; measure with `paperclipai cost by-agent --company-id ...`. Cost: none.
- Verify after 48h: `GET /api/companies/<id>/heartbeat-runs?limit=50` shows no `invocationSource: timer` for the CEO.

### C2 (P0). Real brakes for a subscription: per-run caps, daily run caps, quota guard

Why: cents budgets never trip (G2). The only live number is the plan window, visible at
`GET /api/companies/<id>/costs/quota-windows` (CLI: `paperclipai cost quota-windows`) [local]. At research time it
returned `Current session 72%`, `Current week (all models) 78%`, `Extra usage: Not enabled`. The window is shared with the owner's own Claude use.

**A. Per-agent settings.** Starting values (judgement, [UNVERIFIED]; the Scout's measured run was 14 turns / $0.256 API-equivalent, so these leave 5-10x headroom; set each cap to ~3x the p95 of a week's `total_cost_usd` from the run results):

| Agent | `effort` | `maxTurnsPerRun` | `extraArgs` | `heartbeat.maxDailyRuns` |
|---|---|---|---|---|
| CEO (opus) | medium | 80 | `["--max-budget-usd","3"]` | 8 |
| Research Scout (sonnet) | medium | 100 | `["--max-budget-usd","2"]` | 5 |
| Quant (sonnet) | leave auto (rigour is the product) | 150 | `["--max-budget-usd","5"]` | 6 |
| Red Team (opus) | leave auto | 60 | `["--max-budget-usd","4"]` | 4 |
| Risk Officer (opus) | medium | 40 | `["--max-budget-usd","2"]` | 3 |
| Trading Desk (haiku) | low | 25 | `["--max-budget-usd","0.5"]` | 6 |
| Firm Improvement (sonnet) | medium | 60 | `["--max-budget-usd","2"]` | 3 |

- Field names: `effort` -> `--effort` (low|medium|high; xhigh|max on newer models) and `maxTurnsPerRun` -> `--max-turns` are read by the installed claude_local adapter [local code `execute.js`, docs]. `extraArgs` is a string array appended to the CLI call [local code]. `--max-budget-usd` is a Claude Code flag that stops a print-mode run at a client-side cost estimate [docs cli-reference]; whether that estimate runs under subscription auth is [UNVERIFIED] (the run result does carry `total_cost_usd: 0.256`, so it likely does).
- `maxDailyRuns` lives in `runtimeConfig.heartbeat` and cancels any wake (timer, assignment, routine) once that agent has started that many runs in the current UTC day [local code `getHeartbeatDailyCapBlock`; not in public docs; behaviour read from code, not tested]. The UTC day starts 02:00 SAST, which matches the firm's nightly sequence (02:20 desk, 03:40 CEO, 21:45 scout), so caps map cleanly to "per firm day". `maxDailyCostCents` also exists but sums `costCents`, which is 0 here, so it is useless.
- `--max-turns` ends a run with an error when hit [docs]; keep caps generous so a legitimate long run is not cut mid-test. Quant keeps `timeoutSec` 7200.
- Optional: move the weekly Risk Officer review to Sonnet at `effort: medium` (it compares numbers and writes < 200 words) and switch `adapterConfig.model` back to `opus` for the 2026-12-13 promotion gate. Judgement; keep Opus if you prefer.
- Example live call: `PATCH /api/agents/868c8d23-fc93-41ac-8534-5bfe188dc7ad` with `{"adapterConfig": {"effort": "low", "maxTurnsPerRun": 25, "extraArgs": ["--max-budget-usd", "0.5"]}, "runtimeConfig": {"heartbeat": {"enabled": false, "intervalSec": 86400, "maxDailyRuns": 6}}}`.

**B. Quota guard (instruction text, goes in the Run protocol, C5).** The paper-book routine always runs; everything optional yields when the plan is nearly used:

```
Quota check. At the start of every run except the Trading Desk's paper-book run, GET
http://127.0.0.1:3100/api/companies/5e6a1546-5971-4f76-afd5-408d94bed26f/costs/quota-windows.
In the "anthropic" entry, if "Current week (all models)" usedPercent >= 85 or "Current session"
usedPercent >= 90: post one line ("skipped: quota NN%"), set the issue to done, and exit.
```

**C. Optional insurance** (zero effect today): `PATCH /api/companies/<id>/budgets` `{"budgetMonthlyCents": 5000}` and `PATCH /api/agents/<id>/budgets` `{"budgetMonthlyCents": N}` [docs how-to set-monthly-budget]. They only matter if some agent is ever switched to a billed API key, or "Extra usage" is enabled on the account.

- Source: https://docs.paperclip.ing/guides/day-to-day/costs, https://docs.paperclip.ing/reference/api/costs, https://docs.paperclip.ing/reference/adapters/claude-code/, https://code.claude.com/docs/en/cli-reference.
- Benefit: bounds the worst case of any one run and of any one day, and stops the firm from starving the owner's own use. Cost: a few lines of config; a too-low cap can cancel a legitimate run (watch `heartbeat.daily_run_limit` cancellations in the first week).

### C3 (P0). Governance lock-down

1. Company: turn on "Require board approval for new hires" (UI: Settings -> Company -> Hiring; underlying field `requireBoardApprovalForNewAgents`, currently `false` [local]). API route: probably `PATCH /api/companies/<id>` with `{"requireBoardApprovalForNewAgents": true}` [UNVERIFIED; the UI toggle is documented].
2. Permissions (documented route `PATCH /api/agents/{id}/permissions`, body `canCreateAgents` and `canAssignTasks` required booleans, `canCreateSkills` optional) [docs agents API]:

   | Agent | canCreateAgents | canAssignTasks | canCreateSkills |
   |---|---|---|---|
   | CEO | true (hire requests then wait for the board) | true | false |
   | Trading Desk, Quant, Firm Improvement | false | true (they assign issues to the CEO) | false |
   | Research Scout, Red Team, Risk Officer | false | false | false |

   Reason for `canCreateSkills: false`: a skill is persistent instruction text attached to agents; an agent that read a hostile web page should not be able to plant one. The owner installs skills (C11). [Reasoning; no incident observed.] Whether the comment-only agents still work with `canAssignTasks: false` is [UNVERIFIED]: test with the Risk Officer's Monday run.
3. Harness deny rules (owner action in `.claude/settings.json`, which this task did not edit). Suggested content:

```json
{
  "permissions": {
    "deny": [
      "Edit(config/mandate.v1.json)", "Write(config/mandate.v1.json)",
      "Edit(config/mandate.lock.json)", "Write(config/mandate.lock.json)",
      "Read(./.env)", "Read(./var/account.json)", "Read(./var/dashboard.token)",
      "Read(~/.wave-alerts.env)", "Read(~/.telegram.env)",
      "Bash(py -m pionex_lab review-latch*)"
    ]
  }
}
```

   Limits [docs permissions]: deny rules are evaluated before allow rules and apply to Claude's file tools and to `cat/sed/tee`-style commands, but not to a Python script that opens a file itself, and a Bash rule matches the command text as written. So this is a guard against accidents and injected tool calls, not a boundary. The real boundary stays the engine's hash check of the mandate and "no order path in the repo". Whether deny rules hold under `--dangerously-skip-permissions` is [UNVERIFIED]: test with a harmless canary file before relying on it.
4. Red Team and Risk Officer: add `extraArgs: ["--disallowedTools","Edit,Write,NotebookEdit"]` (comma-separated so the flag cannot swallow the prompt). This removes the file-edit tools from their context [docs cli-reference]; they keep Bash for the API and `py -c` reads, so they could still write via shell. It makes "read-only" real for the normal tool path only.

- Source: https://docs.paperclip.ing/how-to/handle-board-approvals-for-hires/, https://docs.paperclip.ing/reference/api/agents/, https://code.claude.com/docs/en/permissions.
- Benefit: closes the one path by which the firm could grow its own cost or instructions without the board. Cost: minutes; none in tokens.

### C4 (P1). Enforce the Red Team review with an execution policy

- On a Quant test that returns **PASS**, the CEO PATCHes that issue (FAIL/INSUFFICIENT need no review; keep that rule, it saves Opus runs):

```json
PATCH /api/issues/<issueId>
{"executionPolicy": {"mode": "normal", "commentRequired": true, "maxReviewRounds": 2,
  "stages": [{"type": "review", "participants": [{"type": "agent", "agentId": "8478bc00-5b1f-4ae9-a4a2-87cda1bdac6b"}]}]}}
```

- For a **promotion** issue (paper -> owner review, due 2026-12-13): review = Risk Officer, approval = the board user (`local-board`, the company's `defaultResponsibleUserId` [local]):
  `"stages": [{"type":"review","participants":[{"type":"agent","agentId":"1322be79-39b5-4257-a6d3-33dab35fa55b"}]},{"type":"approval","participants":[{"type":"user","userId":"local-board"}]}]`.
- Mechanics [docs execution-policy]: when the executor moves the issue to `done`, the runtime sets `in_review` and assigns the reviewer; only the active participant can advance it (others get 422); the original executor cannot review their own work; approving needs a non-empty comment; at `maxReviewRounds` (default 3) it escalates to the responsible human. `maxReviewRounds: 2` caps Opus ping-pong.
- Instruction text, Red Team: "When an issue is assigned to you in `in_review`, you are its reviewer. Approve (PATCH status `done` + comment starting `VERDICT: HOLDS` or `VERDICT: HOLDS WITH FIXES` and the ranked fixes) or request changes (any non-done status + comment starting `VERDICT: BROKEN` and why). Fixes to the *strategy* are never applied to the same test: the CEO opens a new pre-registered test."
- Instruction text, CEO: "On a PASS, set the executionPolicy above before the Quant closes the issue. Do not close a PASS yourself."
- Benefit: the review cannot be skipped by a forgetful CEO run; the runtime keeps the history (`issue_execution_decisions`). Cost: no new runs (same Opus review as today); one more PATCH per PASS.
- [UNVERIFIED]: that an agent-created issue accepts `executionPolicy` on create (docs say yes) and that the Red Team's API calls are accepted as the active participant; try on the next PASS or on a dummy issue.
- Source: https://docs.paperclip.ing/guides/power/execution-policy/.

### C5 (P1). Add a Run protocol to FIRM_RULES.md (shared by all agents)

Text to add (about 12 lines; edit `paperclip/FIRM_RULES.md`, re-run setup):

```
## Run protocol
1. Before you stop, set the issue status: `done` when finished, `blocked` with a one-line reason when you
   cannot continue. Never exit with the issue `in_progress`. A progress comment alone does not close a run.
2. Every issue-bound run ends with a comment (the runtime retries without one). If there is nothing to do,
   the comment is one line: "Nothing to do: <reason>".
3. Update an existing issue instead of opening a new one. At most 3 new issues per run, at most 3 child
   issues per parent. Never create agents or skills; ask the CEO, who asks the board.
4. Quota check (see C2).
5. Cost is measured in tokens and quota-window percent, not dollars (subscription runs report 0 cents).
6. Tell the owner only through `py -m pionex_lab notify` (see C7); never read or print token files.
```

- Do **not** copy the community line "if no concrete blocker or decision exists, do not comment" verbatim: Paperclip's comment backstop re-wakes an issue-bound run that ends without a comment [docs execution-policy]. A one-line comment is the compatible form.
- Also change Firm Improvement step 1: "cost per agent" -> read `GET /api/companies/<id>/costs/by-agent` fields `inputTokens`, `cachedInputTokens`, `outputTokens`, `subscriptionRunCount`, plus `quota-windows`; do not report `costCents` (it is 0).
- Source: https://docs.paperclip.ing/how-to/debug-stuck-heartbeat/, https://paperclip.community/newsletter/your-ceo-is-spending-your-tokens.
- Benefit: routine issues stop piling up as `in_progress`; fewer duplicate issues and "blocked" comments; Firm Improvement measures something real. Cost: about 250 tokens per run of extra instruction (cached).

### C6 (P1). Routine policy fixes and removing script drift

- Set `catchUpPolicy: "skip_missed"` on: Nightly research cycle (CEO, Opus), YouTube BTC calls (forward-only; a stale catch-up is worthless), Morning report, both weekly reviews. After a multi-day outage `enqueue_missed_with_cap` queues up to 25 runs per routine [docs create-a-daily-routine], so a 3-day outage would replay three Opus research cycles. Keep `enqueue_missed_with_cap` on Paper books & daily check **only if** `py -m pionex_lab guidance` replays missed daily candles by itself (then one catch-up run is enough and `coalesce_if_active` merges the rest); if it does, `skip_missed` is also fine [UNVERIFIED: check the code or run it after a skipped day].
- Live: `PATCH /api/routines/<routineId>` `{"catchUpPolicy": "skip_missed"}`; triggers: `PATCH /api/routine-triggers/<triggerId>` (`cronExpression`, `timezone`, `enabled`) [docs routines API]. Keep `concurrencyPolicy: coalesce_if_active` (the documented default).
- Fix the drift: in `setup_company.py`, when `title in have`, PATCH the routine's `description`, `assigneeAgentId`, `concurrencyPolicy`, `catchUpPolicy` and its trigger's `cronExpression`/`timezone` instead of printing "routine exists" (the routine JSON already shows `latestRevisionNumber: 2`, so revisions are kept [local]).
- Do **not** use `activityGatePolicy: require_external_activity` on the core loop. It skips ticks (`failureReason: no_external_activity`) when nothing else happened [docs]; the paper books and morning report must run every day. At most consider it for the weekly Firm Improvement review.
- Benefit: no replay storms after the PC sleeps or reboots; routine edits in code actually take effect. Cost: none.
- Source: https://docs.paperclip.ing/how-to/create-a-daily-routine/, https://docs.paperclip.ing/reference/api/routines/.

### C7 (P1). Notifications to the owner: Telegram via the existing notifier

Full steps and options are in section c. Summary of what to change: (1) owner creates `~/.telegram.env` (no agent does); (2) add the notify block below to the agent instructions; (3) add `~/.telegram.env` to FIRM_RULES rule 5 and to the deny rules in C3.

```
## Telling the owner (Telegram)
Use `py -m pionex_lab notify --level <critical|important|daily> --key <stable-id> "<text, <= 600 chars, numbers first>"`.
- critical: a routine failed twice, a hard limit or the mandate was touched, a paper book missed a day, quota >= 95%.
- important: a Quant PASS, a Red Team verdict, a book or BTC/ETH trend flip, a Risk Officer READY / NOT READY,
  a proposal that needs the board.
- daily: the morning report, Trading Desk only, once.
Reuse the same --key for the same event (it is sent once per 24 h). Quiet hours 23:00-07:00 hold non-critical
messages; max 6 "important" a day. Never read, print or log the token file; the command reads it for you.
```

- Benefit: the owner hears about verdicts, flips, failures and the morning summary without opening the dashboard. Cost: zero tokens beyond the instruction; a Telegram bot. Caveat in section c.

### C8 (P2). Trim the per-turn prompt prefix (measure first)

- Evidence [local run log of the Scout's run `a90c2a20...`]: `system/init` reported 34 tools, 39 skills including `finance:*`, `anthropic-skills:docx/pptx/pdf/xlsx/computer-use/chrome-browser/google-workspace`, `youtube-transcriber`, 75 slash commands, and MCP servers "Paperclip projects" and "Paperclip connections"; the first assistant turn used 20,040 cache-creation + 14,175 cache-read tokens, later turns ~35-50K cache-read each. Most of those skill descriptions are irrelevant to trading.
- Experiment on the Trading Desk only (cheapest): `adapterConfig.extraArgs = ["--setting-sources","project,local"]` (skips user-level settings and the plugins enabled there) [docs cli-reference]. Compare the next run's `system/init` skills list and first-turn tokens against the baseline above. Keep it only if the prefix shrinks and the run still comments and sets status.
- Do not use `--bare` (it never reads OAuth/keychain, so the subscription login stops working) or `--disable-slash-commands` (would also drop Paperclip's own skills) [docs headless, cli-reference].
- Do not `npx skills add -g` anything: that writes to `~/.claude/skills`, which is loaded into *every* agent run and the owner's interactive sessions, and shows up as "external" in each agent's skill snapshot [local]. Install through Paperclip (C11).
- Benefit [UNVERIFIED]: fewer cached tokens per turn; how cache-read tokens count against the plan window is not documented. Cost: one experiment run.

### C9 (P2). Give the company a goal and two projects

- Goal (UI: Goals section; API route not confirmed, the docs page 404ed): "Find, prove and run in paper an after-cost edge on Pionex at the lowest running cost. Live trading only with owner approval, capped at $100. Targets: first candidate through Red Team and 60 paper days by 2026-12-13; weekly Claude quota use below 60% from the firm." A company goal is the shared reference for all agents [docs your-first-company].
- Projects "Research" (scout, quant, red team, CEO cycle) and "Paper desk" (books, morning report, health) with `C:\Users\Desj Griesel\pionex` as workspace; link routines via `projectId`. Gives `paperclipai cost by-project` and the Costs -> Overview "by project" split, so research vs operations cost is visible [docs costs]. A project-scoped activity gate is also possible later.
- Benefit: attribution and context, small. Cost: 10 minutes; a few goal tokens per run [UNVERIFIED how much context the goal adds].

### C10 (P2). Evidence-standard tooling: trial count, deflated Sharpe, leakage test

The one candidate (CTA basket v1.1) is the survivor of ~20 failed ideas and 100+ zoo/oscillator tests, and its rules were written with the first results [repo]. Its in-sample Sharpe 1.37 has no selection-bias adjustment.

- Add `n_trials` to every `docs/STRATEGY_LOG.md` row (variants evaluated to reach that row) and a firm-level append-only `var/reports/trial_registry.json`. The Quant appends it (step 6).
- Before the 2026-12-13 gate the Red Team computes a **deflated Sharpe ratio** and **minimum backtest length** for the basket, with N = the firm-wide number of independent configurations tried en route, and reports it next to the headline Sharpe. Python stdlib is enough (`statistics.NormalDist`). Caveat: DSR assumes roughly independent trials and a return model; it is a screen, not a probability of profit, and the in-sample label stays.
  Sources: https://papers.ssrn.com/abstract=2460551 (Bailey & Lopez de Prado, Deflated Sharpe Ratio), https://scholarworks.wmich.edu/math_pubs/40/ (Bailey, Borwein, Lopez de Prado, Zhu, backtest overfitting and minimum backtest length).
- Red Team check 7 (add to `red-team.md`): "Truncation test: recompute the signal at 5 random dates using only data up to that date and confirm the decision equals the full-run decision. Report the number of free parameters; more than 4 needs the CEO's written justification." Check 8: "No LLM output (labels, scores, summaries) may feed a signal or a test window."
- Quant step 2 addition: "State the number of free parameters and the cumulative `n_trials` in the docstring."
- Evidence base: Bailey et al. above; Profit Mirage (https://arxiv.org/abs/2510.07920) for the LLM-leakage point; AlphaAgent (https://arxiv.org/abs/2502.16789, self-reported) for complexity limits.
- Benefit: guards the only decision that could eventually touch money. Cost: a small Python helper, about 150 extra instruction tokens, no new agent runs.

### C11 (P2). Skills: install few, vetted, per agent, through Paperclip

Shortlist and verdicts are in section b2. Concrete steps (CLI exists in 2026.1012.0 [local]; `paperclipai skills ...` [docs cli/skills]):

```
paperclipai skills install reflection-coach --company-id 5e6a1546-5971-4f76-afd5-408d94bed26f
paperclipai skills agent sync 29e5964c-f383-46d0-b3f8-35b775ee7897 --skill reflection-coach --mode add --company-id 5e6a1546-5971-4f76-afd5-408d94bed26f
```

- `reflection-coach` (bundled, 12 KB, trust `markdown_only`): reviews another agent's last 10-25 issues and proposes the smallest evidence-backed change to its AGENTS.md or skills; proposal and apply are separate runs; AGENTS.md may grow at most 20% per proposal; cites trajectories or drops the rule [local SKILL.md]. This is the structured version of what Firm Improvement does by hand, with the same "propose, CEO decides" gate.
- Own skill `pionex-evidence-standard` (frontmatter flat scalars only, no `>`/`|` blocks [docs write-a-company-skill]): the pre-registration, walk-forward, cost, next-open-fill, trial-count and truncation-test checklist, once, instead of copies in `quant.md`, `red-team.md`, `research-scout.md`. Create with `paperclipai skills create --name pionex-evidence-standard --description "<one line>" --body-file <path> --company-id ...`, attach to Quant, Red Team, Scout with `skills agent sync ... --mode add`.
- Run `paperclipai skills audit <skill> --company-id ...` and read each external SKILL.md in full before attaching; unattached skills cost nothing per run.
- `sync --mode replace` detaches everything not listed, including Paperclip's bundled `paperclip` skill; use `--mode add` [docs].
- Benefit: one place to evolve the evidence standard; a repeatable improvement loop. Cost: about 3K tokens when the reflection skill is invoked (weekly), nothing otherwise.

### C12 (P2). Mechanise the Scout's YouTube fetch (and a fallback)

- Evidence: the first run recorded 2 of 4 calls; transcripts for two channels were blocked; 24.4 minutes of wall time for 14 turns, much of it yt-dlp retries driven turn by turn by the model [local CLO-1 comment, run log].
- Proposal: a small stdlib helper, e.g. `py -m pionex_lab yt-newest`, that for each channel prints newest video id/title/date and either the caption text path or `BLOCKED`, with bounded retries and a cache in `var/tools/subs/`; fallback to the video description/chapters via yt-dlp metadata. Never use cookies or logins (project rule). The Scout then only extracts BTC calls from text it is handed and records "no transcript" explicitly rather than guessing. The helper does not exist yet [repo]; magnitude of the saving is [UNVERIFIED].
- Optional, not recommended now: a task watchdog (`PUT /api/issues/<id>/watchdog` `{"agentId": "<Firm Improvement id>", "instructions": "..."}`) on the nightly cycle issue. It only wakes when the whole subtree has stalled with no continuation path, takes no action on board-only decisions, and costs one extra agent run [docs task-watchdogs]. Routine issues are created fresh each night, so the CEO would have to set it every cycle; the value is low while the cycle is shallow.
- Benefit: shorter, more reliable Scout runs; fewer partial days. Cost: ~50 lines of code and a retest.

---

## b2. Skills shortlist (skills.sh, GitHub, Paperclip catalog)

Install route for everything: Paperclip, not `npx skills add -g`. `paperclipai skills import <source>` accepts GitHub `owner/repo`, skills.sh URLs, or a local path inside an approved workspace root [docs]. Whether a repo import lets you pick individual packages from the CLI is [UNVERIFIED]; check `paperclipai skills import --help`. Windows: Node 24.15 and `yt-dlp` are present on this PC [local]; skills here are Markdown, so Windows is not an obstacle unless noted.

| Skill / repo | What it does | Install | Fits Windows + Claude Code + our limits? | Verdict |
|---|---|---|---|---|
| `reflection-coach` (Paperclip bundled) | Evidence-backed proposals to improve another agent's AGENTS.md/skills; never applies in the same run | `paperclipai skills install reflection-coach --company-id ...` | Yes; markdown only [local] | **Install** (Firm Improvement) |
| Own `pionex-evidence-standard` | Our checklist, one copy | `paperclipai skills create ...` | Yes | **Write** (Quant, Red Team, Scout) |
| `Kryhr/26-quant-trading-skills` (MIT, 31 SKILL.md, 0 stars, 21 commits) https://github.com/Kryhr/26-quant-trading-skills | Methodology text: deflated Sharpe/PBO, look-ahead detection (truncation, future corruption), fill feasibility, authenticity audit gate | `paperclipai skills import Kryhr/26-quant-trading-skills --company-id ...` (README itself says "clone into `.claude/skills/`") | Markdown, no APIs required per README; zero community validation; advisory text only | **Read, then attach 3 to Red Team only**: `statistical-significance-and-deflated-metrics`, `lookahead-bias-detection-methodology`, `backtest-result-authenticity-audit`. Do not attach all 31 (31 descriptions per run) |
| `wshobson/agents` `backtesting-frameworks` (85 lines, conceptual) https://github.com/wshobson/agents | Bias table, walk-forward outline | import the repo or copy the folder | Markdown, no library assumptions | Optional smaller alternative to Kryhr; overlaps our own skill |
| `agent-browser` (Paperclip optional catalog; CLI `vercel-labs/agent-browser`, Apache-2.0, ~44k stars) | Drives a real browser (snapshot, click, screenshot, console, network) for JS-rendered pages | `paperclipai skills install agent-browser --company-id ...` plus `npm install -g agent-browser` then `agent-browser install` (downloads Chrome for Testing) | Windows behaviour documented (private desktop, job object) but no Windows install section [docs/README]; Node present | **Optional, Scout only**, for JS-rendered pages such as TradingView script pages. Use `--allowed-domains`. No logins (project rule). Static `WebFetch` is cheaper when it works |
| `tradermonty/claude-trading-skills` (MIT, ~3k stars) | 40+ equity-oriented skills; `backtest-expert`, `position-sizer`, `drawdown-circuit-breaker` need no key | clone folders to a workspace path, import | Many skills need FMP/Alpaca keys; equities focus | Skip (key handling is out of bounds). Read `backtest-expert` for ideas only |
| `shakeebshaan/claude-code-quant-skills` (2 stars, 2 commits) | `/backtest-review`, `/strategy-critique`, `/risk-report`, `/hedge-lab` | git clone + symlink | Immature; hedge/arbitrage content irrelevant | Skip |
| `marketcalls/vectorbt-backtesting-skills` | VectorBT, TA-Lib, QuantStats templates | n/a | Needs pandas/vectorbt/TA-Lib; the lab is stdlib-only | Skip |
| K-Dense `statsmodels` (MIT) | OLS/GLM/time-series diagnostics | `npx skills add K-Dense-AI/claude-scientific-skills --skill statsmodels` | Needs statsmodels, not stdlib | Skip unless the lab accepts dependencies |
| `last30days` (Paperclip optional) | Social/web trend digest across Reddit, X, YouTube, GitHub... | `paperclipai skills install last30days` | Trust level `scripts_executables` (runs scripts), ~131 KB SKILL.md, optional API keys [local, docs] | Skip |
| `caveman` (juliusbrussee, Apache-2.0, ~112k stars) | Terse replies, input compression | `npx skills add JuliusBrussee/caveman -g` or CLI | CLI sends usage stats by default (opt-out `DO_NOT_TRACK=1`); its own README says a plain "Answer concisely" captures much of the gain; own benchmarks | Skip. FIRM_RULES already says "no long reports" |
| `find-skills` (vercel-labs/skills, 3.9M installs), `company-creator` (paperclipai/paperclip) | Meta tools to discover skills / generate company packages | n/a | Agents should not self-install | Skip |

Install counts are from the skills.sh leaderboard at research time [community].

---

## (c) Telegram and other notifications

State today: `py -m pionex_lab notify` exists with levels `critical` / `important` / `daily`, a 6-per-day cap for `important`, the same `--key` sent at most once per 24 h, quiet hours 23:00-06:59 local (non-critical held in `var/notify/outbox.json`, sent with the next message), text trimmed to 900 chars [repo `pionex_lab/notify.py`]. It reads `TELEGRAM_BOT_TOKEN` (and optional `TELEGRAM_CHAT_ID`) from `~/.telegram.env`, falling back to `~/.wave-alerts.env`; with no chat id it uses the latest chat that messaged the bot [repo `waves/alerts.py`]. Neither file exists yet; the outbox is empty [local]. No agent instruction calls it [repo].

### Option 1 (quick start, about 10 minutes, no new code): owner creates the token file; agents call `notify`

1. Telegram app -> message **@BotFather** -> `/newbot` -> display name (e.g. "Cloudworks AI trading") -> username ending in `bot` -> copy the token (`123456789:AA...`) [docs telegram connector, BotFather steps]. Use a **dedicated bot** for this; do not reuse it for the Paperclip connector later (a bot has one webhook, and `getUpdates` stops working while a webhook is set [Telegram Bot API docs]).
2. Open the new bot, press Start, send "hi".
3. In PowerShell, as yourself, not through an agent: `notepad "$env:USERPROFILE\.telegram.env"` and write
   `TELEGRAM_BOT_TOKEN=<token>` (and optionally `TELEGRAM_CHAT_ID=<your numeric chat id>`). Then restrict it:
   `icacls "$env:USERPROFILE\.telegram.env" /inheritance:r /grant:r "${env:USERNAME}:(R,W)"`.
4. Test: `cd "C:\Users\Desj Griesel\pionex"; $env:PYTHONPATH = (Get-Location).Path; py -m pionex_lab notify --level important --key setup-test "Cloudworks AI trading: test"`. Expected output `sent` (or `held (quiet hours)` between 23:00 and 07:00, or `held (no Telegram token file yet)` if step 3 failed).
5. Add the "Telling the owner" block from C7 to the CEO, Trading Desk, Red Team, Risk Officer and Quant instructions (Desk: daily + critical; Red Team/Risk/Quant/CEO: important).
6. Add `~/.telegram.env` to FIRM_RULES rule 5 (it lists `~/.wave-alerts.env` only) and to the deny rules in C3.

Residual risk, stated plainly: the token is handled by the `notify` process, so agents trigger messages but never see the token *by design*. They run as your Windows user with `bypassPermissions`, so they *could* read the file; protection is the rule plus the deny rule, not isolation. If that is not acceptable under "no keys handled by agents", use Option 2.

### Option 2 (recommended end state): an owner-run poller; agents never touch the token

A Windows scheduled task (same pattern as `WaveLab Alerts`) runs a stdlib script every ~10 minutes. It does GET requests to the local API and calls `pionex_lab.notify.notify(...)` itself; the agents only write comments and set issue states. Script not written yet [repo]; about 60 lines. Sources of events (all verified to exist on 2026.1012.0 [local]):

| Event | Endpoint | Level |
|---|---|---|
| Approval waiting (hire, board decision) | `GET /api/companies/<id>/approvals?status=pending` | important |
| Agent in error, budget incident, paused agent | `GET /api/companies/<id>/dashboard` -> `agents.error`, `budgets.activeIncidents`, `budgets.pausedAgents` | critical |
| Failed or cancelled runs (`heartbeat.daily_run_limit`, timeouts) | `GET /api/companies/<id>/heartbeat-runs?limit=50` | important (critical if the paper-book run failed) |
| Issue `blocked` or `in_review` waiting on the board | `GET /api/companies/<id>/issues?status=blocked` | important |
| Plan nearly used | `GET /api/companies/<id>/costs/quota-windows` week >= 90% | important |
| Morning summary | read `docs/status/<today>.md` after 08:05 | daily |

Schedule example (not executed; quoting differs between cmd and PowerShell, so test with `schtasks /Run /TN "Cloudworks Notify"`): `schtasks /Create /SC MINUTE /MO 10 /TN "Cloudworks Notify" /TR "py \"C:\Users\Desj Griesel\pionex\tools\paperclip_notify.py\"" /F`. Paperclip does not push events outbound; the documented pattern is a polling notifier [docs wire-slack-discord how-to]. The docs example polls with an LLM agent every minute, which would be 1,440 runs a day; a plain script costs no tokens.

### Option 3: Paperclip's own Telegram connector (two-way chat with an agent) - not recommended now

- Exists in the installed build (`chat-channels.js` has a `telegram` channel with key `botToken`) [local]. Needs: Settings -> Experimental -> **Chat connectors** on (currently `enableChatConnectors: false` [local]); env var `PAPERCLIP_CHAT_WEBHOOK_PUBLIC_URL` set to a public HTTPS **origin** with no path (the installed parser rejects anything else) on port 443, 80, 88 or 8443 [local, docs]; webhook-only, "no outbound-only mode" [docs].
- Why not now: `local_trusted` has no login, so a public URL would expose the board-level API unless a path-restricting tunnel is put in front (not documented, [UNVERIFIED]); anyone who finds the bot can message it, and by default "Allow unlinked people" is on (guest tasks run in an isolated sandbox only if available) [docs]; inbound text from the internet becomes an agent task, and our agents run `bypassPermissions`. It also gives one bot -> one agent.
- If you want it later: (1) move to authenticated mode (https://docs.paperclip.ing/how-to/enable-multi-user-login/), (2) expose only the webhook through a fixed-hostname tunnel [UNVERIFIED which], (3) set the env var in the environment of the Windows task that starts Paperclip (`paperclip\start_paperclip.vbs`), (4) enable Chat connectors, (5) BotFather -> new bot -> Connectors -> Telegram -> paste token -> choose the answering agent, (6) turn **Allow unlinked people** off and link your own Telegram identity, (7) test with "hello, can you confirm you are connected?" (the doc's verify step).

### Other options

| Option | Fit | Notes |
|---|---|---|
| ntfy.sh push | Good fallback for Option 2's sender | One `POST https://ntfy.sh/<topic>` with `Title` and `Priority` headers; no sign-up; the topic name is the only secret, so use a long random one [ntfy docs]. Free public server limits [UNVERIFIED] |
| AgentMail connector (email) | Possible for rich reports | "Live connection" mode is outbound-only, no public URL; needs an AgentMail API key (stored by Paperclip as a secret, not shown to agents); pricing and sending limits not in the docs [docs, UNVERIFIED] |
| Slack/Discord incoming webhooks | Works, but the documented pattern polls with an LLM every minute | Use a plain script like Option 2 if you prefer Slack/Discord [docs] |
| Paperclip inbox / Approvals tab | Always available, not a push | Hire approvals and review escalations appear there [docs] |
| Plugins (SDK, alpha) | Could add scheduled jobs and webhooks without an LLM | No Telegram/Discord plugin is documented; alpha, "expect breaking changes" [docs plugins]. Option 2 is simpler |

---

## (d) Most useful links

Paperclip docs (base https://docs.paperclip.ing):
- Execution policy: /guides/power/execution-policy/
- Routines: /guides/projects-workflow/routines/ ; daily routine how-to: /how-to/create-a-daily-routine/ ; routines API: /reference/api/routines/
- Costs and budgets: /guides/day-to-day/costs ; set a monthly budget: /how-to/set-monthly-budget ; costs API: /reference/api/costs ; cost CLI: /reference/cli/cost/
- Agents guide: /guides/org/agents/ ; agents API: /reference/api/agents/ ; issues API: /reference/api/issues/ ; hire approvals: /how-to/handle-board-approvals-for-hires/ ; stuck heartbeat: /how-to/debug-stuck-heartbeat/
- Claude adapter fields: /reference/adapters/claude-code/
- Skills reference: /reference/skills/ ; skills CLI: /reference/cli/skills/ ; write a company skill: /how-to/write-a-company-skill/ ; Agent Browser: /reference/skills/optional/browser/agent-browser/
- Connectors: /connectors/ ; Telegram: /connectors/telegram/ ; AgentMail: /connectors/agentmail/ ; Slack/Discord notification pattern: /how-to/wire-slack-discord-notifications/
- Plugins: /administration/plugins/ ; experimental features: /experimental/overview/ ; task watchdogs: /guides/projects-workflow/task-watchdogs
- Company export/import: /guides/power/export-import/ ; changelog: /reference/changelog/ ; multi-user login: /how-to/enable-multi-user-login/

Claude Code docs: https://code.claude.com/docs/en/cli-reference (flags used here), https://code.claude.com/docs/en/headless (bare mode, auth), https://code.claude.com/docs/en/permissions (deny rules).

Community and setups: dotta's talk https://ai.engineer/talks/h403btjldDQ-paperclip-open-source-human-control-plane-ai ; interview transcript https://spoken.md/episode/i-built-an-ai-agent-company-from-scratch-1000757557617 ; Lewis Jackson x dotta (third-party summary) https://videohighlight.com/v/T6jdfZ317Vw ; trading-firm template https://github.com/jackson-video-resources/paperclip-zero-human-trading-firm ; token-cost newsletter https://paperclip.community/newsletter/your-ceo-is-spending-your-tokens ; idle-heartbeat issue https://github.com/paperclipai/paperclip/issues/3401 and discussion https://github.com/paperclipai/paperclip/discussions/449 ; company packs https://github.com/paperclipai/companies.

Research: TradingAgents https://arxiv.org/abs/2412.20138 ; AlphaAgent https://arxiv.org/abs/2502.16789 ; RD-Agent(Q) https://arxiv.org/abs/2505.15155 ; Profit Mirage https://arxiv.org/abs/2510.07920 ; Deflated Sharpe Ratio https://papers.ssrn.com/abstract=2460551 ; backtest overfitting https://scholarworks.wmich.edu/math_pubs/40/.

Skills: https://skills.sh ; https://github.com/vercel-labs/agent-browser ; https://github.com/Kryhr/26-quant-trading-skills ; https://github.com/wshobson/agents ; https://github.com/tradermonty/claude-trading-skills ; https://github.com/shakeebshaan/claude-code-quant-skills ; https://github.com/juliusbrussee/caveman.

Notifications: https://core.telegram.org/bots/api ; https://docs.ntfy.sh/publish/.

---

## Appendix A. Suggested order of work

1. Today (about 30 min, no code): C1 (heartbeat off, FI assigns the CEO), C3.1-C3.2 (approval policy and permissions), C6 (`skip_missed`), C2 for the Trading Desk and CEO.
2. This week: C5 (Run protocol text), C2 for the other agents, C7 Option 1 if the owner accepts the residual risk, C4 on the next PASS.
3. Before 2026-12-13: C10 (trial count and deflated Sharpe for the basket), C11, then C8 and C12 as time allows.

Verification after 48 hours (all read-only): `paperclipai cost by-agent`, `GET /costs/quota-windows`, `GET /heartbeat-runs?limit=50` (no CEO timer runs; any `heartbeat.daily_run_limit` cancellations; every routine issue ended in `done` or `blocked`), and the next run's `system/init` for the C8 experiment.

## Appendix B. Local observations used (read-only, 2026-10-14 ~22:50 SAST)

- `GET /api/instance/settings/experimental`: `enableChatConnectors: false`, `enableAgentChat: false`, `enableStatusCards: false`.
- Company: `budgetMonthlyCents 0`, `requireBoardApprovalForNewAgents false`, `defaultResponsibleUserId local-board`; no goals, no projects; one issue (CLO-1, routine execution, `in_progress`).
- Agents: all `permissions {canCreateAgents: true, canCreateSkills: true}`; CEO heartbeat enabled 28800 s, others disabled; `adapterConfig` has no `effort`, `maxTurnsPerRun`, `extraArgs`.
- Scout run `a90c2a20-...` (YouTube calls, Sonnet): 14 turns, 1,465 s, 37,900 input + 519,425 cached input + 5,253 output tokens, `costUsd 0.256`, `billingType subscription_included`; by-agent `costCents 0`; six 5-hour window readings in the run log rose 26% -> 33% during the run (the window is shared with other use, so not attributable) and the 7-day window read 72-73%.
- `GET /costs/quota-windows` later: current session 72%, current week 78%, extra usage not enabled; `window-spend` costCents 0.
- Skills: company library holds only Paperclip bundled skills; `~/.claude/skills` (`graphify`, `karpathy-guidelines`) appear as external in every agent snapshot.
- Installed server code: `runtimeConfig.heartbeat` supports `skipTimerWhenNoActionableWork`, `maxDailyRuns`, `maxDailyCostCents`; claude_local passes `--effort`, `--max-turns` and `extraArgs`; chat webhook URL must be an HTTPS origin without path.
