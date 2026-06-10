"""Write actions. Only ever called AFTER human approval (see approval.py)."""
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


def patch_memory_limit(deployment: str, container: str, new_limit: str,
                       namespace: str = "default") -> str:
    """Raise a container's memory limit — the fix for the OOMKill demo."""
    _load()
    body = {"spec": {"template": {"spec": {"containers": [
        {"name": container, "resources": {"limits": {"memory": new_limit}}}
    ]}}}}
    try:
        client.AppsV1Api().patch_namespaced_deployment(deployment, namespace, body)
        return f"patched {deployment}/{container} memory limit -> {new_limit}"
    except Exception as e:
        return f"ERROR patching {deployment}: {e}"


def restart_deployment(deployment: str, namespace: str = "default") -> str:
    _load()
    import datetime as _dt
    body = {"spec": {"template": {"metadata": {"annotations": {
        "reflex/restartedAt": _dt.datetime.utcnow().isoformat()
    }}}}}
    try:
        client.AppsV1Api().patch_namespaced_deployment(deployment, namespace, body)
        return f"restarted {deployment}"
    except Exception as e:
        return f"ERROR restarting {deployment}: {e}"
