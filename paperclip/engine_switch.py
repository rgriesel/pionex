"""Two-way Claude <-> Codex failover for the Paperclip agents (run every 5 minutes by the watchdog).

Everything runs on Codex by default (owner's choice). When the OpenAI 5-hour or weekly window reaches HIGH, the
agents move to Claude; when it falls back below LOW they move back. If Claude itself reports a limit while an
agent is on it, that agent returns to Codex and Claude is not used for 5 hours. Only the engine changes; the
instructions, permissions, run brakes and every firm rule stay the same. Agents run with full access to this PC
(no sandbox). The Trading Desk always stays on Codex (cheap model). Local loopback API only, no keys.
State: var/engine_state.json.
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
HIGH, LOW = 90, 60
MIN_DWELL = 25 * 60
KEEP_ON_CODEX = {"Trading Desk"}


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


def openai_usage(cid):
    for prov in call("GET", f"/companies/{cid}/costs/quota-windows"):
        if prov.get("provider") == "openai" and prov.get("ok"):
            vals = [w.get("usedPercent") for w in prov.get("windows", []) if w.get("usedPercent") is not None]
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
    claude_ids = {x for x in []}
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


def claude_config(sc, name):
    for n, role, title, model, fname, timeout, caps, brake, perms in sc.AGENTS:
        if n == name:
            cfg = {"model": model, "cwd": sc.REPO, "dangerouslySkipPermissions": True, "timeoutSec": timeout, "graceSec": 30,
                   "engine": "cli", "command": sc.CLAUDE_EXE, "maxTurnsPerRun": brake["turns"],
                   "extraArgs": ["--max-budget-usd", str(brake["usd"])]}
            if brake["effort"]:
                cfg["effort"] = brake["effort"]
            return cfg
    raise KeyError(name)


def main():
    ids = json.loads((ROOT / "var" / "paperclip_ids.json").read_text(encoding="utf-8"))
    cid, state_path = ids["company"], ROOT / "var" / "engine_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    state.setdefault("saved_codex", {})
    state.setdefault("since", {})
    state.setdefault("claude_blocked_until", 0)
    sc = setup_module()
    use = openai_usage(cid)
    now = time.time()
    claude_ok = now > state["claude_blocked_until"]
    changed = []
    for name, aid in ids["agents"].items():
        if name in KEEP_ON_CODEX:
            continue
        agent = call("GET", f"/agents/{aid}")
        on = agent["adapterType"]
        dwell = now - state["since"].get(name, 0)
        if on == "codex_local" and use is not None and use >= HIGH and claude_ok and dwell > MIN_DWELL:
            state["saved_codex"][name] = {k: v for k, v in agent["adapterConfig"].items() if k != "env"}
            call("PATCH", f"/agents/{aid}", {"adapterType": "claude_local", "replaceAdapterConfig": True,
                                              "adapterConfig": claude_config(sc, name)})
            state["since"][name] = now
            changed.append(f"{name}: openai {use}% -> claude")
        elif on == "claude_local" and name in state["saved_codex"] and dwell > MIN_DWELL and (
                (use is not None and use <= LOW) or claude_limit_hit(cid)):
            if claude_limit_hit(cid):
                state["claude_blocked_until"] = now + 5 * 3600
            call("PATCH", f"/agents/{aid}", {"adapterType": "codex_local", "replaceAdapterConfig": True,
                                              "adapterConfig": state["saved_codex"][name]})
            state["since"][name] = now
            changed.append(f"{name}: back to codex")
    state_path.write_text(json.dumps(state, indent=1), encoding="utf-8")
    print("; ".join(changed) if changed else f"no change (openai {use}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
