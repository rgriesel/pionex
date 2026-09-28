"""Authenticated, read-only dashboard server (standard library).

* Binds to 127.0.0.1 by default. Remote binding requires an explicit flag and
  must sit behind a TLS reverse proxy; this server speaks plain HTTP.
* Every /api request needs `Authorization: Bearer <token>`; the token lives in
  var/dashboard.token (mode 0600) and is never an exchange credential.
* All databases are opened read-only per request; the server cannot write the
  ledger, change risk state, or reach the exchange. There are no control actions.
"""
from __future__ import annotations

import hmac
import ipaddress
import json
import logging
import os
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..data.store import MarketView
from ..ledger.journal import Journal
from ..research.registry import Registry
from ..risk.service import RiskView
from ..util import PROJECT_ROOT, SystemClock
from .report import ReportInvalid, build_report

log = logging.getLogger("pionex_lab.server")
DASHBOARD = PROJECT_ROOT / "dashboard" / "index.html"
CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; "
       "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def load_or_create_token(path: Path) -> str:
    path = Path(path)
    if path.exists():
        tok = path.read_text(encoding="utf-8").strip()
        if len(tok) >= 32:
            return tok
    tok = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(tok)
    return tok


def make_handler(paths, mandate, cfg, token: str, clock):
    universe = list(cfg["research_universe"])

    class Handler(BaseHTTPRequestHandler):
        server_version = "pionex-lab"
        sys_version = ""

        def log_message(self, fmt, *args):  # never log headers (they carry the token)
            log.info("%s %s", self.command, self.path.split("?")[0])

        def _send(self, status, body: bytes, ctype="application/json"):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", CSP)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status, obj):
            self._send(status, json.dumps(obj, allow_nan=False).encode("utf-8"))

        def _authorized(self) -> bool:
            auth = self.headers.get("Authorization", "")
            given = auth[7:] if auth.startswith("Bearer ") else ""
            return bool(given) and hmac.compare_digest(given.encode(), token.encode())

        def do_GET(self):  # noqa: N802
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                return self._send(200, DASHBOARD.read_bytes(), "text/html; charset=utf-8")
            if not path.startswith("/api/"):
                return self._json(404, {"error": "not found"})
            if not self._authorized():
                return self._json(401, {"error": "missing or invalid bearer token"})
            if path == "/api/report":
                return self._report()
            if path == "/api/health":
                return self._health()
            return self._json(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802 - read-only service: no mutations exist
            self._json(405, {"error": "read-only telemetry endpoint"})

        do_PUT = do_DELETE = do_PATCH = do_POST

        def _report(self):
            if not Path(paths.ledger).exists():
                return self._json(503, {"error": "ledger not initialised; run `python -m pionex_lab init`"})
            journal = Journal(paths.ledger, readonly=True)
            market = MarketView(paths.market) if Path(paths.market).exists() else None
            risk = RiskView(mandate, paths.risk) if Path(paths.risk).exists() else None
            registry = Registry(paths.research, readonly=True) if Path(paths.research).exists() else None
            try:
                report = build_report(paths, mandate, clock.now_ms(), journal=journal, market=market, risk=risk,
                                      registry=registry, universe=universe)
                self._json(200, report)
            except ReportInvalid as exc:
                self._json(500, {"error": f"ledger export failed validation: {exc}"})
            finally:
                journal.close()
                for o in (market, risk):
                    if o is not None:
                        o.close()
                if registry is not None:
                    registry.conn.close()

        def _health(self):
            journal = Journal(paths.ledger, readonly=True) if Path(paths.ledger).exists() else None
            try:
                eng, at = journal.get_status("engine") if journal else (None, None)
                self._json(200, {"engine": eng, "engine_updated_ms": at, "now_ms": clock.now_ms()})
            finally:
                if journal:
                    journal.close()

    return Handler


def serve(paths, mandate, cfg, host="127.0.0.1", port=8765, allow_remote=False, clock=None, ready=None):
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host == "localhost"
    if not loopback and not allow_remote:
        raise SystemExit("refusing to bind a non-loopback address without --allow-remote (put it behind TLS)")
    token = load_or_create_token(paths.dashboard_token)
    httpd = ThreadingHTTPServer((host, port), make_handler(paths, mandate, cfg, token, clock or SystemClock()))
    if ready is not None:
        ready(httpd, token)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
    return httpd
