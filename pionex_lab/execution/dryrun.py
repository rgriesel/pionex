"""Pionex dry-run order previews for paper trading.

Pionex's official AI Kit CLI (`pionex-trade-cli orders new ... --dry-run`) prints
the resolved request body for POST /api/v1/trade/order and returns WITHOUT sending
anything. It produces no fills, balances, or exchange-side validation, so the paper
broker uses it for the order request and simulates fills separately from later
observed public quotes.

Every paper order is (1) rendered here with the official tool's field rules,
(2) validated against the symbol filters, and (3) when the pinned official CLI is
installed, cross-checked against its own --dry-run output. The CLI runs with an
empty HOME, no PIONEX_* credential variables, and --read-only, so it cannot load
keys or place orders even if its behaviour changed. A mismatch rejects the order.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from decimal import Decimal
from pathlib import Path

from ..exchange.pionex_public import SymbolRules
from ..util import PROJECT_ROOT

ORDER_PATH = "/api/v1/trade/order"
TOOL_NAME = "pionex_orders_new_order"
# The pinned package's JS entry point, run with `node` directly so it works the same on
# Windows (where npm's .bin shims are .cmd files) and on macOS/Linux.
PINNED_CLI_JS = PROJECT_ROOT / "tools" / "pionex-cli" / "node_modules" / "@pionex" / "pionex-ai-kit" / "dist" / "index.js"


class DryRunError(ValueError):
    pass


def _plain(d: Decimal) -> str:
    s = format(d.normalize(), "f")
    return s


def _is_multiple(value: Decimal, step: Decimal) -> bool:
    return (value / step) == (value / step).to_integral_value()


def build_order_request(rules: SymbolRules, side: str, type_: str, client_order_id: str,
                        size: Decimal | None = None, price: Decimal | None = None,
                        amount: Decimal | None = None, ioc: bool | None = None) -> dict:
    """Render and validate the exact body the official tool would send."""
    if side not in ("BUY", "SELL") or type_ not in ("LIMIT", "MARKET"):
        raise DryRunError("ORDER_SIDE_OR_TYPE")
    if not client_order_id or len(client_order_id) > 64:
        raise DryRunError("CLIENT_ORDER_ID_LENGTH")
    if not rules.enabled:
        raise DryRunError("SYMBOL_DISABLED")
    body: dict = {"symbol": rules.symbol, "side": side, "type": type_, "clientOrderId": client_order_id}
    if type_ == "LIMIT":
        if size is None or price is None or amount is not None:
            raise DryRunError("LIMIT_REQUIRES_PRICE_AND_SIZE")
    elif side == "BUY":
        if amount is None or size is not None or price is not None:
            raise DryRunError("MARKET_BUY_REQUIRES_AMOUNT")
    else:
        if size is None or amount is not None or price is not None:
            raise DryRunError("MARKET_SELL_REQUIRES_SIZE")
    if size is not None:
        if size <= 0 or not _is_multiple(size, rules.quantity_step):
            raise DryRunError("SIZE_PRECISION")
        if type_ == "MARKET":
            lo, hi = rules.min_dump_size, rules.max_dump_size
        else:
            lo, hi = rules.min_trade_size, rules.max_trade_size
        if lo is None or size < lo:
            raise DryRunError("SIZE_BELOW_MINIMUM")
        if hi is not None and size > hi:
            raise DryRunError("SIZE_ABOVE_MAXIMUM")
        body["size"] = _plain(size)
    if price is not None:
        if price <= 0 or not _is_multiple(price, rules.price_step):
            raise DryRunError("PRICE_PRECISION")
        body["price"] = _plain(price)
        if rules.min_amount is None or size * price < rules.min_amount:
            raise DryRunError("NOTIONAL_BELOW_MINIMUM")
    if amount is not None:
        precision = rules.raw.get("amountPrecision")
        if amount <= 0 or (isinstance(precision, int) and amount != amount.quantize(Decimal(1).scaleb(-precision))):
            raise DryRunError("AMOUNT_PRECISION")
        if rules.min_amount is None or amount < rules.min_amount:
            raise DryRunError("AMOUNT_BELOW_MINIMUM")
        body["amount"] = _plain(amount)
    if ioc is not None:
        body["IOC"] = bool(ioc)
    return {"tool": TOOL_NAME, "method": "POST", "path": ORDER_PATH, "args": body, "sent": False}


def find_official_cli(explicit: str | None = None) -> list | None:
    """Command prefix (argv list) that runs the official CLI, or None if unavailable."""
    for candidate in (explicit, os.environ.get("PIONEX_TRADE_CLI")):
        if candidate and Path(candidate).is_file():
            if candidate.endswith(".js"):
                node = shutil.which("node")
                return [node, candidate] if node else None
            if os.access(candidate, os.X_OK):
                return [candidate]
    node = shutil.which("node")
    if node and PINNED_CLI_JS.is_file():
        return [node, str(PINNED_CLI_JS)]
    found = shutil.which("pionex-trade-cli")
    return [found] if found else None


def official_cli_preview(request: dict, cli: list, timeout_s: float = 20.0) -> dict:
    """Run the official CLI's dry-run for the same order and return its JSON."""
    a = request["args"]
    argv = list(cli) + ["--read-only", "orders", "new", "--symbol", a["symbol"], "--side", a["side"],
                        "--type", a["type"], "--client-order-id", a["clientOrderId"]]
    for key, flag in (("size", "--size"), ("price", "--price"), ("amount", "--amount")):
        if key in a:
            argv += [flag, a[key]]
    if a.get("IOC"):
        argv.append("--IOC")
    argv.append("--dry-run")
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PIONEX")}
    with tempfile.TemporaryDirectory(prefix="pionex-dryrun-") as home:
        env["HOME"] = env["USERPROFILE"] = home  # no ~/.pionex/config.toml can be read (POSIX or Windows)
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout_s, env=env, check=False)
    if proc.returncode != 0:
        raise DryRunError(f"OFFICIAL_CLI_FAILED: {proc.stderr.strip()[:300]}")
    try:
        return json.loads(proc.stdout)
    except ValueError as exc:
        raise DryRunError("OFFICIAL_CLI_OUTPUT_NOT_JSON") from exc


def preview(rules: SymbolRules, cli: list | None, **order) -> dict:
    """Build the request, cross-check with the official CLI when available."""
    req = build_order_request(rules, **order)
    if cli:
        out = official_cli_preview(req, cli)
        if out.get("tool") != TOOL_NAME or out.get("args") != req["args"]:
            raise DryRunError(f"OFFICIAL_CLI_MISMATCH: {out!r} != {req['args']!r}")
        req["preview_source"] = "official pionex-trade-cli --dry-run"
    else:
        req["preview_source"] = "built-in renderer (official CLI not installed)"
    return req
