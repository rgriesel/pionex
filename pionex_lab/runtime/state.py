"""Persisted lifecycle: SETUP -> RESEARCH -> PAPER -> LIVE_CANARY -> LIVE, plus
PAUSED, HALTED, UNWINDING, COMPLETE. Every transition is journaled with reason,
evidence, actor, time, and policy hash. No live transition follows from elapsed
time or target pressure; LIVE_* transitions are refused in this build."""
from __future__ import annotations

STATES = ("SETUP", "RESEARCH", "PAPER", "LIVE_CANARY", "LIVE", "PAUSED", "HALTED", "UNWINDING", "COMPLETE")
ALLOWED = {
    "SETUP": {"RESEARCH", "PAPER", "HALTED"},
    "RESEARCH": {"PAPER", "PAUSED", "HALTED"},
    "PAPER": {"RESEARCH", "PAUSED", "HALTED", "UNWINDING", "LIVE_CANARY"},
    "PAUSED": {"PAPER", "HALTED", "UNWINDING"},
    "HALTED": {"PAPER", "UNWINDING"},
    "UNWINDING": {"COMPLETE", "HALTED"},
    "LIVE_CANARY": {"PAUSED", "HALTED", "UNWINDING", "PAPER"},
    "LIVE": {"PAUSED", "HALTED", "UNWINDING", "PAPER"},
    "COMPLETE": set(),
}


class TransitionError(RuntimeError):
    pass


def current_state(journal) -> str:
    last = journal.last("STATE_TRANSITION")
    return last[2]["to"] if last else "SETUP"


def transition(journal, to: str, reason: str, evidence: dict, actor: str, policy_hash: str, now: int,
               live_preflight: list | None = None) -> str:
    frm = current_state(journal)
    if to not in STATES:
        raise TransitionError(f"unknown state {to}")
    if frm == to:
        return frm
    if to not in ALLOWED[frm]:
        raise TransitionError(f"transition {frm} -> {to} not allowed")
    if to in ("LIVE_CANARY", "LIVE"):
        failing = [g["gate"] for g in (live_preflight or [{"gate": "preflight_missing", "status": "FAIL"}])
                   if g["status"] != "PASS"]
        raise TransitionError(f"live transition refused; failing gates: {failing or ['no live execution path']}")
    if frm == "HALTED" and to == "PAPER" and not actor.startswith("human:"):
        raise TransitionError("leaving HALTED requires a reviewed human decision")
    journal.append("STATE_TRANSITION", {"from": frm, "to": to, "reason": reason, "evidence": evidence,
                                        "actor": actor, "policy_hash": policy_hash}, now)
    return to
