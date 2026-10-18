"""Disk hygiene for the firm (called by selfheal.py every 2 minutes; cheap).

Videos downloaded for research are deleted once their frames and transcript are extracted: any video file under
var/youtube older than KEEP_HOURS is removed, and everything under var/youtube that is not a small frame/text file is
removed when the folder exceeds MAX_GB or the disk has less than MIN_FREE_GB free. Frames (jpg/png), subtitles and
the method cards are kept. Never touches anything outside var/youtube, var/tmp and the npm/pip caches.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIDEO = {".mp4", ".webm", ".mkv", ".m4a", ".mov", ".avi", ".wav", ".mp3", ".part", ".ytdl"}
KEEP_HOURS, MAX_GB, MIN_FREE_GB = 2, 3.0, 6.0


def run() -> str:
    yt = ROOT / "var" / "youtube"
    freed, n = 0, 0
    if yt.exists():
        now = time.time()
        files = [f for f in yt.rglob("*") if f.is_file()]
        for f in files:
            if f.suffix.lower() in VIDEO and now - f.stat().st_mtime > KEEP_HOURS * 3600:
                freed += f.stat().st_size
                f.unlink(missing_ok=True)
                n += 1
        total = sum(f.stat().st_size for f in yt.rglob("*") if f.is_file()) / 1e9
        low = shutil.disk_usage(ROOT).free / 1e9 < MIN_FREE_GB
        if total > MAX_GB or low:                      # emergency: drop every video file, then the biggest leftovers
            for f in sorted((f for f in yt.rglob("*") if f.is_file()), key=lambda x: -x.stat().st_size):
                if f.suffix.lower() in VIDEO or f.stat().st_size > 20_000_000:
                    freed += f.stat().st_size
                    f.unlink(missing_ok=True)
                    n += 1
    return f"cleanup: removed {n} files, {freed / 1e6:.0f} MB" if n else "cleanup: nothing to remove"


if __name__ == "__main__":
    print(run())
