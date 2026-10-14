"""Telegram messages from the firm to the owner: important and informative only, never spam.

Agents call `py -m pionex_lab notify --level important --key <id> "text"`. Levels:
  critical   something is broken or a hard limit was touched; always sent at once
  important  a verdict or decision the owner should know (a PASS, a red-team verdict, a flip,
             a promotion); at most MAX_PER_DAY non-critical messages a day
  daily      the one morning summary
Anti-spam: the same --key is sent at most once per 24 h; non-critical messages in quiet hours
(23:00-06:59 local) are held in var/notify/outbox.json and sent together with the next message
after quiet hours (normally the morning summary).
The bot token comes from ~/.telegram.env (TELEGRAM_BOT_TOKEN, optional TELEGRAM_CHAT_ID; falls
back to ~/.wave-alerts.env). It is never printed or logged. Without it, messages stay in the outbox.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

LEVELS = ("critical", "important", "daily")
MAX_PER_DAY = 6
QUIET = (23, 7)                      # [23:00, 07:00) local
PREFIX = "Cloudworks AI trading"
TOKEN_FILES = (Path.home() / ".telegram.env", Path.home() / ".wave-alerts.env")


def _now():
    return datetime.now().astimezone()


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1), encoding="utf-8")


def quiet(now: datetime) -> bool:
    return now.hour >= QUIET[0] or now.hour < QUIET[1]


def telegram():
    from .waves.alerts import load_telegram
    for f in TOKEN_FILES:
        tg = load_telegram(f) if f.exists() else None
        if tg:
            return tg
    return None


def notify(var: Path, text: str, level: str = "important", key: str | None = None, now: datetime | None = None,
           sender=None) -> str:
    """Returns what happened: sent / held (quiet hours) / held (no token) / skipped (duplicate|daily cap)."""
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}")
    now = now or _now()
    d = Path(var) / "notify"
    state = _load(d / "state.json", {"keys": {}, "sent": []})
    day_ago = now.timestamp() - 86_400
    state["keys"] = {k: t for k, t in state["keys"].items() if t > day_ago}
    state["sent"] = [t for t in state["sent"] if t > day_ago]
    if key and key in state["keys"]:
        return "skipped (duplicate)"
    outbox = _load(d / "outbox.json", [])
    if level == "important" and len(state["sent"]) >= MAX_PER_DAY:
        return "skipped (daily cap)"
    line = f"{text.strip()[:900]}"
    if level != "critical" and quiet(now):
        outbox.append({"at": now.isoformat(timespec="minutes"), "level": level, "text": line})
        _save(d / "outbox.json", outbox)
        if key:
            state["keys"][key] = now.timestamp()
        _save(d / "state.json", state)
        return "held (quiet hours)"
    parts = []
    flush = bool(outbox) and not quiet(now)                 # a night-time critical goes alone
    if flush:
        parts.append("Held overnight:\n" + "\n".join(f"- {m['text']}" for m in outbox))
    head = {"critical": "CRITICAL", "important": "Update", "daily": "Morning summary"}[level]
    parts.insert(0, f"{PREFIX} - {head}\n{line}")
    message = "\n\n".join(parts)[:3900]
    if sender is None:
        tg = telegram()
        if tg is None:
            outbox.append({"at": now.isoformat(timespec="minutes"), "level": level, "text": line})
            _save(d / "outbox.json", outbox)
            return "held (no Telegram token file yet)"
        from .waves.alerts import telegram_send
        sender = lambda m: telegram_send(tg, m)  # noqa: E731
    sender(message)
    if flush:
        _save(d / "outbox.json", [])
    state["sent"].append(now.timestamp())
    if key:
        state["keys"][key] = now.timestamp()
    _save(d / "state.json", state)
    with open(d / "sent.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": now.isoformat(timespec="seconds"), "level": level, "key": key,
                             "chars": len(message), "ts": time.time()}) + "\n")
    return "sent"
