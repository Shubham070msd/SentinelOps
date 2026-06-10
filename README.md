# Reflex — autonomous on-call SRE agent

A Kubernetes alert fires → **Reflex** investigates the cluster on its own
(describe, logs, events, metrics), reasons to a root cause, **proposes a fix and
waits for your approval**, applies it, verifies recovery, and writes the
postmortem to Teams.

**Hackathon:** Microsoft Build AI — theme *AI-Powered Production Function*
(stretch: *Agent Swarms*). The human approval gate is the responsible-AI story.

## Stack
- Python 3.11 · FastAPI (Alertmanager webhook)
- **Azure OpenAI** (GPT-4o) — function-calling baseline; port to **Microsoft
  Agent Framework** for function-tools + native human-in-the-loop
- Kubernetes (local `kind` for the demo, AKS-portable) via the official Python client
- Prometheus HTTP API · OpenTelemetry (agent's own traces) · Teams webhook
- Docker · GitHub Actions

## Layout
```
src/reflex/
  main.py          FastAPI: /alert webhook, /pending, /approve, UI
  agent.py         investigation loop  <-- MAIN BUILD TARGET (Tue-Wed)
  approval.py      human-in-the-loop gate
  postmortem.py    markdown + Teams
  tools/           describe / logs / events / prometheus / remediation
deploy/demo/       memory-hog.yaml (OOMKill) + sample alert payload
deploy/aks/        AKS deployment notes
ui/index.html      approve button (build out Friday)
tests/             keep CI green
```

## Phase 0 — tonight (de-risk the two killers)
1. `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
2. `cp .env.example .env` and fill in your **Azure OpenAI** values — confirm the
   deployment actually responds tonight. If access is blocked, raise it now.
3. Spin a local cluster and inject the failure:
   ```bash
   kind create cluster
   kubectl apply -f deploy/demo/memory-hog.yaml
   kubectl get pods -w        # confirm it OOMKills into CrashLoopBackOff
   ```
4. Smoke-test the skeleton runs:
   ```bash
   PYTHONPATH=src uvicorn reflex.main:app --reload --port 8080
   curl localhost:8080/health
   ```

## The 6-day plan
- **Mon** — Phase 0 above: repo runs, cluster OOMKills, Azure confirmed.
- **Tue–Wed** — make `agent.py` reach a correct root cause end-to-end. POST the
  sample payload: `curl -XPOST localhost:8080/alert -d @deploy/demo/alertmanager-webhook.json -H 'content-type: application/json'`
- **Thu** — close the loop: approval → `patch_memory_limit` → pod healthy → postmortem to Teams.
- **Fri** — build out `ui/index.html` (live timeline + approve); turn on OpenTelemetry traces; README + architecture diagram.
- **Sat–Sun** — record a 2–4 min demo (inject → diagnose → approve → fix → postmortem); write the pitch; **submit Sat night / Sun morning, not 11pm Sunday.**

> AKS: demo on `kind` for reliability, ship the AKS manifests as proof of portability.
> Swarm stretch (only after v1 is recorded): split into planner + metrics/logs
> investigators + remediator + scribe via Agent Framework graph workflows.
