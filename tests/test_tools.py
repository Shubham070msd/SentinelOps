"""Minimal tests so CI is green from day one. Expand as you build."""
from reflex.postmortem import build_postmortem


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
