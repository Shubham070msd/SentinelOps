"""Minimal tests so CI is green from day one. Expand as you build."""
import threading
import time

from reflex import approval
from reflex.postmortem import build_postmortem


def test_approval_gate_resolves_via_api_path():
    """request_approval(console=False) must unblock when /approve calls resolve()."""
    outcome = {}

    def wait_for_decision():
        outcome["approved"] = approval.request_approval(
            {"action": "patch_memory_limit"}, console=False, timeout=5
        )

    t = threading.Thread(target=wait_for_decision)
    t.start()
    for _ in range(100):
        if approval.get_pending():
            break
        time.sleep(0.05)
    assert approval.get_pending() == {"action": "patch_memory_limit"}
    approval.resolve(True)
    t.join(timeout=5)
    assert outcome["approved"] is True


def test_postmortem_has_sections():
    md = build_postmortem({
        "alert_name": "KubePodCrashLooping",
        "resource": "memory-hog",
        "root_cause": "OOMKilled: limit too low",
        "action_taken": "patched limit -> 256Mi",
        "summary": "fixed",
        "timeline": ["alert received", "patched"],
    })
    assert "Root cause" in md
    assert "Action taken" in md
    assert "memory-hog" in md
