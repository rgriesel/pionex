"""Self-healing for the Paperclip firm (run every 5 minutes by the watchdog; rate-limited inside).

Plain code, no agent: finds issues that were parked "blocked" because of infrastructure trouble (the run ended
without a disposition, retry budget spent, quota skip, daily cap, empty wake) and puts them back in the queue
with a fresh wake, with back-off and a cap of MAX_REQUEUES per issue so nothing loops forever. Issues that wait
on a real dependency (another issue, the owner) are left alone. Local loopback API only, no keys.
State: var/selfheal_state.json.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
import urllib.request

API = "http://127.0.0.1:3100/api"
ROOT = Path(__file__).resolve().parent.parent
MAX_REQUEUES = 4
COOLDOWN = 20 * 60
INFRA = ("exhausted", "retried this issue", "missing remote disposition", "no live execution path", "quota",
         "daily", "heartbeat budget", "wakeup", "lost wake", "no durable", "unchanged_source_state")
OWNER_OR_DEPENDENT = ("owner", "board action", "your action", "blocked on clo-", "first-class blocker", "prohibited for agents")


def call(method, path, body=None):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read() or "null")


def main():
    ids = json.loads((ROOT / "var" / "paperclip_ids.json").read_text(encoding="utf-8"))
    cid, sp = ids["company"], ROOT / "var" / "selfheal_state.json"
    st = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    now, out = time.time(), []
    cli = os.path.join(os.path.expandvars("%APPDATA%"), "npm", "paperclipai.cmd")
    for i in call("GET", f"/companies/{cid}/issues"):
        if i["status"] != "blocked" or not i.get("assigneeAgentId"):
            continue
        rec = st.get(i["identifier"], {"n": 0, "at": 0})
        if rec["n"] >= MAX_REQUEUES or now - rec["at"] < COOLDOWN * (rec["n"] + 1):
            continue
        cm = call("GET", f"/issues/{i['id']}/comments")
        text = " ".join((c.get("body") or "") for c in cm[:2]).lower() + " " + (i.get("description") or "").lower()[:200]
        if not any(k in text for k in INFRA) or any(k in text for k in OWNER_OR_DEPENDENT):
            continue
        call("POST", f"/issues/{i['id']}/comments", {"body": f"Self-heal: re-queued automatically (attempt {rec['n'] + 1}/{MAX_REQUEUES}). "
                                                       "Finish the work, then set the issue to done, or blocked with the real reason and the owner of it."})
        call("PATCH", f"/issues/{i['id']}", {"status": "todo"})
        subprocess.run([cli, "agent", "wake", i["assigneeAgentId"], "--company-id", cid, "--reason", "self-heal requeue",
                        "--payload", json.dumps({"issueId": i["id"]})], capture_output=True, shell=True, timeout=120)
        st[i["identifier"]] = {"n": rec["n"] + 1, "at": now}
        out.append(i["identifier"])
    sp.write_text(json.dumps(st, indent=1), encoding="utf-8")
    print("requeued: " + ", ".join(out) if out else "nothing to heal")
    return 0


if __name__ == "__main__":
    sys.exit(main())
