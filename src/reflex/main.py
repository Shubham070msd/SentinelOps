"""FastAPI surface: Alertmanager webhook, health, approval endpoints, UI."""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from . import approval

app = FastAPI(title="Reflex")
_UI = Path(__file__).resolve().parent.parent.parent / "ui" / "index.html"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/alert")
async def alert(request: Request):
    """Receives an Alertmanager webhook and kicks off an investigation."""
    payload = await request.json()
    alerts = payload.get("alerts", [payload])
    results = []
    for a in alerts:
        labels = a.get("labels", a)
        # Lazy import so the app starts without Azure creds (Phase 0 smoke test).
        from .agent import handle_alert
        results.append(handle_alert(labels))
    return {"handled": len(results), "incidents": results}


@app.get("/pending")
def pending():
    return {"pending": approval.get_pending()}


@app.post("/approve")
def approve(approved: bool = True):
    approval.resolve(approved)
    return {"resolved": approved}


@app.get("/", response_class=HTMLResponse)
def home():
    return _UI.read_text() if _UI.exists() else "<h1>Reflex</h1>"
