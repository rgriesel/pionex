"""Filesystem layout for runtime state (everything under var/ is git-ignored)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .util import PROJECT_ROOT, load_json


@dataclass(frozen=True)
class Paths:
    root: Path

    @classmethod
    def default(cls) -> "Paths":
        return cls(Path(os.environ.get("PIONEX_LAB_VAR", PROJECT_ROOT / "var")))

    @property
    def market(self) -> Path:
        return self.root / "market.db"

    @property
    def ledger(self) -> Path:
        return self.root / "ledger.db"

    @property
    def risk(self) -> Path:
        return self.root / "risk.db"

    @property
    def research(self) -> Path:
        return self.root / "research.db"

    @property
    def reports(self) -> Path:
        return self.root / "reports"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def capability(self) -> Path:
        return self.root / "capability"

    @property
    def dashboard_token(self) -> Path:
        return self.root / "dashboard.token"

    def ensure(self) -> "Paths":
        for p in (self.root, self.reports, self.logs, self.capability):
            p.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass
        return self


def load_runtime_config(path: Path | None = None) -> dict:
    cfg = load_json(path or PROJECT_ROOT / "config" / "runtime.json")
    env_url = os.environ.get("PIONEX_LAB_BASE_URL")
    if env_url:
        cfg["base_url"] = env_url
    return cfg
