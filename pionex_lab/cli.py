"""Command line entry point: python -m pionex_lab <command>."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from decimal import Decimal
from pathlib import Path

from . import __version__
from .mandate import DEFAULT_CONFIG_DIR, PolicyError, load_mandate
from .paths import Paths, load_runtime_config
from .util import PROJECT_ROOT, SystemClock, iso_ms, pretty_json, utc_day

log = logging.getLogger("pionex_lab")

SKILL_DIR = PROJECT_ROOT / ".claude" / "skills" / "pionex-trading-lab"
SKILL_HASHES = {  # from Pionex-Claude-Code-Handoff.json (agent-skill-handoff-v1)
    "SKILL.md": "fbf05cfe3390657ded917c24ffe0ec851664496751251d91dbf07ead55551ddd",
    "assets/mandate.json": "04c392230697c2dfb046e706ad6052452c608cedb18864b13609713b4190eeac",
    "assets/dashboard.html": "12a61a695560684939001ec5167a83f920a5f216b011861c4d91ce3c06677fcc",
    "references/operations.md": "87572ab8d32ffc0f4c5e674d7ac500629f706b6fe68478297fbda48fa22c0b9e",
    "references/research.md": "cdd8bdf94f253be4c9cb59b3229135c2592c26fe1dfb5fd33a15b1ebb0e1f082",
    "references/pionex-api.md": "8cde79aa85baecde397cb953e51d5b38a1aed5e4347728d62c4ac107d74cb12e",
    "references/dashboard.md": "77faa9b687aa2f38d3e3de2521e41b74d212701048f929c475d02f924b0b6e20",
    "scripts/risk_gate.py": "7fc965fa82bb02f5cdf7512d966dfd0ac3325b802a80df6de6ec1ad983bdb1c8",
    "scripts/test_risk_gate.py": "0a38726642c2ae794d131fb87574561249905ce5c1b700d27678db235b5f27dc",
}


def _setup_logging(paths: Paths, name: str | None, verbose: bool) -> None:
    handlers = [logging.StreamHandler(sys.stderr)] if sys.stderr is not None else []  # None under pythonw
    if name:
        paths.logs.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(paths.logs / f"{name}.log"))
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _stop_event() -> threading.Event:
    stop = threading.Event()

    def handler(signum, frame):
        stop.set()
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
    return stop


def _client(cfg, capture=None):
    from .exchange.pionex_public import PionexPublic
    return PionexPublic(cfg["base_url"], on_response=capture)


# ------------------------------------------------------------------ commands
def cmd_init(args, paths, cfg, mandate):
    from .data.store import MarketStore
    from .ledger.journal import Journal
    from .reporting.server import load_or_create_token
    from .research.registry import Registry
    from .risk.service import RiskService
    paths.ensure()
    MarketStore(paths.market).close()
    j = Journal(paths.ledger)
    RiskService(mandate, paths.risk, SystemClock()).conn.close()
    Registry(paths.research).conn.close()
    load_or_create_token(paths.dashboard_token)
    print(f"initialised {paths.root}")
    print(f"mandate {mandate.path.name} sha256={mandate.sha256} live_enabled={mandate.live_enabled}")
    print(f"journal rows={j.count()} (chain ok={j.verify()[0]})")
    return 0


def cmd_verify(args, paths, cfg, mandate):
    ok = True
    for rel, expected in SKILL_HASHES.items():
        p = SKILL_DIR / rel
        got = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "MISSING"
        good = got == expected
        ok &= good
        print(f"{'OK ' if good else 'BAD'} skill/{rel}")
    vendored = PROJECT_ROOT / "pionex_lab" / "risk" / "risk_gate_ref.py"
    good = hashlib.sha256(vendored.read_bytes()).hexdigest() == SKILL_HASHES["scripts/risk_gate.py"]
    ok &= good
    print(f"{'OK ' if good else 'BAD'} vendored risk_gate_ref.py identical to skill reference")
    print(f"OK  mandate {mandate.path.name} matches lock ({mandate.sha256[:16]}...)")
    if paths.ledger.exists():
        from .ledger.journal import Journal
        chain_ok, bad, n = Journal(paths.ledger, readonly=True).verify()
        ok &= chain_ok
        print(f"{'OK ' if chain_ok else 'BAD'} journal hash chain ({n} rows){'' if chain_ok else f' broken at {bad}'}")
    return 0 if ok else 1


def cmd_capability(args, paths, cfg, mandate):
    """Probe public endpoints and write a capability report + raw fixtures."""
    paths.ensure()
    fixtures = paths.capability / "fixtures"
    fixtures.mkdir(parents=True, exist_ok=True)
    captured = []

    def capture(endpoint, status, text):
        name = endpoint.split("?")[0].strip("/").replace("/", "_")
        (fixtures / f"{name}.json").write_text(text[:2_000_000], encoding="utf-8")
        captured.append({"endpoint": endpoint, "status": status, "bytes": len(text)})

    client = _client(cfg, capture)
    universe = list(cfg["research_universe"])
    report = {"generated_at": iso_ms(SystemClock().now_ms()), "base_url": client.base_url,
              "official": client.is_official, "checks": {}, "symbols": {}, "captured": captured}

    def check(name, fn):
        try:
            out = fn()
            report["checks"][name] = {"ok": True, "detail": out}
        except Exception as exc:  # noqa: BLE001 - capability probing records every failure
            report["checks"][name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:500]}

    def symbols():
        rules, env = client.symbols(universe + [cfg.get("depeg_monitor_symbol")])
        for r in rules:
            complete, missing = r.complete()
            report["symbols"][r.symbol] = {"enabled": r.enabled, "base_precision": r.base_precision,
                                           "quote_precision": r.quote_precision, "min_amount": str(r.min_amount),
                                           "min_trade_size": str(r.min_trade_size),
                                           "max_trade_size": str(r.max_trade_size),
                                           "min_market_sell_size": str(r.min_dump_size),
                                           "complete_for_paper": complete, "missing_fields": missing}
        return {"count": len(rules), "skew_ms": env.skew_ms, "latency_ms": env.latency_ms}
    check("common/symbols", symbols)
    for s in universe:
        check(f"bookTickers:{s}", lambda s=s: (lambda bt: {"spread_bps": str(bt[0].spread_bps)})(client.book_ticker(s)))
        check(f"depth:{s}", lambda s=s: (lambda d: {"bid_levels": len(d[0].bids), "ask_levels": len(d[0].asks)})(
            client.depth(s, 20)))
        check(f"klines5M:{s}", lambda s=s: {"bars": len(client.klines(s, "5M", None, 5)[0])})
        check(f"trades:{s}", lambda s=s: {"trades": len(client.trades(s, 5)[0])})
    report["assumptions_and_untested"] = {
        "fees": "research assumption 0.05% per side from pionex.com/en/fees (page not fetched); actual account fees unverified",
        "rate_limits": "local budget 5 weight/s with exit headroom; per-endpoint weights not verified",
        "order_endpoint": "POST /api/v1/trade/order used only as a dry-run preview; never sent",
        "order_id_semantics": "clientOrderId <= 64 chars per official AI Kit schema; lookup/idempotency untested",
        "protective_stops": "spot LIMIT/MARKET only; no native stop/OCO demonstrated -> live remains disabled",
        "account_permissions": "not probed: no credentials are used by this build",
        "bot_balances": "unused; bot/earn balances excluded from GET /api/v1/account/balances per docs",
        "websocket": "not used; REST polling only",
        "response_shapes": "parsers validate strictly; compare fixtures in var/capability/fixtures with docs",
    }
    out = paths.capability / f"capability-{utc_day(SystemClock().now_ms())}.json"
    out.write_text(pretty_json(report), encoding="utf-8")
    ok = all(c["ok"] for c in report["checks"].values())
    for name, c in report["checks"].items():
        print(f"{'OK  ' if c['ok'] else 'FAIL'} {name}: {c.get('detail') or c.get('error')}")
    print(f"capability report: {out}")
    return 0 if ok else 2


def cmd_collect(args, paths, cfg, mandate):
    from .data.collector import Collector
    from .data.store import MarketStore
    paths.ensure()
    _setup_logging(paths, "collector", args.verbose)
    store = MarketStore(paths.market)
    col = Collector(_client(cfg), store, cfg, SystemClock())
    stop = _stop_event()
    days = None if args.no_backfill else (args.backfill_days or cfg["backfill_days"])
    if args.backfill_only:
        col.refresh_symbols()
        for s in col.symbols:
            for iv in col.intervals:
                print(json.dumps(col.backfill(s, iv, days or cfg["backfill_days"])))
        return 0
    log.info("collector starting against %s (backfill_days=%s)", cfg["base_url"], days)
    col.run(stop, backfill_days=days)
    return 0


def cmd_fetch_proxy(args, paths, cfg, mandate):
    """Download/refresh the labelled proxy-venue history (data/proxy.py) and report how closely
    it tracks Pionex. Public archive files only; no account or key."""
    from datetime import datetime, timezone
    from urllib.error import URLError
    from .data.proxy import VENUE, ProxyDataError, fetch, tracking_check
    from .data.store import MarketStore, MarketView
    paths.ensure()
    store = MarketStore(paths.proxy_market)
    now = SystemClock().now_ms()
    today = datetime.fromtimestamp(now / 1000, timezone.utc).date()
    print(f"source: {VENUE}")
    try:
        for s in cfg["research_universe"]:
            for iv in ("5M", "60M"):
                print(json.dumps(fetch(store, s, iv, args.months, today, now)))
    except (ProxyDataError, URLError, OSError) as exc:
        print(f"FETCH FAILED: {exc}. Existing proxy history is kept.")
        return 3
    if paths.market.exists():
        mv = MarketView(paths.market)
        for s in cfg["research_universe"]:
            print(json.dumps({"symbol": s, "tracking_5m": tracking_check(store.bars(s, "5M"), mv.bars(s, "5M"))}))
    return 0


def cmd_account(args, paths, cfg, mandate):
    """Read-only snapshots of the user's own Pionex account for the dashboard (runtime/account_reader.py)."""
    from .exchange.account import AccountReadError
    from .runtime.account_reader import run
    paths.ensure()
    _setup_logging(paths, "account", args.verbose)
    try:
        return run(paths, _stop_event(), once=args.once)
    except AccountReadError as exc:
        print(f"ACCOUNT READER: {exc}", file=sys.stderr)
        return 3


def _universe_bars(paths, cfg, timeframe="5m", source="pionex"):
    """Research bars from Pionex's store, or from the separate proxy-venue store."""
    from .data.store import MarketView, resample
    from .strategies.catalog import TIMEFRAMES
    base, context, _ = TIMEFRAMES[timeframe]
    mv = MarketView(paths.market)
    src = mv if source == "pionex" else MarketView(paths.proxy_market)
    out = {}
    for s in cfg["research_universe"]:
        b = src.bars(s, base)
        ctx = resample(b, context) if context == "4H" else src.bars(s, context)
        out[s] = (b, ctx)
    return out, mv


def cmd_research(args, paths, cfg, mandate):
    from .research.backtest import CostModel
    from .research.registry import Registry
    from .research.walkforward import DailyBudgetSpent, run_cycle
    paths.ensure()
    from .strategies.catalog import TIMEFRAMES
    proxy = args.data == "proxy"
    if proxy and not paths.proxy_market.exists():
        print("SKIPPED: no proxy history; run `fetch-proxy` first. No research budget used.")
        return 0
    universe, mv = _universe_bars(paths, cfg, args.timeframe, args.data)
    data_source = {"venue": "Pionex public API"}
    if proxy:
        from .data.proxy import VENUE, tracking_check
        base_iv = TIMEFRAMES[args.timeframe][0]
        tracking = {s: tracking_check(b, mv.bars(s, base_iv)) for s, (b, _) in universe.items()}
        print("proxy tracking vs Pionex: " + json.dumps(tracking))
        if not all(t["ok"] for t in tracking.values()):
            print("SKIPPED: the proxy venue does not track Pionex closely enough to stand in for it. "
                  "No research budget used.")
            return 0
        data_source = {"venue": VENUE, "tracking_vs_pionex": tracking}
    now = SystemClock().now_ms()
    spreads = [mv.median_spread_bps(s, now - 7 * 86_400_000) for s in universe]
    spreads = [x for x in spreads if x is not None]
    half_spread = max(1.0, max(spreads) / 2) if spreads else 1.0
    cost = CostModel(fee_per_side=float(mandate.fee_per_side), half_spread_bps=half_spread)
    base, context, names = TIMEFRAMES[args.timeframe]
    spans = [(b.t[-1] - b.t[0]) / 86_400_000 if len(b) > 1 else 0.0 for b, _ in universe.values()]
    need = MIN_HISTORY_DAYS[args.timeframe]
    if not spans or min(spans) < need:
        print(f"SKIPPED: {args.timeframe} research needs {need:.0f} days of history; have "
              f"{min(spans) if spans else 0:.1f}. No research budget used.")
        return 0
    print(f"data: {data_source['venue']}")
    print(f"timeframe {args.timeframe}: " + ", ".join(f"{s} {base}={len(b)} {context}={len(c)}"
                                                     for s, (b, c) in universe.items()))
    print(f"cost model: fee {cost.fee_per_side:.4%}/side, half-spread {half_spread:.2f} bps "
          f"({'observed median' if spreads else 'default; no book ticks yet'}), impact {cost.impact_bps} bps")
    try:
        results = run_cycle(universe, Registry(paths.research), mandate, cost, now, strategy_names=list(names),
                            enforce_daily_limit=not args.allow_second_cycle_for_tests, note=args.note or "",
                            timeframe=args.timeframe, data_source=data_source)
    except DailyBudgetSpent as exc:
        print(f"SKIPPED: {exc}. Run again after 00:00 UTC.")
        return 0
    for r in results:
        print(json.dumps(r, default=str))
    return 0


def cmd_paper(args, paths, cfg, mandate):
    from .data.store import MarketView
    from .runtime.engine import Engine
    paths.ensure()
    _setup_logging(paths, "paper", args.verbose)
    if not paths.market.exists():
        print("market.db missing: run `python -m pionex_lab init` and start the collector first", file=sys.stderr)
        return 2
    eng = Engine(cfg, paths, mandate, SystemClock(), MarketView(paths.market), config_dir=DEFAULT_CONFIG_DIR,
                 dry_run_cli=args.pionex_cli or "auto")
    log.info("paper engine starting; dry-run previews via %s", eng.cli or "built-in renderer")
    eng.run(_stop_event())
    return 0


def cmd_serve(args, paths, cfg, mandate):
    from .reporting.server import serve
    paths.ensure()
    _setup_logging(paths, "dashboard", args.verbose)
    host = args.host or cfg["dashboard"]["host"]
    port = args.port or cfg["dashboard"]["port"]

    def ready(httpd, token):
        url = f"http://{host}:{httpd.server_address[1]}/#token={token}"
        print(f"dashboard (read-only) ready. Open locally: {url}", flush=True)
        if args.url_file:
            fd = os.open(args.url_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as fh:
                fh.write(url)
    serve(paths, mandate, cfg, host=host, port=port, allow_remote=args.allow_remote, ready=ready)
    return 0


MIN_HISTORY_DAYS = {"5m": 20.0, "1h": 90.0}
DAILY_JOB_MINUTE = 10  # run the daily jobs from 00:10 UTC, after the day's first bars have closed
STARTUP_GRACE_MS = 15 * 60_000  # let the collector finish its backfill before the first research cycle


def research_timeframe_for(day: str) -> str:
    """Alternate the single daily research cycle between timeframes (mandate: one cycle per UTC day)."""
    from datetime import date
    return "5m" if date.fromisoformat(day).toordinal() % 2 == 0 else "1h"


def due_daily_jobs(state: dict, now_ms: int) -> list:
    """Daily automation for the supervisor: reconcile/attribute yesterday, then one research cycle.
    5-minute cycles run on the refreshed, labelled proxy-venue history: Pionex's own ~35 days of
    5-minute bars can never meet the 60-day out-of-sample gate. Hourly cycles use Pionex data."""
    day = utc_day(now_ms)
    if state.get("day") == day or (now_ms % 86_400_000) // 60_000 < DAILY_JOB_MINUTE:
        return []
    tf = research_timeframe_for(day)
    research = ["research", "--timeframe", tf, "--note", "automatic daily cycle"]
    if tf == "5m":
        return [["daily-review"], ["fetch-proxy"], research + ["--data", "proxy"]]
    return [["daily-review"], research]


def cmd_run(args, paths, cfg, mandate):
    """Supervise collector, paper engine, and dashboard; restart crashed children; run the daily
    review and the daily research cycle automatically."""
    paths.ensure()
    _setup_logging(paths, "supervisor", args.verbose)
    base = [sys.executable, "-m", "pionex_lab"]
    children = {"collector": base + ["collect"], "paper": base + ["paper"], "dashboard": base + ["serve"]}
    if (paths.root / "account.json").exists():  # opt-in read-only view of the user's own account
        children["account"] = base + ["account"]
    procs, backoff, next_start = {}, {k: 1.0 for k in children}, {k: 0.0 for k in children}
    stop = _stop_event()
    env = dict(os.environ)
    env["PIONEX_LAB_VAR"] = str(paths.root)  # children use the same state directory
    state_path = paths.root / "supervisor-daily.json"
    try:
        daily_state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        daily_state = {}
    queue, job, started_ms = [], None, int(time.time() * 1000)
    while not stop.is_set():
        if job is not None and job.poll() is not None:
            log.info("daily job finished with exit code %s", job.returncode)
            job = None
        now_ms = int(time.time() * 1000)
        if job is None and not queue and now_ms - started_ms >= STARTUP_GRACE_MS:
            jobs = due_daily_jobs(daily_state, now_ms)
            if jobs:
                queue = jobs
                daily_state = {"day": utc_day(now_ms), "jobs": [" ".join(j) for j in jobs]}
                state_path.write_text(json.dumps(daily_state), encoding="utf-8")
        if job is None and queue:
            argv = base + queue.pop(0)
            job = subprocess.Popen(argv, cwd=PROJECT_ROOT, env=env)
            log.info("started daily job %s pid=%s", " ".join(argv[3:]), job.pid)
        for name, argv in children.items():
            p = procs.get(name)
            if p is not None and p.poll() is None:
                continue
            if p is not None:
                log.warning("%s exited with %s; restarting in %.0fs", name, p.returncode, backoff[name])
                next_start[name] = time.time() + backoff[name]
                backoff[name] = min(60.0, backoff[name] * 2)
                procs[name] = None
            if time.time() >= next_start[name]:
                procs[name] = subprocess.Popen(argv, cwd=PROJECT_ROOT, env=env)
                log.info("started %s pid=%s", name, procs[name].pid)
        stop.wait(1.0)
    if job is not None and job.poll() is None:
        job.terminate()
    for name, p in procs.items():
        if p is not None and p.poll() is None:
            p.terminate()
    for p in procs.values():
        if p is not None:
            try:
                p.wait(timeout=15)
            except subprocess.TimeoutExpired:
                p.kill()
    return 0


def cmd_report(args, paths, cfg, mandate):
    from .data.store import MarketView
    from .reporting.report import build_report
    from .risk.service import RiskView
    risk = RiskView(mandate, paths.risk) if paths.risk.exists() else None
    market = MarketView(paths.market) if paths.market.exists() else None
    report = build_report(paths, mandate, SystemClock().now_ms(), market=market, risk=risk,
                          universe=cfg["research_universe"])
    text = pretty_json(report)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out} (import it in dashboard/index.html)")
    else:
        print(text)
    return 0


def cmd_status(args, paths, cfg, mandate):
    from .data.store import MarketView
    from .ledger.journal import Journal
    from .risk.service import RiskView
    from .runtime.state import current_state
    now = SystemClock().now_ms()
    out = {"now": iso_ms(now), "mandate_sha256": mandate.sha256, "live_enabled": mandate.live_enabled}
    if paths.ledger.exists():
        j = Journal(paths.ledger, readonly=True)
        started = j.last("EXPERIMENT_STARTED")
        eng, at = j.get_status("engine")
        out.update(state=current_state(j), journal_rows=j.count(), experiment=started[2] if started else None,
                   engine_heartbeat_age_s=(now - at) / 1000 if at else None, engine=eng)
    if paths.market.exists():
        mv = MarketView(paths.market)
        coll, at = mv.status("collector")
        out["collector"] = coll
        out["collector_heartbeat_age_s"] = (now - at) / 1000 if at else None
        out["books"] = {s: ((now - b["fetched_at"]) / 1000 if b else None)
                        for s in cfg["research_universe"] for b in [mv.latest_book(s)]}
        out["bars"] = {f"{s}:{iv}": len(mv.bars(s, iv)) for s in cfg["research_universe"] for iv in cfg["bar_intervals"]}
    if paths.risk.exists():
        out["risk"] = RiskView(mandate, paths.risk).state_summary()
    print(pretty_json(out))
    return 0


def cmd_daily_review(args, paths, cfg, mandate):
    """Reconcile and attribute the previous UTC day (no automatic strategy changes)."""
    from .ledger.journal import Journal
    j = Journal(paths.ledger)
    now = SystemClock().now_ms()
    day_start = (now // 86_400_000 - (0 if args.today else 1)) * 86_400_000
    day_end = day_start + 86_400_000
    closed, shadows, rejects, incidents = [], [], {}, []
    for _, at, kind, p in j.events(("POSITION_CLOSED", "SHADOW_CLOSE", "RISK_DECISION", "INCIDENT")):
        if not day_start <= at < day_end:
            continue
        if kind == "POSITION_CLOSED":
            closed.append(p)
        elif kind == "SHADOW_CLOSE":
            shadows.append(p)
        elif kind == "RISK_DECISION" and not p.get("approved"):
            key = str(p.get("reason", "")).split(":")[0]
            rejects[key] = rejects.get(key, 0) + 1
        elif kind == "INCIDENT":
            incidents.append(p.get("kind"))
    recon, recon_at = j.get_status("reconciliation")
    book_ok = bool(recon and recon.get("ok"))
    net = sum((Decimal(p["net_pnl_usd"]) for p in closed), Decimal(0))
    fees = sum((Decimal(p["fees_usd"]) for p in closed), Decimal(0))
    slip = sum((Decimal(p["slippage_usd"]) for p in closed), Decimal(0))
    review = {"day": utc_day(day_start), "reconciled": book_ok, "chain_ok": j.verify()[0],
              "closed_trades": len(closed), "net_pnl_usd": str(net), "fees_usd": str(fees),
              "slippage_usd": str(slip), "execution_vs_signal_note": "slippage is execution cost vs decision "
              "benchmark; remaining P&L is signal outcome", "rejections": rejects,
              "shadow_closed": len(shadows), "shadow_mean_bps": (sum(float(p["net_bps"]) for p in shadows) / len(shadows))
              if shadows else None, "incidents": incidents,
              "improvement_proposal": None, "note": "Propose at most one falsifiable change, test it as a shadow "
              "challenger on identical opportunities, and promote only through the gates. A single loss is not "
              "evidence of a mistake."}
    j.append("DAILY_REVIEW", review, now)
    print(pretty_json(review))
    return 0


def cmd_record_cost(args, paths, cfg, mandate):
    from .ledger.journal import Journal
    usd = Decimal(args.usd)
    if not usd.is_finite() or usd <= 0:
        raise SystemExit("cost must be positive")
    Journal(paths.ledger).append("OPERATING_COST", {"usd": str(usd), "note": args.note[:300]}, SystemClock().now_ms())
    print(f"recorded external operating cost ${usd} (the paper engine applies it on its next replay/restart)")
    return 0


def cmd_review_latch(args, paths, cfg, mandate):
    """Human-only: clear a REVIEW latch after a reviewed mandate decision."""
    from .ledger.journal import Journal
    from .risk.service import RiskService
    if not sys.stdin.isatty():
        raise SystemExit("review-latch requires an interactive human terminal")
    typed = input(f"Type the latch name ({args.latch}) to confirm a reviewed mandate decision: ").strip()
    if typed != args.latch:
        raise SystemExit("confirmation did not match; nothing changed")
    j = Journal(paths.ledger)
    RiskService(mandate, paths.risk, SystemClock(), journal=j).review_clear(args.latch, args.reviewer, args.note,
                                                                             SystemClock().now_ms())
    print(f"cleared {args.latch}")
    return 0


def cmd_live_preflight(args, paths, cfg, mandate):
    from .execution.live import live_preflight
    from .research.registry import Registry
    from .risk.service import RiskView
    from .ledger.journal import Journal
    from .reporting.report import paper_evidence
    reg = Registry(paths.research, readonly=True) if paths.research.exists() else None
    risk = RiskView(mandate, paths.risk) if paths.risk.exists() else None
    evidence = {}
    if paths.ledger.exists():
        closed = [p for _, _, _, p in Journal(paths.ledger, readonly=True).events(("POSITION_CLOSED",))]
        evidence = paper_evidence(closed, SystemClock().now_ms())
    gates = live_preflight(mandate, registry=reg, risk=risk, **evidence)
    for g in gates:
        print(f"{g['status']:<16} {g['gate']}: {g['detail']}")
    print("\nLIVE TRADING DISABLED" if any(g["status"] != "PASS" for g in gates) else "\nno live path exists")
    return 3


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="pionex_lab", description=f"Pionex Trading Lab {__version__} (paper only)")
    parser.add_argument("--var", help="runtime state directory (default ./var or $PIONEX_LAB_VAR)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create var/ databases and dashboard token")
    sub.add_parser("verify", help="verify skill hashes, vendored risk gate, mandate lock, journal chain")
    sub.add_parser("capability", help="probe public Pionex endpoints; write capability report + fixtures")
    p = sub.add_parser("collect", help="run the market-data collector")
    p.add_argument("--backfill-days", type=float)
    p.add_argument("--no-backfill", action="store_true")
    p.add_argument("--backfill-only", action="store_true")
    p = sub.add_parser("research", help="run one walk-forward qualification cycle (max one per UTC day per timeframe)")
    p.add_argument("--timeframe", choices=["5m", "1h"], default="5m",
                   help="5m: 5-minute candles with 1h context; 1h: 1-hour candles with 4h context")
    p.add_argument("--note")
    p.add_argument("--data", choices=["pionex", "proxy"], default="pionex",
                   help="pionex: Pionex bars; proxy: labelled Binance archive bars (see fetch-proxy)")
    p.add_argument("--allow-second-cycle-for-tests", action="store_true", help=argparse.SUPPRESS)
    p = sub.add_parser("account", help="read-only snapshots of your own Pionex account (needs var/account.json)")
    p.add_argument("--once", action="store_true")
    p = sub.add_parser("fetch-proxy", help="download/refresh labelled proxy-venue history (Binance public archive)")
    p.add_argument("--months", type=int, default=12)
    p = sub.add_parser("paper", help="run the paper engine")
    p.add_argument("--pionex-cli", help="path to pionex-trade-cli for dry-run previews (default: auto)")
    p = sub.add_parser("serve", help="serve the read-only dashboard")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--allow-remote", action="store_true")
    p.add_argument("--url-file", help=argparse.SUPPRESS)
    sub.add_parser("run", help="supervise collector + paper engine + dashboard")
    p = sub.add_parser("report", help="export the dashboard report JSON")
    p.add_argument("--out")
    sub.add_parser("status", help="show state, feeds, latches")
    p = sub.add_parser("daily-review", help="journal the daily reconciliation/attribution review")
    p.add_argument("--today", action="store_true")
    p = sub.add_parser("record-cost", help="record an external operating cost in USD")
    p.add_argument("--usd", required=True)
    p.add_argument("--note", required=True)
    p = sub.add_parser("review-latch", help="HUMAN ONLY: clear a review latch after a mandate decision")
    p.add_argument("--latch", required=True)
    p.add_argument("--reviewer", required=True)
    p.add_argument("--note", required=True)
    sub.add_parser("live-preflight", help="list every live-trading gate (always refuses in this build)")
    args = parser.parse_args(argv)
    paths = Paths(Path(args.var)) if args.var else Paths.default()
    cfg = load_runtime_config()
    try:
        mandate = load_mandate(DEFAULT_CONFIG_DIR)
    except PolicyError as exc:
        print(f"POLICY ERROR: {exc}", file=sys.stderr)
        return 4
    handler = globals()["cmd_" + args.cmd.replace("-", "_")]
    return handler(args, paths, cfg, mandate)
