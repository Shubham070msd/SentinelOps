"""FastAPI surface: Alertmanager webhook, health, approval endpoints, UI."""
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from . import approval
from . import incidents
from .config import settings

app = FastAPI(title="SentinelOps")
_UI = Path(__file__).resolve().parent.parent.parent / "ui" / "index.html"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/alert")
async def alert(request: Request, background: BackgroundTasks):
    """Receives an Alertmanager webhook and kicks off an investigation.

    Returns 202 immediately: the investigation blocks on human approval, so it
    must run off the event loop or POST /approve could never be served, and
    Alertmanager would time out and re-send the webhook.
    """
    payload = await request.json()
    alerts = payload.get("alerts", [payload])
    for a in alerts:
        labels = a.get("labels", a)
        # Lazy import so the app starts without Azure creds (Phase 0 smoke test).
        from .agent import handle_alert
        background.add_task(handle_alert, labels)
    return JSONResponse({"accepted": len(alerts)}, status_code=202)


@app.get("/pending")
def pending():
    return {"pending": approval.get_pending()}


@app.post("/approve")
def approve(approved: bool = True):
    approval.resolve(approved)
    return {"resolved": approved}


@app.get("/incidents")
def incident_feed():
    """Live + historical incidents and rollup stats for the dashboard."""
    return {"stats": incidents.stats(), "incidents": incidents.list_all()}


@app.get("/cluster")
def cluster():
    """Live pod inventory in the target namespace (cluster-health panel)."""
    from .tools import list_pods
    pods = list_pods(settings.target_namespace)
    return {"namespace": settings.target_namespace, "pods": pods}


@app.get("/", response_class=HTMLResponse)
def home():
    return _UI.read_text() if _UI.exists() else "<h1>SentinelOps</h1>"
