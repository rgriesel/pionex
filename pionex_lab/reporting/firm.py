"""Read-only "firm" status for the dashboard: paper swing books, agent roles, routines, the strategy
pipeline, and background research processes. It only reads local files and checks local ports; it
writes nothing and has no control actions. Paper results are simulated, not evidence of profit.
"""
from __future__ import annotations

import json
import re
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..util import PROJECT_ROOT

BOOKS = (("state.json", "Defensive · 10 coins"), ("state_growth.json", "Growth · 10 coins (comparison)"),
         ("state_canary.json", "Canary · BTC + ETH (the $100 live shape)"))
PAPER_DAYS_BEFORE_REVIEW = 60
ROUTINES = (  # session schedules (local time); `out` is the file the routine leaves behind, if any
    ("02:17", "Paper swing books + BTC/ETH trend check", "swing_book/state.json"),
    ("02:53", "Nightly paper-lab check", None),
    ("03:37", "Research: scout → quant → red team → strategy log", "docs/STRATEGY_LOG.md"),
    ("07:52", "Morning summary for the owner", None),
    ("21:43", "YouTube BTC calls + guidance scorecard", "reports/btc_guidance.json"),
)
SERVICES = (("Wave Lab", 8770), ("Pionex Trader panel", 8780))


def _iso(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="seconds")


def _age_s(path: Path, now_ms: int):
    try:
        return round(now_ms / 1000 - path.stat().st_mtime)
    except OSError:
        return None


def _books(var: Path) -> list:
    out = []
    for fname, label in BOOKS:
        p = var / "swing_book" / fname
        try:
            st = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        hist = st.get("history", [])
        start_usdt = float(st.get("paper_usdt") or 100.0)
        eq = float(st.get("equity", start_usdt))
        peak, mdd = start_usdt, 0.0
        for h in hist:
            peak = max(peak, h["equity"])
            mdd = max(mdd, 1 - h["equity"] / peak)
        w = st.get("weights", {})
        hold = sorted(w.items(), key=lambda kv: -kv[1])
        out.append({"book": label, "start": st.get("start", ""), "paper_usdt": start_usdt, "equity_usdt": round(eq, 2),
                    "return_pct": round(100 * (eq / start_usdt - 1), 2), "max_drawdown_pct": round(100 * mdd, 2),
                    "paper_days": len(hist), "invested_pct": round(100 * sum(w.values()), 1),
                    "holdings": ", ".join(f"{s.split('_')[0]} {100 * v:.0f}%" for s, v in hold) or "cash",
                    "updated": st.get("updated", "")})
    return out


ORDER = ("research-scout", "quant-backtester", "red-team", "risk-officer", "ops-reporter")


def _agents(root: Path) -> list:
    out = [{"role": "lead (main session)", "model": "opus",
            "does": "Sets priorities, makes the final strategy and settings decisions, commits the code."}]
    found = []
    for p in (root / ".claude" / "agents").glob("*.md"):
        m = re.match(r"---\s*\n(.*?)\n---", p.read_text(encoding="utf-8"), re.S)
        if not m:
            continue
        meta = dict(re.findall(r"^(\w+):\s*(.*)$", m.group(1), re.M))
        sentences = meta.get("description", "").split(". ")
        does = ". ".join(sentences[1:2] or sentences[:1]).rstrip(".") + "."
        found.append({"role": meta.get("name", p.stem), "model": meta.get("model", "inherit"), "does": does[:300]})
    found.sort(key=lambda a: ORDER.index(a["role"]) if a["role"] in ORDER else len(ORDER))
    return out + found


def _pipeline(root: Path) -> dict:
    try:
        text = (root / "docs" / "STRATEGY_LOG.md").read_text(encoding="utf-8")
    except OSError:
        return {"tested": 0, "failed": 0, "candidates": []}
    section, tested, failed, cands = "", 0, 0, []
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].lower()
        elif line.startswith("| 20"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if section.startswith("live candidates"):
                name = re.sub(r"\*\*|`|\(.*?\)", "", cells[1]).split(":")[0].strip()
                cands.append({"strategy": name[:200], "status": re.sub(r"\*\*|`", "", cells[-1])[:400]})
            elif section.startswith("tested"):
                tested += 1
                failed += ("FAIL" in cells[-1] or "REJECTED" in cells[-1])
    return {"tested": tested, "failed": failed, "candidates": cands}


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def firm_status(var: Path, now_ms: int, root: Path = PROJECT_ROOT) -> dict:
    var, root = Path(var), Path(root)
    books = _books(var)
    start = min((b["start"] for b in books if b["start"]), default="")
    review = ((datetime.fromisoformat(start) + timedelta(days=PAPER_DAYS_BEFORE_REVIEW)).date().isoformat()
              if start else "")
    routines = []
    for at, what, out in ROUTINES:
        path = (root / out) if out and out.startswith("docs/") else (var / out) if out else None
        age = _age_s(path, now_ms) if path else None
        routines.append({"at": at, "what": what,
                         "last_output": (_iso(now_ms - age * 1000) if age is not None else "reported in chat")})
    procs = [{"what": "Live order-book recorder (Binance spot depth, every 60 s)",
              "alive": (_age_s(var / "orderbook" / "live.db", now_ms) or 10 ** 9) < 300},
             {"what": "Kronos forecast test (research; stops when finished)",
              "alive": (_age_s(var / "kronos" / "forecasts.json", now_ms) or 10 ** 9) < 900}]
    procs += [{"what": f"{name} (port {port})", "alive": _port_open(port)} for name, port in SERVICES]
    return {"books": books, "review_after": review, "agents": _agents(root), "routines": routines,
            "pipeline": _pipeline(root), "processes": procs,
            "note": "Paper only: simulated books on Pionex daily candles; no orders are placed. Session routines "
                    "run only while the Claude session is open. Paper results are not evidence of future profit."}
