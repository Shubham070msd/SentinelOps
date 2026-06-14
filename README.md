# SentinelOps — Autonomous On-Call SRE Agent

> **HackerEarth × Microsoft Build AI Day** — Theme: AI-Powered Production Function · Agentic Reliability

**SentinelOps** is an autonomous agent that acts as your on-call Site
Reliability Engineer for Kubernetes. A Prometheus/Alertmanager alert fires —
*"pod `memory-hog` is crash-looping (OOMKilled)"* — and instead of paging a
human at 3 a.m., the agent:

- **Investigates** the cluster on its own — describes the resource, tails pod
  logs, lists recent events, queries Prometheus metrics.
- **Reasons** step by step to a single most-likely **root cause**.
- **Proposes the smallest safe fix and waits for human approval** — it never
  mutates the cluster on its own.
- **Remediates** once approved (e.g. raise a memory limit, restart a
  deployment), then **writes a postmortem** to Microsoft Teams.

…all visible live in a browser dashboard with an **Approve / Reject** button.

---

## Core Innovation — The Trust Boundary

Most agent systems let the LLM both decide *and* act. SentinelOps draws a hard
line between **diagnosis** and **action**:

> **The LLM investigates and proposes. Deterministic code and a human decide
> what actually runs against the cluster.**

The agent uses an LLM (Groq · Llama 3.3 70B) to read signals and reason to a
root cause. But no write action ever touches the cluster unless it clears **two
non-negotiable gates**:

1. **A hardcoded allowlist** (`_ALLOWED_ACTIONS` in `agent.py`) — only
   `patch_memory_limit` and `restart_deployment` can ever execute. Logs and
   events are untrusted input fed to the model, so a prompt-injected or
   hallucinated action name is rejected **in code**, not just in the prompt.
2. **A human approval gate** (`approval.py`) — the proposed fix is parked as
   *pending* and the loop blocks until a human clicks **Approve** in the UI.

A model mistake can **never**:
- Run an arbitrary or destructive command against the cluster
- Apply *any* remediation without explicit human sign-off
- Act on a fix the operator rejected

---

## Technology Stack

| Layer | Choice |
|---|---|
| **Language** | Python 3.11 |
| **Web / API server** | FastAPI + Uvicorn — Alertmanager webhook, approval API, UI |
| **LLM provider** | Groq (Llama 3.3 70B Versatile) — free tier, fast inference, OpenAI-compatible API |
| **LLM client** | `openai` SDK pointed at Groq's `base_url` — swap providers with one config change |
| **Cluster access** | Official Kubernetes Python client (`kubernetes`) — in-cluster or local kubeconfig |
| **Metrics** | Prometheus HTTP API (`httpx`) |
| **Notifications** | Microsoft Teams incoming webhook (falls back to stdout) |
| **Frontend** | Single-file vanilla HTML/JS dashboard (`ui/index.html`) that polls `/pending` |
| **Packaging** | Docker · `kind` for local demo · AKS manifests for portability |

---

## Architecture

```
                          ┌──────────────────────────────────────────────┐
   Browser (ui/index.html)│  Dashboard: live pending action + Approve /   │
   ─────────────────────► │  Reject button (polls /pending every 2s)      │
                          └───────────────┬──────────────────────────────┘
                                          │ HTTP (JSON)
                          ┌───────────────▼──────────────────────────────┐
   main.py (FastAPI)      │  POST /alert (202 + background task)          │  ← runs the
   ─────────────────────► │  GET /pending · POST /approve · GET / (UI)    │    investigation
                          └───────────────┬──────────────────────────────┘    off the event loop
                                          │
                 ┌────────────────────────▼─────────────────────────────────┐
                 │  agent.py — handle_alert()   (THE INVESTIGATION LOOP)     │
                 │                                                            │
                 │   investigate ─► reason ─► PROPOSE ─► [approval] ─►        │
                 │   remediate ─► postmortem                                  │
                 └───┬───────────────┬───────────────┬────────────┬──────────┘
                     │               │               │            │
             ┌───────▼──────┐ ┌──────▼───────┐ ┌─────▼──────┐ ┌───▼──────────┐
             │ tools/kubectl│ │tools/promethe│ │ approval.py│ │ tools/       │
             │  describe /  │ │ -us query    │ │ (HUMAN     │ │ remediation  │
             │  logs /events│ │ (read-only)  │ │  GATE)     │ │ (write — after│
             │ (read-only)  │ └──────────────┘ └────────────┘ │  approval +   │
             └──────────────┘                                 │  allowlist)   │
                     │                                        └───────────────┘
                     │ Groq drives tool-calls         ┌──────────────────────┐
            ┌────────▼──────────┐                     │ postmortem.py → Teams │
            │ Groq (Llama 3.3   │                     │  markdown incident    │
            │ 70B) function-call│                     │  report               │
            └───────────────────┘                     └──────────────────────┘
```

**Key design seam:** the LLM *investigates and proposes* (read-only tools +
reasoning), but the **consequential action** — does anything run against the
cluster? — is gated by a **hardcoded allowlist** and a **human approval
checkpoint**. The model never patches a cluster on its own.

---

## Data Flow

**Incident state machine:**

```
ALERT FIRES ─► INVESTIGATING ─►(root cause)─► PROPOSED ─► [PENDING APPROVAL]
                                                              │
                                              approve ────────┤───► REMEDIATED ─► POSTMORTEM
                                              reject  ────────┘───► NO ACTION  ─► POSTMORTEM
```

**Step by step:**

1. Alertmanager (or `curl`) sends a webhook → `POST /alert` returns **202
   Accepted** immediately and spawns the investigation on a background task, so
   the event loop stays free to serve the approval call and Alertmanager never
   times out and re-sends.
2. The agent runs a **function-calling loop** (up to `max_steps`): Groq decides
   which read-only tool to call (`describe_resource`, `get_pod_logs`,
   `get_recent_events`, `query_prometheus`), the result is fed back, and it
   reasons until it emits a strict-JSON conclusion: `root_cause`, `remediation`,
   `summary`.
3. The proposed remediation is parked as **pending** (`approval.set_pending`)
   and the loop **blocks** waiting for a human decision.
4. The dashboard polls `/pending` every ~2 s and shows the proposed action.
5. The operator clicks **Approve** or **Reject** → `POST /approve` resolves the
   gate. On approval, the action is looked up in the **allowlist** and executed;
   anything not on the list is blocked.
6. A **postmortem** (markdown: root cause, action taken, full timeline) is
   posted to Teams — or printed to stdout if no webhook is configured.

---

## Project Structure

```
SentinelOps/
├── src/sentinelops/
│   ├── main.py              FastAPI: /alert webhook, /pending, /approve, UI
│   ├── agent.py             investigation loop + allowlist + Groq function-calling
│   ├── approval.py          human-in-the-loop gate (pending store + resolve)
│   ├── postmortem.py        markdown postmortem + Teams webhook
│   ├── config.py            env/.env settings (Groq, Prometheus, Teams, namespace)
│   └── tools/
│       ├── kubectl.py       describe_resource / get_pod_logs / get_recent_events (read)
│       ├── prometheus.py    query_prometheus — instant PromQL over the HTTP API (read)
│       └── remediation.py   patch_memory_limit / restart_deployment (write, post-approval)
├── ui/index.html            dashboard: live pending action + approve/reject
├── deploy/
│   ├── demo/memory-hog.yaml         OOMKill workload that crash-loops on command
│   ├── demo/alertmanager-webhook.json   sample firing alert payload
│   └── aks/README.md                AKS deployment notes (portability story)
├── tests/test_tools.py      unit tests (postmortem formatting + approval gate)
├── Dockerfile               container image
├── requirements.txt         Python dependencies
└── .env.example             configuration template (Groq key, Prometheus, Teams)
```

---

## Core Components

### Investigation loop — `src/sentinelops/agent.py`

`handle_alert(alert)` runs the full lifecycle: **investigate → propose →
approve → remediate → postmortem**. It exposes four **read-only** tools to Groq
via function-calling and lets the model drive the investigation, then enforces
the trust boundary on the way out:

| Tool exposed to the LLM | Backed by | Purpose |
|---|---|---|
| `describe_resource` | `tools/kubectl.py` | Pod/Deployment status, restarts, last-terminated reason, limits |
| `get_pod_logs` | `tools/kubectl.py` | Tail recent container logs |
| `get_recent_events` | `tools/kubectl.py` | Recent namespace events (e.g. `OOMKilling`) |
| `query_prometheus` | `tools/prometheus.py` | Instant PromQL query over the HTTP API |

**Key constraints enforced:**
- **Allowlist in code** — only `patch_memory_limit` and `restart_deployment`
  can execute; any other proposed action is `blocked`, regardless of what the
  model emits.
- **Approval-gated** — `request_approval(rem, console=False)` blocks the loop
  until `POST /approve` resolves it; rejection means `none (rejected)`.
- **Bounded** — `max_steps` caps the investigation so a loop can never run
  forever; tool errors are surfaced to the model as strings, not crashes.

### Human approval gate — `src/sentinelops/approval.py`

A small, thread-safe state machine: `set_pending(proposal)` parks the proposed
action, `get_pending()` powers the dashboard, and `resolve(approved)` (called by
`POST /approve`) unblocks the agent waiting on a `threading.Event`. This is the
responsible-AI checkpoint — **the agent always stops here before acting.**

### Remediation tools — `src/sentinelops/tools/remediation.py`

The only **write** actions, ever called *after* approval:
- **`patch_memory_limit(deployment, container, new_limit, namespace)`** — the
  fix for the OOMKill demo: raise a container's memory limit.
- **`restart_deployment(deployment, namespace)`** — rollout restart via an
  annotation bump.

Both load in-cluster config when running inside Kubernetes, otherwise the local
kubeconfig (the `kind` cluster), and return a human-readable result string.

### Server — `src/sentinelops/main.py`

- `POST /alert` — Alertmanager webhook; returns **202** and runs
  `handle_alert` as a FastAPI **background task** (off the event loop, so the
  approval endpoint stays reachable while the agent waits).
- `GET /pending` — the currently proposed action (powers the dashboard).
- `POST /approve?approved=true|false` — resolves the approval gate and resumes
  the agent.
- `GET /` — serves the single-file dashboard; `GET /health` — liveness probe.

---

## Setup and Run

**Requirements:** Python 3.11. A free **Groq** API key
([console.groq.com](https://console.groq.com)). For the live cluster demo:
Docker + [`kind`](https://kind.sigs.k8s.io) + `kubectl`.

```bash
# 1. Clone
git clone https://github.com/Shubham070msd/SentinelOps.git
cd SentinelOps

# 2. Install
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Configure the LLM (Groq is free and fast)
cp .env.example .env
# Edit .env:
#   GROQ_API_KEY=gsk_your_key_here
#   GROQ_MODEL=llama-3.3-70b-versatile

# 4. Run
PYTHONPATH=src uvicorn sentinelops.main:app --port 8080   # → http://localhost:8080
curl localhost:8080/health
```

**Switching LLM providers** is a config change only (Groq exposes an
OpenAI-compatible API, so any OpenAI-compatible endpoint works):

```bash
# Groq (used in this build — free tier)
GROQ_API_KEY=gsk_...   GROQ_MODEL=llama-3.3-70b-versatile   GROQ_BASE_URL=https://api.groq.com/openai/v1
# Point GROQ_BASE_URL at OpenAI, a local Ollama (/v1), or any compatible gateway to swap brains.
```

---

## End-to-End Demo (the live cluster loop)

This is what you record for the submission — inject a real failure, watch the
agent diagnose it, approve the fix, and see the pod recover.

```bash
# 1. Spin up a local cluster and inject the OOMKill
kind create cluster
kubectl apply -f deploy/demo/memory-hog.yaml
kubectl get pods -w        # watch it OOMKill into CrashLoopBackOff, then Ctrl-C

# 2. Start the agent (in another terminal)
PYTHONPATH=src uvicorn sentinelops.main:app --port 8080

# 3. Fire the alert and open the dashboard
curl -XPOST localhost:8080/alert \
  -d @deploy/demo/alertmanager-webhook.json -H 'content-type: application/json'
#   → open http://localhost:8080, review the proposed fix, click Approve
```

The agent investigates, proposes raising the memory limit, waits for your
**Approve**, patches the deployment, and posts the postmortem.

---

## Deploy to the Cloud

The repo ships a `Dockerfile`. Two good paths:

**Render (fastest public URL)**
1. Push to GitHub, then on [dashboard.render.com](https://dashboard.render.com):
   **New → Web Service → Docker**, connect this repo.
2. Set env var `GROQ_API_KEY` (and `GROQ_MODEL=llama-3.3-70b-versatile`).
3. When **Live**, open the URL — the dashboard and approval API are served.

**Azure Container Apps (best Microsoft signal)**
```bash
az login
az group create -n sentinelops-rg -l eastus
az containerapp up \
  --name sentinelops --resource-group sentinelops-rg \
  --source . --ingress external --target-port 8080 \
  --env-vars GROQ_API_KEY=<your-key> GROQ_MODEL=llama-3.3-70b-versatile
```

> **Note:** the deployed web service hosts the UI and approval API. To remediate
> a real cluster, run the agent **inside** that cluster (in-cluster config is
> picked up automatically) — see `deploy/aks/README.md` for the AKS path.

---

## Configuration Reference

Settings load from environment / `.env` (`src/sentinelops/config.py`):

| Variable | Default | Meaning |
|---|---|---|
| `GROQ_API_KEY` | `""` | Your Groq API key. **Required** for the agent to reason. |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | The model the agent runs on. |
| `GROQ_BASE_URL` | `https://api.groq.com/openai/v1` | OpenAI-compatible endpoint — change to swap providers. |
| `PROMETHEUS_URL` | `http://localhost:9090` | Prometheus HTTP API for the `query_prometheus` tool. |
| `TEAMS_WEBHOOK_URL` | `""` | Teams incoming webhook for postmortems. Blank ⇒ log to stdout. |
| `TARGET_NAMESPACE` | `default` | Kubernetes namespace the agent operates in. |

**Allowed remediation actions** (enforced in `agent.py`):

| Action | Effect |
|---|---|
| `patch_memory_limit` | Raise a container's memory limit (the OOMKill fix). |
| `restart_deployment` | Trigger a rollout restart of a deployment. |

---

## Testing

```bash
PYTHONPATH=src python -m pytest tests/ -q
```

Covers the postmortem formatter and the **approval gate's API-resolved path** —
the regression test that proves the loop unblocks when `/approve` resolves it
(the exact UI flow), guarding against the deadlock the threaded design fixes.

---

## Future Scope

**Near-term:**
- Live timeline UI — stream each investigation step into the dashboard as it happens
- OpenTelemetry traces of the agent's own reasoning for observability
- More remediation actions behind the allowlist (scale replicas, roll back image, cordon node)
- Automated recovery verification — re-check pod health after the fix and report success/failure

**Medium-term:**
- Port the baseline loop to the **Microsoft Agent Framework** — function-tools +
  native human-in-the-loop checkpoint (the tools map 1:1 today)
- Per-incident approval keying so concurrent alerts can't overwrite each other
- Shared-secret / auth on `/alert` and `/approve`
- Real Alertmanager wiring with a runbook library per alert type

**Long-term:**
- **Agent swarm** — split into planner + metrics/logs investigators + remediator
  + scribe via Agent Framework graph workflows
- Cross-cluster fleet operation with org-wide incident intelligence
- Confidence-gated auto-remediation for well-understood, low-risk fixes

---

## Author

**Manjunath Huddar**

| | |
|---|---|
| **GitHub** | [github.com/Shubham070msd](https://github.com/Shubham070msd) |
| **Portfolio** | [manjunath-07.vercel.app](https://manjunath-07.vercel.app) |
| **LinkedIn** | [linkedin.com/in/manjunath-huddar-devops](https://linkedin.com/in/manjunath-huddar-devops) |

Built for **HackerEarth × Microsoft Build AI Day** — Theme: AI-Powered Production Function

---

## Feature Highlights

### Dashboard (`ui/index.html`)
- **Live pending action** — the proposed remediation, polled from `/pending` every ~2s
- **Approve / Reject** — one click resolves the human approval gate and resumes the agent
- **Zero build step** — single-file vanilla HTML/JS, no framework

### The Trust Boundary
- **Hardcoded action allowlist** — only vetted remediations can ever execute
- **Mandatory human approval** — nothing touches the cluster without a click
- **Untrusted-input safe** — pod logs/events feed the model but can't smuggle in actions

### Resilient by design
- `POST /alert` returns **202** and investigates in the background — no webhook timeouts/retries
- Tool errors are surfaced to the model as strings, never fatal to the loop
- Bounded investigation (`max_steps`) so a loop can never run forever

### Docker Support
```bash
docker build -t sentinelops .
docker run -p 8080:8080 --env-file .env sentinelops
```

### Kubernetes Portability
- In-cluster config auto-detected when deployed inside Kubernetes
- `deploy/demo/` ships a reproducible OOMKill workload + sample alert payload
- `deploy/aks/` documents the AKS deployment path
