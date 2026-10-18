"""One-off: method learning (owner, 2026-10-18). Updates rules/instructions/sources and files the three tasks."""
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

g = ROOT / "pionex_lab/swing/guidance.py"
t = g.read_text(encoding="utf-8")
t = t.replace('SOURCES = ("More Crypto Online", "Daily Entry", "Chart Hackers", "Owner")',
              'SOURCES = ("More Crypto Online", "Daily Entry", "Chart Hackers", "Owner", "Crypto Banter", "Crypto Decoded", "Firm")')
g.write_text(t, encoding="utf-8")

s = ROOT / "paperclip/agents/research-scout.md"
u = s.read_text(encoding="utf-8")
if "Method learning" not in u:
    u += """
## Method learning (owner, 2026-10-18): learn HOW the analysts read the market, not only their entries
Channels: ChartHackersGroup, CryptoBanterGroup, DailyEntry, morecryptoonline, cryptodecodedgroup (all five; Crypto Banter and
Crypto Decoded are also in the daily YouTube routine now, as sources "Crypto Banter" and "Crypto Decoded").
The owner's own process: listen to what they say and USE (anchored VWAPs from the low and from the high, support/resistance,
order-block size and volume, Elliott waves, oscillator, liquidation heatmap, news), look at the same on the Pionex/Wave Lab/
TradingView charts, and make his OWN decision. Transcripts alone are not enough: take frames of the charts at the timestamps
where they discuss levels (yt-dlp downloads into var/youtube/<id>/, ffmpeg frame grabs; look at the images with your vision) and
write, per analyst, a method card research/owner_method/<analyst>.md: indicators and settings, how they draw and rank levels, how
they size order blocks, AVWAP anchors, entry/exit/invalidations, what they ignore; plus an append-only claims table
research/owner_method/claims.jsonl (video, timestamp, date, level or zone, direction, technique, claim). Mark each item as
'said' or 'seen on chart'. The Quant verifies the claims on Pionex data.
"""
    s.write_text(u, encoding="utf-8")

f = ROOT / "paperclip/FIRM_RULES.md"
r = f.read_text(encoding="utf-8")
if "Method learning and own market read" not in r:
    add = """## Method learning and own market read (owner, 2026-10-18)
We do what the owner does: learn the analysts' TECHNIQUES (not copy their entries), verify every technique on Pionex data, then
form our OWN daily read of BTC (support/resistance, AVWAP from the swing low and high, order blocks with size and volume, Elliott
and the WL oscillator from Wave Lab's own Python mirror, liquidation heatmap, news) and score it forward as source "Firm" next to
the analysts and the owner. A technique enters a strategy only if the verification shows it works.

"""
    r = r.replace("## Own the problem", add + "## Own the problem")
    f.write_text(r, encoding="utf-8")

ids = json.loads((ROOT / "var/paperclip_ids.json").read_text(encoding="utf-8"))
cid, ag = ids["company"], ids["agents"]


def call(method, path, body=None):
    req = urllib.request.Request("http://127.0.0.1:3100/api" + path, data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=180))


def issue(title, who, desc):
    x = call("POST", f"/companies/{cid}/issues", {"title": title, "description": desc, "priority": "critical",
                                                    "status": "todo", "assigneeAgentId": ag[who]})
    print(x["identifier"], title[:70])


issue("Method cards from all 5 analyst channels: techniques, chart frames, claims table (not just entries)", "Research Scout",
      "Owner (2026-10-18): the analysts are where he learned his method. Channels: youtube.com/@ChartHackersGroup, @CryptoBanterGroup, "
      "@DailyEntry, @morecryptoonline, @cryptodecodedgroup. For the latest 30 BTC videos per channel (60 for Daily Entry and Chart "
      "Hackers): transcript (yt-dlp subtitles; if 429, the YouTube transcript panel via a browser tool or curl_cffi in var/tools/site), "
      "chapters, and chart frames (yt-dlp video download into var/youtube/<id>/, ffmpeg frame grabs at the timestamps where they discuss "
      "levels; READ the frames with your vision). Output research/owner_method/<analyst>.md and research/owner_method/claims.jsonl (see "
      "your AGENTS.md 'Method learning'). Also list EVERY indicator and setting visible on their charts (AVWAP anchors from low/high, "
      "volume profile, order-block drawings, Elliott labels, oscillators). Free tools only. Mark each item 'said' or 'seen on chart'. Hand "
      "the claims file to the Quant B verifier when 200+ claims exist and keep adding afterwards.")
issue("Verify the analysts' techniques on Pionex data: which levels and indicators actually work (claims verifier)", "Quant B",
      "Owner (2026-10-18): learn what the analysts USE and verify it. Input: research/owner_method/claims.jsonl (the Scout builds it; "
      "start from the calls in var/guidance and the transcripts in var/tools/subs, build the first 100 claims yourself if it is empty). "
      "For each claim compute, point-in-time from Pionex klines (BTC, proxies labelled), the firm's own version of the technique: AVWAP "
      "from the last swing low/high, support/resistance from swing points and volume profile, order block (last opposite candle before "
      "an impulsive move, with size and volume), Elliott count (pionex_lab/waves/elliott.py and the WL oscillator mirror "
      "pionex_lab/waves/oscillator.py), and the liquidation heatmap (Wave Lab model). Measure: does the stated level coincide with our "
      "computed level; does price touch, respect or break it; forward returns and MAE/MFE after touches; hit rate vs random levels at the "
      "same distance; by analyst and by technique. Pre-register definitions and thresholds first, apply the luck suite (CLO-44), log in "
      "docs/STRATEGY_LOG.md. Output the ranked list of techniques that survive, with settings; they feed the owner-method strategy (CLO-64).")
issue("Daily OWN market read for BTC (source 'Firm'): levels, AVWAP, order blocks, EW/oscillator, heatmap, news, bias, invalidation", "Quant",
      "Owner (2026-10-18): do what the owner does and decide for yourself. Build pionex_lab/read/own_read.py (+ tests, + a routine "
      "'Firm market read' at 06:30 SAST in setup_company ROUTINES, run by the Trading Desk): from FRESH Pionex data compute BTC "
      "support/resistance, AVWAP from the last swing low and high, order blocks (size, volume), volume profile, the Elliott count and WL "
      "oscillator state (reuse pionex_lab/waves), the liquidation-heatmap clusters (Wave Lab model) and the news calendar, and produce a "
      "read: bias (LONG/SHORT/NEUTRAL), long/short zones, triggers, targets, invalidation, reasons, confidence. Record it with "
      "`py -m pionex_lab guidance --add` as source 'Firm' so it is scored forward like the analysts and the owner. Compare daily with the "
      "analysts' reads (agree/disagree) in docs/status/market-read-<date>.md. Only techniques that passed the claims verifier get weight.")
print("done")
