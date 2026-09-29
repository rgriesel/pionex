"""Shared test fixtures (synthetic data only)."""
from __future__ import annotations

import math
import random
import shutil
import tempfile
from pathlib import Path

from pionex_lab.data.store import Bars
from pionex_lab.mandate import load_mandate
from pionex_lab.paths import Paths
from pionex_lab.util import PROJECT_ROOT

T0 = 1_790_000_000_000 - (1_790_000_000_000 % 86_400_000)  # a UTC midnight in 2026


def tmp_paths() -> tuple[Paths, str]:
    d = tempfile.mkdtemp(prefix="pionex-lab-test-")
    return Paths(Path(d)).ensure(), d


def cleanup(d: str) -> None:
    shutil.rmtree(d, ignore_errors=True)


def mandate():
    return load_mandate(PROJECT_ROOT / "config")


def copy_config(dst: Path) -> Path:
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("mandate.v1.json", "mandate.lock.json"):
        shutil.copy(PROJECT_ROOT / "config" / name, dst / name)
    return dst


def runtime_cfg():
    import json
    cfg = json.loads((PROJECT_ROOT / "config" / "runtime.json").read_text())
    return cfg


def make_bars(symbol, interval, closes, start=T0, spread=0.001, vol=None):
    step = {"5M": 300_000, "60M": 3_600_000}[interval]
    b = Bars(symbol, interval, [], [], [], [], [], [])
    prev = closes[0]
    for i, c in enumerate(closes):
        o = prev
        b.t.append(start + i * step)
        b.o.append(o)
        b.h.append(max(o, c) * (1 + spread))
        b.l.append(min(o, c) * (1 - spread))
        b.c.append(c)
        b.v.append(vol[i] if vol else 10.0)
        prev = c
    return b


def random_walk(n, start=100.0, sigma=0.002, seed=1, drift=0.0):
    rng = random.Random(seed)
    out, p = [], start
    for _ in range(n):
        p *= math.exp(drift + sigma * rng.gauss(0, 1))
        out.append(p)
    return out


def hourly_from_5m(b5):
    """Aggregate 5m bars into 60m bars (complete hours only)."""
    out = Bars(b5.symbol, "60M", [], [], [], [], [], [])
    i = 0
    while i + 12 <= len(b5):
        if b5.t[i] % 3_600_000:
            i += 1
            continue
        seg = range(i, i + 12)
        out.t.append(b5.t[i])
        out.o.append(b5.o[i])
        out.h.append(max(b5.h[k] for k in seg))
        out.l.append(min(b5.l[k] for k in seg))
        out.c.append(b5.c[i + 11])
        out.v.append(sum(b5.v[k] for k in seg))
        i += 12
    return out
