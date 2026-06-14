"""Read-only cluster inspection tools the agent calls during investigation.

Backed by the official Kubernetes Python client. Loads in-cluster config when
running inside the cluster, otherwise your local kubeconfig (the kind cluster).
"""
from kubernetes import client, config as k8s_config

_loaded = False


def _load():
    global _loaded
    if _loaded:
        return
    try:
        k8s_config.load_incluster_config()
    except Exception:
        k8s_config.load_kube_config()
    _loaded = True


def describe_resource(kind: str, name: str, namespace: str = "default") -> str:
    """Summarize a pod or deployment: status, restarts, last-terminated reason, limits."""
    _load()
    kind = kind.lower()
    try:
        if kind == "pod":
            p = client.CoreV1Api().read_namespaced_pod(name, namespace)
            lines = [f"Pod {name} phase={p.status.phase}"]
            for cs in (p.status.container_statuses or []):
                last = cs.last_state.terminated
                lines.append(
                    f"  container={cs.name} restarts={cs.restart_count} ready={cs.ready}"
                    + (f" lastTerminated={last.reason}(exit {last.exit_code})" if last else "")
                )
            for c in p.spec.containers:
                lim = (c.resources.limits or {}) if c.resources else {}
                lines.append(f"  spec {c.name} limits={dict(lim)}")
            return "\n".join(lines)
        if kind == "deployment":
            d = client.AppsV1Api().read_namespaced_deployment(name, namespace)
            return (f"Deployment {name} replicas={d.status.ready_replicas}/{d.spec.replicas} "
                    f"image={d.spec.template.spec.containers[0].image}")
        return f"Unsupported kind: {kind}"
    except Exception as e:  # surface the error to the agent, don't crash the loop
        return f"ERROR describing {kind}/{name}: {e}"


def list_pods(namespace: str = "default") -> list[dict]:
    """Live pod inventory for the dashboard's cluster-health panel."""
    _load()
    try:
        pods = client.CoreV1Api().list_namespaced_pod(namespace).items
        out = []
        for p in pods:
            statuses = p.status.container_statuses or []
            restarts = sum(cs.restart_count for cs in statuses)
            ready = sum(1 for cs in statuses if cs.ready)
            reason = p.status.phase
            for cs in statuses:
                w = cs.state.waiting if cs.state else None
                if w and w.reason:
                    reason = w.reason       # e.g. CrashLoopBackOff
            out.append({
                "name": p.metadata.name,
                "phase": p.status.phase,
                "reason": reason,
                "ready": f"{ready}/{len(statuses) or 1}",
                "restarts": restarts,
                "healthy": p.status.phase == "Running" and ready == len(statuses) and len(statuses) > 0,
            })
        return sorted(out, key=lambda x: (x["healthy"], x["name"]))
    except Exception as e:
        return [{"name": f"ERROR: {e}", "phase": "-", "reason": "-",
                 "ready": "-", "restarts": 0, "healthy": False}]


def get_pod_logs(pod: str, namespace: str = "default", tail_lines: int = 100) -> str:
    _load()
    try:
        return client.CoreV1Api().read_namespaced_pod_log(
            pod, namespace, tail_lines=tail_lines, previous=False
        )
    except Exception as e:
        return f"ERROR reading logs for {pod}: {e}"


def get_recent_events(namespace: str = "default") -> str:
    _load()
    try:
        evs = client.CoreV1Api().list_namespaced_event(namespace).items
        evs = sorted(evs, key=lambda e: e.last_timestamp or e.event_time or 0)[-20:]
        return "\n".join(f"{e.type}/{e.reason}: {e.message}" for e in evs) or "(no events)"
    except Exception as e:
        return f"ERROR listing events: {e}"
