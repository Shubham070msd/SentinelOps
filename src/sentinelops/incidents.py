"""In-memory incident store so the dashboard can show live + historical state.

Thread-safe because handle_alert() runs on a background thread while the API
serves /incidents on the event loop. One process, resets on restart — that is
fine for the demo; swap for SQLite/Redis if you need durability.
"""
import datetime as _dt
import itertools
import threading

_lock = threading.Lock()
_incidents: dict[int, dict] = {}
_counter = itertools.count(1)


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def create(alert_name: str) -> int:
    """Open a new incident in the 'investigating' state and return its id."""
    with _lock:
        iid = next(_counter)
        _incidents[iid] = {
            "id": iid,
            "alert_name": alert_name,
            "status": "investigating",   # investigating | pending_approval | resolved | rejected | failed
            "root_cause": None,
            "remediation": None,
            "action_taken": None,
            "summary": "",
            "timeline": [],
            "started_at": _now(),
            "updated_at": _now(),
            "resolved_at": None,
        }
        return iid


def add_step(iid: int, text: str) -> None:
    with _lock:
        inc = _incidents.get(iid)
        if inc:
            inc["timeline"].append(text)
            inc["updated_at"] = _now()


def update(iid: int, **fields) -> None:
    terminal = {"resolved", "rejected", "failed"}
    with _lock:
        inc = _incidents.get(iid)
        if not inc:
            return
        inc.update(fields)
        inc["updated_at"] = _now()
        if fields.get("status") in terminal and not inc["resolved_at"]:
            inc["resolved_at"] = _now()


def get(iid: int) -> dict | None:
    with _lock:
        inc = _incidents.get(iid)
        return dict(inc) if inc else None


def list_all() -> list[dict]:
    """Most-recent first."""
    with _lock:
        return [dict(i) for i in sorted(_incidents.values(), key=lambda x: x["id"], reverse=True)]


def stats() -> dict:
    with _lock:
        items = list(_incidents.values())
        resolved = [i for i in items if i["status"] == "resolved"]
        durations = []
        for i in resolved:
            try:
                s = _dt.datetime.fromisoformat(i["started_at"])
                e = _dt.datetime.fromisoformat(i["resolved_at"])
                durations.append((e - s).total_seconds())
            except Exception:
                pass
        mttr = round(sum(durations) / len(durations), 1) if durations else None
        return {
            "total": len(items),
            "pending": sum(1 for i in items if i["status"] == "pending_approval"),
            "resolved": len(resolved),
            "rejected": sum(1 for i in items if i["status"] == "rejected"),
            "investigating": sum(1 for i in items if i["status"] == "investigating"),
            "mttr_seconds": mttr,
        }
