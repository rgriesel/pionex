"""One-off final setup (owner, 2026-10-18): permissions, new-videos-only rule, notes. Retries while Paperclip is busy."""
import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ids = json.loads((ROOT / "var/paperclip_ids.json").read_text(encoding="utf-8"))
cid = ids["company"]


def call(method, path, body=None, tries=6):
    for k in range(tries):
        try:
            req = urllib.request.Request("http://127.0.0.1:3100/api" + path, data=json.dumps(body).encode() if body is not None else None,
                                         method=method, headers={"Content-Type": "application/json"})
            return json.load(urllib.request.urlopen(req, timeout=300))
        except urllib.error.HTTPError as e:
            return {"error": e.code, "body": e.read().decode()[:200]}
        except Exception:
            time.sleep(20 * (k + 1))
    return {"error": "unreachable"}


for name, aid in ids["agents"].items():
    r = call("PATCH", f"/agents/{aid}/permissions", {"canCreateAgents": name == "CEO", "canAssignTasks": True,
                                                       "canCreateSkills": name not in ("Red Team", "Risk Officer")})
    print(name, r.get("permissions", r))

s = ROOT / "paperclip/agents/research-scout.md"
u = s.read_text(encoding="utf-8")
if "NEW videos only" not in u:
    u += """
## Video rule (owner, 2026-10-18): NEW videos only, only the coins we trade
Never download or process older videos or backfill. Each day take only videos published since the last run (yt-dlp --dateafter or the
channel's newest uploads), only about the coins we trade (BTC now; add a coin when the firm trades it). Process each video once
(transcript, frames, claims), then DELETE the video file immediately; keep frames, subtitles, method-card updates and claims.
"""
    s.write_text(u, encoding="utf-8")

iss = {i["identifier"]: i for i in call("GET", f"/companies/{cid}/issues") if isinstance(i, dict)}
note = ("Owner instruction (2026-10-18): NEW videos only, never older ones, only the coins we trade (BTC now). Replace the 'latest 30 "
        "videos' scope: build the method cards from the transcripts and frames already collected plus each NEW video going forward "
        "(daily). Delete each video file right after its frames and transcript are extracted. The verifier (CLO-68) uses the claims "
        "that accumulate plus the recorded calls in var/guidance.")
for k in ("CLO-67", "CLO-68"):
    if k in iss:
        call("POST", f"/issues/{iss[k]['id']}/comments", {"body": note})
print("done")
