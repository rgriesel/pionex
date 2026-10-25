"""Descriptive attribution of the owner's finished grid bots (CLO-128, 2026-10-25 SAST). Read-only, no network, no orders.
Per bot: market move m over its life (hourly BTC close, last bar at/before start and end), d = +1 long / -1 short / 0 neutral,
direction component = investment * leverage * d * m (what a plain leveraged position of the same sign would have made),
residual = total_pnl - direction component. Grids are not plain positions (scaled in gradually, capped by the range),
so the split is an approximation and is labelled so. No pass/fail test; descriptive only."""
from __future__ import annotations

import bisect
import json
import sys
from pathlib import Path

from .owner_bots import load_bots, load_hourly


def dsign(s):
    s = (s or "").lower()
    return 1 if "long" in s or s == "up" else -1 if "short" in s or s == "down" else 0


def _extra(account_db):
    """Per bot: totalRealizedProfit, quoteInvestment (actual capital, incl. top-ups), marginBalance, fees, funding."""
    import sqlite3
    c = sqlite3.connect(f"file:{Path(account_db).as_posix()}?mode=ro", uri=True)
    last = {}
    for oid, raw in c.execute("SELECT bu_order_id, raw FROM bots WHERE bu_order_id IS NOT NULL AND raw IS NOT NULL ORDER BY at"):
        last[oid] = json.loads(raw)["summary"]["buOrderData"]
    c.close()
    g = lambda d, k: float(d[k]) if d.get(k) not in (None, "") else None
    return {o: {"realized": g(d, "totalRealizedProfit"), "quote_invest": g(d, "quoteInvestment"),
                "margin_balance": g(d, "marginBalance"), "fee": g(d, "totalFee"), "funding": g(d, "totalFundingFee")}
            for o, d in last.items()}


def build(root: Path):
    bots = load_bots(root / "var" / "account.db")
    extra = _extra(root / "var" / "account.db")
    bars = load_hourly([root / "var" / "market.db", root / "var" / "proxy_market.db"])
    ts = [t for t, _ in bars]
    cl = [c for _, c in bars]

    def px(ms):
        i = bisect.bisect_right(ts, ms) - 1
        return cl[i] if i >= 0 and ms - ts[i] < 2 * 3_600_000 else None
    rows = []
    for b in bots:
        p0, p1 = px(b["start"]), px(b["end"])
        m = (p1 / p0 - 1) if p0 and p1 else None
        d = dsign(b["direction"])
        dc = b["investment"] * b["leverage"] * d * m if m is not None else None
        rows.append({**b, **extra.get(b["id"], {}), "dirsign": d, "mkt_move": m, "dir_component": dc,
                     "residual": None if dc is None else b["total_pnl"] - dc})
    return rows


def main():
    root = Path(__file__).resolve().parents[2]
    rows = build(root)
    out = root / "var" / "reports" / "owner_grid_attrib_2026-10-25.json"
    out.write_text(json.dumps(rows, indent=1, default=str))
    print(len(rows), "bots ->", out)
    return rows


if __name__ == "__main__":
    main()
