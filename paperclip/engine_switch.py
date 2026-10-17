"""Claude <-> Codex fallback for the Paperclip agents (run every 5 minutes by the watchdog).

When Claude usage (session or week) reaches HIGH, the agents in SWITCHABLE move to codex_local; when it falls
below LOW (the limit has reset) they move back to their saved Claude config. Only the engine changes: the
instructions, run brakes, permissions and every firm rule stay the same. If the Anthropic usage endpoint
errors (it rate-limits), nothing changes. State: var/engine_state.json. Local loopback API only, no keys.
"""
from __future__ import annotations

import calendar
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:3100/api"
ROOT = Path(__file__).resolve().parent.parent
HIGH, LOW = 90, 60
CODEX_EXE = str(Path.home() / "AppData/Roaming/npm/node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe")
CODEX_MODEL = {"Quant": "gpt-5.6-sol", "CEO": "gpt-5.6-sol"}      # the agents we move when Claude runs out
SWITCHABLE = tuple(CODEX_MODEL)
ALWAYS_CODEX = {"Trading Desk": "gpt-5.6-luna"}                    # bulk workers that live on Codex permanently


def call(method, path, body=None):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or "null")


def claude_usage(cid):
    for prov in call("GET", f"/companies/{cid}/costs/quota-windows"):
        if prov.get("provider") == "anthropic" and prov.get("ok"):
            return max((w.get("usedPercent") or 0) for w in prov.get("windows", []) if w.get("label", "").startswith(("Current session", "Current week")))
    return None


def limit_hit_recently(cid, minutes=45):
    """True if a Claude run failed with a session/weekly limit message in the last `minutes` minutes."""
    cli = os.path.join(os.path.expandvars("%APPDATA%"), "npm", "paperclipai.cmd")
    r = subprocess.run([cli, "run", "list", "--company-id", cid, "--json"], capture_output=True, text=True, shell=True)
    try:
        runs = json.loads(r.stdout)
    except ValueError:
        return False
    runs = runs if isinstance(runs, list) else runs.get("items", [])
    now = time.time()
    for x in runs[:30]:
        err = (x.get("error") or "").lower()
        if x.get("status") == "failed" and ("session limit" in err or "weekly limit" in err or "hit your" in err):
            ts = x.get("createdAt", "")
            try:
                age = now - calendar.timegm(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))   # createdAt is UTC
            except ValueError:
                continue
            if age < minutes * 60:
                return True
    return False


def codex_config(agent, model):
    c = agent["adapterConfig"]
    return {"engine": "cli", "command": CODEX_EXE, "model": model, "modelReasoningEffort": "medium",
            "cwd": c.get("cwd"), "dangerouslyBypassApprovalsAndSandbox": True,
            "timeoutSec": c.get("timeoutSec", 3600), "graceSec": 30}


def main():
    ids = json.loads((ROOT / "var" / "paperclip_ids.json").read_text(encoding="utf-8"))
    cid, state_path = ids["company"], ROOT / "var" / "engine_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"on_codex": {}}
    use = claude_usage(cid)
    if use is None:                                   # usage endpoint rate-limited: use run failures instead
        use = 100 if limit_hit_recently(cid) else None
    if use is None:
        for name in SWITCHABLE:                       # no signal: go back after 5 h on Codex (a session window)
            since = state.get("since", {}).get(name)
            aid = ids["agents"][name]
            if since and time.time() - since > 5 * 3600 and name in state["on_codex"]:
                call("PATCH", f"/agents/{aid}", {"adapterType": "claude_local", "replaceAdapterConfig": True,
                                                  "adapterConfig": state["on_codex"].pop(name)})
                state["since"].pop(name, None)
                print(f"{name}: 5 h on codex, no usage signal -> back to claude")
        state_path.write_text(json.dumps(state, indent=1), encoding="utf-8")
        print("claude usage unavailable; no change" if not state["on_codex"] else "on codex until reset")
        return 0
    for name in SWITCHABLE:
        aid = ids["agents"][name]
        agent = call("GET", f"/agents/{aid}")
        if use >= HIGH and agent["adapterType"] == "claude_local":
            state["on_codex"][name] = agent["adapterConfig"]                      # remember the way back
            state.setdefault("since", {})[name] = time.time()
            call("PATCH", f"/agents/{aid}", {"adapterType": "codex_local", "replaceAdapterConfig": True,
                                              "adapterConfig": codex_config(agent, CODEX_MODEL[name])})
            print(f"{name}: claude {use}% >= {HIGH}% -> codex")
        elif use <= LOW and agent["adapterType"] == "codex_local" and name in state["on_codex"]:
            call("PATCH", f"/agents/{aid}", {"adapterType": "claude_local", "replaceAdapterConfig": True,
                                              "adapterConfig": state["on_codex"].pop(name)})
            print(f"{name}: claude {use}% <= {LOW}% -> back to claude")
    state_path.write_text(json.dumps(state, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
