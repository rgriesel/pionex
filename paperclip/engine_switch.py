"""The ONE engine controller for the Paperclip agents (run every 5 minutes by the watchdog).

Both token pools work in parallel (owner, 2026-10-18): every agent has a HOME engine, split so Claude and Codex
burn at the same time. When an agent's home pool is exhausted it runs on the other pool, and returns home when
the pool is back. Codex agents run with full access (no sandbox). The controller also repairs any agent whose
adapter, command and model do not match (a half-switched config makes every run fail). It replaces the earlier
"Paperclip OpenAI Fallback" task, which is disabled. Local loopback API only, no keys. State: var/engine_state.json
"""
from __future__ import annotations

import calendar
import importlib.util
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:3100/api"
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CODEX_HIGH, CODEX_LOW = 90, 60
MIN_DWELL = 20 * 60
CODEX_EXE = str(Path.home() / "AppData/Roaming/npm/node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe")
# name: (home engine, codex model, codex effort)
PLAN = {
    "CEO": ("claude", "gpt-6-astra", "medium"),
    "Red Team": ("claude", "gpt-6-astra", "high"),
    "Risk Officer": ("claude", "gpt-6-astra", "medium"),
    "Quant B": ("claude", "gpt-6.1-sol", "medium"),
    "Quant": ("codex", "gpt-6.1-sol", "medium"),
    "Research Scout": ("codex", "gpt-6.1-sol", "low"),
    "Firm Improvement": ("codex", "gpt-6-luna", "medium"),
    "Trading Desk": ("codex", "gpt-6-luna", "low"),
}
BOOTSTRAP = ("Codex agent on the owner's PC with FULL access (no sandbox): Python via `py`, the network, the file system and the "
             "Paperclip API at http://127.0.0.1:3100. Scope: research, building and testing code, data collection, forward/shadow "
             "trading analysis. You never place, alter, cancel, enable or fund live orders or bots, never edit the mandate, its lock "
             "or risk limits, and never read key files or print secrets: the live program does the trading, and only the program "
             "flips live. Follow FIRM_RULES.md; for the quota check use the OpenAI windows. Send owner Telegram notices with "
             "`py -m pionex_lab notify` as the rules say. Never end a run without setting the issue status (done, or backlog with the "
             "dependency named; never blocked); if a Paperclip API call fails, retry 3 times, then write the result to docs/status/ "
             "and leave the issue todo.")


def call(method, path, body=None):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read() or "null")


def setup_module():
    spec = importlib.util.spec_from_file_location("setup_company", HERE / "setup_company.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def codex_used(cid):
    for prov in call("GET", f"/companies/{cid}/costs/quota-windows"):
        if prov.get("provider") == "openai" and prov.get("ok"):
            vals = [w.get("usedPercent") for w in (prov.get("windows") or []) if w and w.get("usedPercent") is not None]
            return max(vals) if vals else None
    return None


def claude_limit_hit(cid, minutes=300):
    cli = os.path.join(os.path.expandvars("%APPDATA%"), "npm", "paperclipai.cmd")
    r = subprocess.run([cli, "run", "list", "--company-id", cid, "--json"], capture_output=True, shell=True, timeout=120)
    try:
        runs = json.loads(r.stdout.decode("utf-8", "replace"))
    except ValueError:
        return False
    runs = runs if isinstance(runs, list) else runs.get("items", [])
    now = time.time()
    for x in runs[:40]:
        err = (x.get("error") or "").lower()
        if x.get("status") == "failed" and "claude" in err and ("limit" in err or "hit your" in err):
            try:
                if now - calendar.timegm(time.strptime(x["createdAt"][:19], "%Y-%m-%dT%H:%M:%S")) < minutes * 60:
                    return True
            except (KeyError, ValueError):
                continue
    return False


def claude_cfg(sc, name):
    for n, role, title, model, fname, timeout, caps, brake, perms in sc.AGENTS:
        if n == name:
            cfg = {"model": model, "cwd": sc.REPO, "dangerouslySkipPermissions": True, "timeoutSec": timeout, "graceSec": 30,
                   "engine": "cli", "command": sc.CLAUDE_EXE, "maxTurnsPerRun": brake["turns"],
                   "extraArgs": ["--max-budget-usd", str(brake["usd"])]}
            if brake["effort"]:
                cfg["effort"] = brake["effort"]
            return cfg
    raise KeyError(name)


def codex_cfg(sc, name):
    _, model, effort = PLAN[name]
    timeout = next((a[5] for a in sc.AGENTS if a[0] == name), 3600)
    cfg = {"engine": "cli", "command": CODEX_EXE, "model": model, "modelReasoningEffort": effort, "cwd": sc.REPO,
           "dangerouslyBypassApprovalsAndSandbox": True, "timeoutSec": timeout, "graceSec": 30,
           "bootstrapPromptTemplate": BOOTSTRAP}
    if name == "Research Scout":
        cfg["search"] = True
    return cfg


def main():
    ids = json.loads((ROOT / "var" / "paperclip_ids.json").read_text(encoding="utf-8"))
    cid, sp = ids["company"], ROOT / "var" / "engine_state.json"
    st = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    st.setdefault("since", {})
    st.setdefault("claude_blocked_until", 0)
    sc = setup_module()
    cu = codex_used(cid)
    now = time.time()
    if claude_limit_hit(cid):
        st["claude_blocked_until"] = now + 5 * 3600
    claude_ok = now > st["claude_blocked_until"]
    codex_ok = cu is None or cu < CODEX_HIGH
    codex_back = cu is None or cu <= CODEX_LOW
    log = []
    for name, aid in ids["agents"].items():
        if name not in PLAN:
            continue
        home = PLAN[name][0]
        agent = call("GET", f"/agents/{aid}")
        if agent.get("status") == "running":
            continue                                       # never switch under a running task
        cur = "codex" if agent["adapterType"] == "codex_local" else "claude"
        dwell = now - st["since"].get(name, 0)
        target = cur
        if cur == home:
            pool_ok = codex_ok if home == "codex" else claude_ok
            other_ok = claude_ok if home == "codex" else codex_ok
            if not pool_ok and other_ok and dwell > MIN_DWELL:
                target = "claude" if home == "codex" else "codex"
        else:
            home_ok = codex_back if home == "codex" else claude_ok
            other_ok = claude_ok if cur == "claude" else codex_ok
            if (home_ok or not other_ok) and dwell > MIN_DWELL:
                target = home
        cfg = codex_cfg(sc, name) if target == "codex" else claude_cfg(sc, name)
        c = agent["adapterConfig"]
        mismatch = (agent["adapterType"] != ("codex_local" if target == "codex" else "claude_local")
                    or c.get("model") != cfg["model"] or c.get("command") != cfg["command"]
                    or bool(c.get("dangerouslyBypassApprovalsAndSandbox")) != bool(cfg.get("dangerouslyBypassApprovalsAndSandbox")))
        if target != cur or mismatch:
            call("PATCH", f"/agents/{aid}", {"adapterType": "codex_local" if target == "codex" else "claude_local",
                                              "replaceAdapterConfig": True, "adapterConfig": cfg})
            if target != cur:
                st["since"][name] = now
            log.append(f"{name}: {cur}->{target}" + (" (repaired config)" if mismatch and target == cur else ""))
    sp.write_text(json.dumps(st, indent=1), encoding="utf-8")
    print("; ".join(log) if log else f"no change (codex {cu}%, claude_ok={claude_ok})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
