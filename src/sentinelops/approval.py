"""Human-in-the-loop approval gate.

v1: in-memory pending store + a console fallback. Wire the UI button to
/approve in main.py on Friday. When you migrate to Microsoft Agent Framework,
replace this with AF's native human-in-the-loop checkpoint.
"""
import threading

_pending: dict | None = None
_decision: bool | None = None
_event = threading.Event()


def set_pending(proposal: dict) -> None:
    global _pending, _decision
    _pending, _decision = proposal, None
    _event.clear()


def get_pending() -> dict | None:
    return _pending


def resolve(approved: bool) -> None:
    global _decision, _pending
    _decision = approved
    _pending = None          # clear the slot so the gate stops showing this proposal
    _event.set()


def request_approval(proposal: dict, console: bool = True, timeout: float = 300) -> bool:
    """Block until the proposed action is approved or rejected."""
    set_pending(proposal)
    if console:
        ans = input(f"\n[APPROVAL] SentinelOps proposes: {proposal}\nApply? [y/N] ").strip().lower()
        resolve(ans == "y")
    else:
        _event.wait(timeout=timeout)  # resolved via POST /approve
    return bool(_decision)
