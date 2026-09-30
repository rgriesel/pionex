"""Read-only view of the user's own Pionex account, for the dashboard's "Human" line.

The credentials are loaded at runtime from an env file the user points to (var/account.json,
git-ignored). They are held only in memory and never printed, logged, journaled, or returned:
`Credentials` redacts itself, and errors carry variable NAMES, never values.

This module can only issue signed GET requests to an explicit allowlist of balance endpoints.
There is no order, cancel, transfer, or withdrawal code here, and `signed_get` refuses any other
path. Nothing in this module can change the account. Signing follows the official
pionex-ai-kit client (HMAC-SHA256 over METHOD + path + sorted query incl. a ms timestamp).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from .. import __version__

BASE_URL = "https://api.pionex.com"
READ_ONLY_PATHS = frozenset({"/api/v1/account/balances", "/api/v1/wallet/balancesFull", "/api/v1/trade/fills"})
PREFERRED = ("PIONEX_API_KEY", "PIONEX_API_SECRET")   # the names the official CLI uses


class AccountReadError(RuntimeError):
    pass


class Credentials:
    __slots__ = ("_key", "_secret", "source")

    def __init__(self, key: str, secret: str, source: str):
        self._key, self._secret, self.source = key, secret, source

    def __repr__(self):
        return f"Credentials(<redacted>, source={self.source!r})"

    __str__ = __repr__


def _parse_env(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name.startswith("export "):
            name = name[7:].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        out[name] = value
    return out


def load_credentials(env_file: Path | str, key_var: str | None = None, secret_var: str | None = None) -> Credentials:
    """Pick the API key/secret variables: explicit names, else the official CLI's names, else the
    single PIONEX-named *KEY / *SECRET pair. Ambiguity is an error listing names only."""
    path = Path(env_file)
    try:
        env = _parse_env(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise AccountReadError(f"cannot read credentials file {path}: {exc.strerror}") from None
    names = sorted(env)
    if key_var and secret_var:
        pick = (key_var, secret_var)
    elif all(n in env for n in PREFERRED):
        pick = PREFERRED
    else:
        pio = [n for n in names if "PIONEX" in n.upper()]
        keys = [n for n in pio if n.upper().endswith("KEY") and "SECRET" not in n.upper()]
        secrets = [n for n in pio if "SECRET" in n.upper()]
        if len(keys) != 1 or len(secrets) != 1:
            raise AccountReadError(f"cannot tell which variables in {path.name} hold the Pionex key and secret; "
                                   f"variable names present: {names}. Set key_var/secret_var in var/account.json.")
        pick = (keys[0], secrets[0])
    missing = [n for n in pick if not env.get(n)]
    if missing:
        raise AccountReadError(f"{path.name} has no value for {missing}; variable names present: {names}")
    return Credentials(env[pick[0]], env[pick[1]], f"{path} ({pick[0]}, {pick[1]})")


def sign(secret: str, method: str, path: str, query: dict) -> tuple[str, str]:
    """(path_with_query, signature) exactly as the official client builds them."""
    qs = "&".join(f"{k}={query[k]}" for k in sorted(query))
    path_url = f"{path}?{qs}"
    sig = hmac.new(secret.encode(), f"{method}{path_url}".encode(), hashlib.sha256).hexdigest()
    return path_url, sig


def signed_get(creds: Credentials, path: str, query: dict | None = None, base_url: str = BASE_URL,
               now_ms: int | None = None, opener=urllib.request.urlopen, timeout: float = 15.0) -> dict:
    if path not in READ_ONLY_PATHS:
        raise AccountReadError(f"refused: {path} is not an allowlisted read-only endpoint")
    params = {**(query or {}), "timestamp": str(now_ms if now_ms is not None else int(time.time() * 1000))}
    path_url, sig = sign(creds._secret, "GET", path, params)
    req = urllib.request.Request(base_url + path_url, method="GET",
                                 headers={"PIONEX-KEY": creds._key, "PIONEX-SIGNATURE": sig,
                                          "Content-Type": "application/json", "Accept": "application/json",
                                          "User-Agent": f"pionex-lab/{__version__}"})
    try:
        with opener(req, timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise AccountReadError(f"HTTP {exc.code} on {path}: {_scrub(detail, creds)}") from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise AccountReadError(f"request to {path} failed: {_scrub(str(exc), creds)}") from None
    if isinstance(body, dict) and body.get("result") is False:
        raise AccountReadError(f"Pionex rejected {path}: {_scrub(json.dumps(body)[:300], creds)}")
    return body


def _scrub(text: str, creds: Credentials) -> str:
    for s in (creds._key, creds._secret):
        if s:
            text = text.replace(s, "<redacted>")
    return text
