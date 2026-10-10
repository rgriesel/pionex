#!/usr/bin/env python3
"""Build the hosted, serverless Wave Lab page: wavelab/index.html with wavelab/engine.js inlined.

The standalone page runs the wave engine in the browser on the labelled synthetic demo feed. It
cannot reach the Pionex API; live data needs the local server (`python3 -m pionex_lab waves`).

    python3 tools/build_wavelab_standalone.py [OUT]   (default: var/wavelab-standalone.html)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def build() -> str:
    page = (ROOT / "wavelab" / "index.html").read_text(encoding="utf-8")
    engine = (ROOT / "wavelab" / "engine.js").read_text(encoding="utf-8")
    if "</script" in engine.lower():
        raise SystemExit("engine.js must not contain a closing script tag")
    # The host wraps the page in its own document skeleton: drop ours.
    for pat in (r"<!doctype html>\s*", r"<html[^>]*>\s*", r"</html>\s*", r"<head>\s*", r"</head>\s*",
                r"<body>\s*", r"</body>\s*", r'<meta charset="utf-8">\s*', r'<meta name="viewport"[^>]*>\s*'):
        page, n = re.subn(pat, "", page, count=1, flags=re.I)
        if n != 1:
            raise SystemExit(f"index.html no longer matches {pat!r}")
    marker = '<script>\n"use strict";'
    if page.count(marker) != 1:
        raise SystemExit("main script marker not found")
    return page.replace(marker, f"<script>\n{engine}</script>\n{marker}")


def main(argv) -> int:
    out = Path(argv[1]) if len(argv) > 1 else ROOT / "var" / "wavelab-standalone.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
