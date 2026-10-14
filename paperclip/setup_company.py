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

# name, role, title, model, file, heartbeat seconds (0 = off), timeout seconds, capabilities
AGENTS = [
    ("CEO", "ceo", "Chief Executive Officer", "opus", "ceo.md", 28800, 3600,
     "Sets priorities, delegates research and testing, decides proposals, reports to the board"),
    ("Research Scout", "researcher", "Research Scout", "sonnet", "research-scout.md", 0, 3600,
     "Finds new testable trading ideas; records the YouTube BTC calls"),
    ("Quant", "engineer", "Quant / Backtester", "sonnet", "quant.md", 0, 7200,
     "Pre-registered backtests with the lab frameworks; logs every verdict"),
    ("Red Team", "qa", "Red Team (read-only reviewer)", "opus", "red-team.md", 0, 3600,
     "Tries to break every PASS: look-ahead, bookkeeping, data, selection, costs"),
    ("Risk Officer", "general", "Risk Officer (read-only)", "opus", "risk-officer.md", 0, 1800,
     "Gates paper to live against the written rules and the $100 cap; weekly paper review"),
    ("Trading Desk", "general", "Trading Desk (operations)", "haiku", "trading-desk.md", 0, 1800,
     "Runs the paper books daily, health checks, morning report to the board"),
    ("Firm Improvement", "general", "Chief of Staff (firm improvement)", "sonnet", "firm-improvement.md", 0, 3600,
     "Weekly review of cost, reliability and research throughput; proposes improvements to the CEO"),
]

# title, assignee, cron (local time), what to do
ROUTINES = [
    ("Paper books & daily check", "Trading Desk", "20 2 * * *",
     "Follow 'Paper books' and 'Health' in your AGENTS.md."),
    ("Nightly research cycle", "CEO", "40 3 * * *",
     "Follow 'Nightly research cycle' in your AGENTS.md: delegate idea cards to the Research Scout, "
     "pick at most 2 for the Quant, Red Team on any PASS, close with a 5-line summary."),
    ("Morning report to the board", "Trading Desk", "55 7 * * *",
     "Follow 'Morning report to the board' in your AGENTS.md."),
    ("YouTube BTC calls", "Research Scout", "45 21 * * *",
     "Follow 'YouTube BTC calls' in your AGENTS.md."),
    ("Weekly risk review of the paper books", "Risk Officer", "5 9 * * 1",
     "Follow 'Weekly paper review' in your AGENTS.md."),
    ("Weekly firm review & improvement", "Firm Improvement", "5 10 * * 0",
     "Follow 'Weekly review' in your AGENTS.md; address the proposals to the CEO."),
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
    existing = {a["name"]: a for a in items(call("GET", f"/companies/{cid}/agents"))}
    ids = {}
    for name, role, title, model, fname, hb, timeout, caps in AGENTS:
        body = {
            "name": name, "role": role, "title": title, "capabilities": caps,
            "reportsTo": None if role == "ceo" else ids.get("CEO"),
            "adapterType": "claude_local",
            "adapterConfig": {"model": model, "cwd": REPO, "dangerouslySkipPermissions": True,
                              "timeoutSec": timeout, "graceSec": 30, "engine": "cli", "command": CLAUDE_EXE},
            "runtimeConfig": {"heartbeat": {"enabled": hb > 0, "intervalSec": hb or 86400}},
            "instructionsBundle": {"files": {"AGENTS.md": (HERE / "agents" / fname).read_text(encoding="utf-8"),
                                             "FIRM_RULES.md": RULES}, "entryFile": "AGENTS.md"},
        }
        if name in existing:
            a = existing[name]
            patch = {k: body[k] for k in ("title", "capabilities", "reportsTo", "adapterConfig", "runtimeConfig")}
            call("PATCH", f"/agents/{a['id']}", patch)
            for path, text in body["instructionsBundle"]["files"].items():
                call("PUT", f"/agents/{a['id']}/instructions-bundle/file",
                     {"path": path, "content": text}, soft=True)
            print("updated agent", name)
        else:
            a = call("POST", f"/companies/{cid}/agents", body)
            print("created agent", name, a["id"])
        ids[name] = a["id"]
    have = {r["title"]: r for r in items(call("GET", f"/companies/{cid}/routines"))}
    for title, who, cron, what in ROUTINES:
        if title in have:
            print("routine exists", title)
            continue
        r = call("POST", f"/companies/{cid}/routines", {
            "title": title, "assigneeAgentId": ids[who], "description": what, "priority": "medium",
            "concurrencyPolicy": "coalesce_if_active", "catchUpPolicy": "enqueue_missed_with_cap"})
        call("POST", f"/routines/{r['id']}/triggers", {"kind": "schedule", "label": cron, "enabled": True,
                                                       "cronExpression": cron, "timezone": TZ})
        print("created routine", title, cron)
    out = Path(REPO) / "var" / "paperclip_ids.json"
    out.write_text(json.dumps({"company": cid, "agents": ids}, indent=1), encoding="utf-8")
    print("ids ->", out)


if __name__ == "__main__":
    sys.exit(main())
