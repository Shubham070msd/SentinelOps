"""SentinelOps investigation loop (Groq function-calling baseline).

This is your MAIN BUILD TARGET for Tue-Wed: tighten the system prompt and the
investigation logic until the agent reliably reaches a correct root cause.
To get the Microsoft signal, later port this to Microsoft Agent Framework —
the tool functions below map 1:1 to AF function-tools, and approval.py maps to
AF's human-in-the-loop checkpoint.
"""
import json

from openai import OpenAI

from .config import settings
from . import tools
from . import incidents
from .approval import request_approval
from .postmortem import build_postmortem, post_to_teams

# Groq exposes an OpenAI-compatible API, so the standard client works as-is.
_client = OpenAI(
    base_url=settings.groq_base_url,
    api_key=settings.groq_api_key,
)

SYSTEM_PROMPT = """You are SentinelOps, an autonomous SRE on-call agent for Kubernetes.
A Prometheus alert just fired. Investigate using the provided tools (describe the
resource, read logs, list events, query metrics). Reason step by step to a single
most-likely ROOT CAUSE. Then output your conclusion as STRICT JSON only:
{"root_cause": "...", "remediation": {"action": "patch_memory_limit",
"deployment": "...", "container": "...", "new_limit": "256Mi"},
"summary": "..."}
Allowed actions: patch_memory_limit, restart_deployment. Pick the smallest safe fix.
Investigate before concluding. Do not invent values you have not observed."""

# Tool schemas exposed to the model -> dispatch map to the real functions.
_TOOL_SCHEMAS = [
    {"type": "function", "function": {"name": "describe_resource",
     "description": "Describe a pod or deployment (status, restarts, limits).",
     "parameters": {"type": "object", "properties": {
         "kind": {"type": "string"}, "name": {"type": "string"},
         "namespace": {"type": "string"}}, "required": ["kind", "name"]}}},
    {"type": "function", "function": {"name": "get_pod_logs",
     "description": "Tail logs from a pod.",
     "parameters": {"type": "object", "properties": {
         "pod": {"type": "string"}, "namespace": {"type": "string"}},
         "required": ["pod"]}}},
    {"type": "function", "function": {"name": "get_recent_events",
     "description": "List recent events in a namespace.",
     "parameters": {"type": "object", "properties": {
         "namespace": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "query_prometheus",
     "description": "Run an instant PromQL query.",
     "parameters": {"type": "object", "properties": {
         "promql": {"type": "string"}}, "required": ["promql"]}}},
]

# Remediations the agent may execute. The system prompt states this limit, but
# logs/events fed to the model are untrusted input, so it is enforced here too.
_ALLOWED_ACTIONS = {
    "patch_memory_limit": tools.patch_memory_limit,
    "restart_deployment": tools.restart_deployment,
}

_DISPATCH = {
    "describe_resource": tools.describe_resource,
    "get_pod_logs": tools.get_pod_logs,
    "get_recent_events": tools.get_recent_events,
    "query_prometheus": tools.query_prometheus,
}


def handle_alert(alert: dict, max_steps: int = 8) -> dict:
    """Run the full loop: investigate -> propose -> approve -> remediate -> postmortem.

    Records progress to the incident store at every step so the dashboard can
    animate the investigation live.
    """
    alert_name = alert.get("alertname", "Incident")
    iid = incidents.create(alert_name)
    timeline = [f"alert received: {alert_name}"]
    incidents.add_step(iid, timeline[-1])
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Alert payload: {json.dumps(alert)}"},
    ]

    final = None
    for _ in range(max_steps):
        resp = _client.chat.completions.create(
            model=settings.groq_model,
            messages=messages, tools=_TOOL_SCHEMAS, tool_choice="auto",
        )
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))
        if msg.tool_calls:
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments or "{}")
                result = _DISPATCH[tc.function.name](**args)
                ok = not str(result).startswith("ERROR")
                step = f"{tc.function.name}({args}) -> {'ok' if ok else result}"
                timeline.append(step)
                incidents.add_step(iid, step)
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": str(result)[:4000]})
            continue
        final = msg.content
        break

    diagnosis = _parse(final)
    root_cause = diagnosis.get("root_cause", "TBD")
    timeline.append(f"root cause: {root_cause}")
    incidents.add_step(iid, timeline[-1])

    action_taken = "none (rejected)"
    rem = diagnosis.get("remediation") or {}
    if rem:
        incidents.update(iid, status="pending_approval", root_cause=root_cause,
                         remediation=dict(rem), summary=diagnosis.get("summary", ""))
        approved = request_approval(rem, console=False)
        action = rem.pop("action", "")
        if approved:
            fn = _ALLOWED_ACTIONS.get(action)
            action_taken = fn(**rem) if fn else f"blocked: {action!r} is not an allowed action"
            timeline.append(f"remediation: {action_taken}")
            incidents.add_step(iid, timeline[-1])
            incidents.update(iid, status="resolved", action_taken=action_taken)
        else:
            incidents.update(iid, status="rejected", action_taken=action_taken)
    else:
        incidents.update(iid, status="failed", root_cause=root_cause,
                         summary=diagnosis.get("summary", ""))

    incident = {
        "alert_name": alert_name,
        "resource": rem.get("deployment", "unknown"),
        "root_cause": root_cause,
        "action_taken": action_taken,
        "summary": diagnosis.get("summary", ""),
        "timeline": timeline,
    }
    post_to_teams(build_postmortem(incident))
    return incident


def _parse(text: str | None) -> dict:
    if not text:
        return {}
    try:
        return json.loads(text[text.find("{"): text.rfind("}") + 1])
    except Exception:
        return {"root_cause": text}
