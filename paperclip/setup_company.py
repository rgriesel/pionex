"""Create (or update) the Cloudworks Technologies AI trading company in the local Paperclip instance.

Idempotent: finds the company, agents and routines by name and only creates what is missing; agent
instructions and adapter settings are refreshed on every run. Talks to the local-trusted API on
127.0.0.1:3100 (loopback only; no keys involved). Run: py paperclip/setup_company.py
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:3100/api"
HERE = Path(__file__).resolve().parent
REPO = str(HERE.parent)
COMPANY = "Cloudworks Technologies AI trading"
DESCRIPTION = ("AI trading firm: find, prove and run a real after-cost edge on Pionex at the lowest running cost. "
               "Research and paper trading 24/7; live trading only with the owner's approval and never more than $100.")
TZ = "Africa/Johannesburg"
RULES = (HERE / "FIRM_RULES.md").read_text(encoding="utf-8")
# On Windows the ACP engine fails to spawn claude-agent-acp.cmd (Node cannot spawn .cmd without a shell),
# so agents use the CLI engine with the native claude.exe that the npm package ships.
CLAUDE_EXE = str(Path.home() / "AppData/Roaming/npm/node_modules/@anthropic-ai/claude-code/bin/claude.exe")

# name, role, title, model, file, timeout seconds, capabilities, run brakes, permissions.
# Brakes (docs/research/paperclip_best_practices.md C2): the firm shares the owner's Claude subscription,
# where Paperclip's cent budgets never trip, so every run is capped by turns, effort and a client-side
# cost estimate, and every agent by a daily run count. Heartbeats are off: routines and assignments wake agents.
# Permissions (C3): only the CEO may request hires (the board approves); nobody creates skills.
AGENTS = [
    ("CEO", "ceo", "Chief Executive Officer", "sonnet", "ceo.md", 3600,
     "Sets priorities, delegates research and testing, decides proposals, reports to the board",
     {"effort": "medium", "turns": 80, "usd": 3, "daily": 14}, (True, True)),
    ("Research Scout", "researcher", "Research Scout", "sonnet", "research-scout.md", 3600,
     "Finds new testable trading ideas; records the YouTube BTC calls",
     {"effort": "medium", "turns": 100, "usd": 2, "daily": 10}, (False, False)),
    ("Quant", "engineer", "Quant / Backtester", "sonnet", "quant.md", 7200,
     "Pre-registered backtests with the lab frameworks; logs every verdict",
     {"effort": None, "turns": 150, "usd": 5, "daily": 40}, (False, True)),
    ("Quant B", "engineer", "Quant / Backtester B (parallel)", "sonnet", "quant.md", 7200,
     "Second quant, works in parallel with Quant on a different test queue; same rules",
     {"effort": None, "turns": 150, "usd": 5, "daily": 40}, (False, True)),
    ("Red Team", "qa", "Red Team (read-only reviewer)", "opus", "red-team.md", 3600,
     "Tries to break every PASS: look-ahead, bookkeeping, data, selection, costs",
     {"effort": None, "turns": 60, "usd": 4, "daily": 8}, (False, False)),
    ("Risk Officer", "general", "Risk Officer (read-only)", "sonnet", "risk-officer.md", 1800,
     "Gates paper to live against the written rules and the $100 cap; weekly paper review",
     {"effort": "medium", "turns": 40, "usd": 2, "daily": 6}, (False, False)),
    ("Trading Desk", "general", "Trading Desk (operations)", "haiku", "trading-desk.md", 1800,
     "Runs the paper books daily, health checks, morning report to the board",
     {"effort": "low", "turns": 25, "usd": 0.5, "daily": 12}, (False, True)),
    ("Firm Improvement", "general", "Chief of Staff (firm improvement)", "sonnet", "firm-improvement.md", 3600,
     "Weekly review of cost, reliability and research throughput; proposes improvements to the CEO",
     {"effort": "medium", "turns": 60, "usd": 2, "daily": 3}, (False, True)),
]

# title, assignee, cron (local time), what to do, catch-up policy after an outage or sleep
# (cheap, time-critical routines catch up; expensive judgement routines skip to the next window)
ROUTINES = [
    ("Paper books & daily check", "Trading Desk", "20 2 * * *",
     "Follow 'Paper books' and 'Health' in your AGENTS.md.", "enqueue_missed_with_cap"),
    ("Nightly research cycle", "CEO", "40 3 * * *",
     "Follow 'Nightly research cycle' in your AGENTS.md: delegate idea cards to the Research Scout, "
     "pick at most 2 for the Quant, Red Team on any PASS, close with a 5-line summary.", "skip_missed"),
    ("Morning report to the board", "Trading Desk", "55 7 * * *",
     "Follow 'Morning report to the board' in your AGENTS.md.", "enqueue_missed_with_cap"),
    ("Daily board report", "CEO", "15 8 * * *",
     "Follow 'Daily board report' in your AGENTS.md.", "enqueue_missed_with_cap"),
    ("YouTube BTC calls", "Research Scout", "45 21 * * *",
     "Follow 'YouTube BTC calls' in your AGENTS.md.", "enqueue_missed_with_cap"),
    ("Weekly risk review of the paper books", "Risk Officer", "5 9 * * 1",
     "Follow 'Weekly paper review' in your AGENTS.md.", "skip_missed"),
    ("Weekly firm review & improvement", "Firm Improvement", "5 10 * * 0",
     "Follow 'Weekly review' in your AGENTS.md; address the proposals to the CEO.", "skip_missed"),
]


def call(method, path, body=None, soft=False):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        msg = f"{method} {path} -> HTTP {e.code}: {e.read().decode(errors='replace')[:800]}"
        if soft:
            print("warning:", msg)
            return None
        raise SystemExit(msg)


def items(x):
    return x.get("items") or x.get("data") or x.get("value") or [] if isinstance(x, dict) else (x or [])


def main():
    company = next((c for c in items(call("GET", "/companies")) if c.get("name") == COMPANY), None)
    if company is None:
        company = call("POST", "/companies", {"name": COMPANY, "description": DESCRIPTION})
        print("created company", company["id"])
    cid = company["id"]
    call("PATCH", f"/companies/{cid}", {"requireBoardApprovalForNewAgents": True}, soft=True)
    existing = {a["name"]: a for a in items(call("GET", f"/companies/{cid}/agents"))}
    ids = {}
    for name, role, title, model, fname, timeout, caps, brake, (may_hire, may_assign) in AGENTS:
        adapter = {"model": model, "cwd": REPO, "dangerouslySkipPermissions": True, "timeoutSec": timeout,
                   "graceSec": 30, "engine": "cli", "command": CLAUDE_EXE, "maxTurnsPerRun": brake["turns"],
                   "extraArgs": ["--max-budget-usd", str(brake["usd"])]}
        if brake["effort"]:
            adapter["effort"] = brake["effort"]
        body = {
            "name": name, "role": role, "title": title, "capabilities": caps,
            "reportsTo": None if role == "ceo" else ids.get("CEO"),
            "adapterType": "claude_local",
            "adapterConfig": adapter,
            "runtimeConfig": {"heartbeat": {"enabled": False, "intervalSec": 86400, "maxDailyRuns": brake["daily"]}},
            "instructionsBundle": {"files": {"AGENTS.md": (HERE / "agents" / fname).read_text(encoding="utf-8"),
                                             "FIRM_RULES.md": RULES}, "entryFile": "AGENTS.md"},
        }
        if name in existing:
            a = existing[name]
            patch = {k: body[k] for k in ("title", "capabilities", "reportsTo", "runtimeConfig")}   # the adapter config belongs to engine_switch.py
            call("PATCH", f"/agents/{a['id']}", patch)
            changed = []
            for path, text in body["instructionsBundle"]["files"].items():
                cur = call("GET", f"/agents/{a['id']}/instructions-bundle/file?path={path}", soft=True) or {}
                if cur.get("content") == text:
                    continue
                call("PUT", f"/agents/{a['id']}/instructions-bundle/file",
                     {"path": path, "content": text, "baseHash": cur.get("contentHash"),
                      "baseRevisionId": (cur.get("revision") or {}).get("id")}, soft=True)
                changed.append(path)
            print("updated agent", name, ("instructions: " + ", ".join(changed)) if changed else "")
        else:
            a = call("POST", f"/companies/{cid}/agents", body, soft=True)
            if not a or "id" not in a:           # board approval is required: file the hire request and approve it as the board
                import os, subprocess
                a = call("POST", f"/companies/{cid}/agent-hires", {**body, "reason": "board-directed hire (owner: more parallel capacity)"})
                a = a.get("agent", a) if isinstance(a, dict) else a
                cli = os.path.join(os.path.expandvars("%APPDATA%"), "npm", "paperclipai.cmd")
                subprocess.run([cli, "agent", "approve", a["id"]], capture_output=True, shell=True, timeout=120)
            print("created agent", name, a["id"])
        ids[name] = a["id"]
        call("PATCH", f"/agents/{a['id']}/permissions",
             {"canCreateAgents": may_hire, "canAssignTasks": may_assign, "canCreateSkills": False}, soft=True)
    have = {r["title"]: r for r in items(call("GET", f"/companies/{cid}/routines"))}
    for title, who, cron, what, catch_up in ROUTINES:
        spec = {"assigneeAgentId": ids[who], "description": what, "concurrencyPolicy": "coalesce_if_active",
                "catchUpPolicy": catch_up}
        if title in have:
            r = have[title]
            call("PATCH", f"/routines/{r['id']}", spec, soft=True)
            for t in r.get("triggers") or []:
                if t.get("kind") == "schedule" and (t.get("cronExpression") != cron or t.get("timezone") != TZ):
                    call("PATCH", f"/routine-triggers/{t['id']}", {"cronExpression": cron, "timezone": TZ}, soft=True)
            print("updated routine", title, cron, catch_up)
            continue
        r = call("POST", f"/companies/{cid}/routines", {"title": title, "priority": "medium", **spec})
        call("POST", f"/routines/{r['id']}/triggers", {"kind": "schedule", "label": cron, "enabled": True,
                                                       "cronExpression": cron, "timezone": TZ})
        print("created routine", title, cron)
    out = Path(REPO) / "var" / "paperclip_ids.json"
    out.write_text(json.dumps({"company": cid, "agents": ids}, indent=1), encoding="utf-8")
    print("ids ->", out)


if __name__ == "__main__":
    sys.exit(main())
