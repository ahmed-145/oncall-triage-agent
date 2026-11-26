import hashlib
import hmac
import os
import tempfile
import time
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field

from triage.domain import Evidence
from triage.engine import investigate
from triage.tools import TOOLS, collect

app = FastAPI()
DURATION = Histogram("triage_investigation_duration_seconds", "Investigation duration")
TOKENS = Counter("triage_model_tokens_total", "Model tokens")
INVESTIGATIONS = Counter("triage_investigations_total", "Reports by model status", ["model"])


class Alert(BaseModel):
    status: Literal["firing", "resolved"]
    startsAt: str = Field(max_length=64)
    fingerprint: str = Field(max_length=128)
    labels: dict[str, str] = Field(max_length=30)


class Notification(BaseModel):
    alerts: list[Alert] = Field(max_length=20)


@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/alerts")
def webhook(notification: Notification, authorization: str = Header(default="")) -> dict:
    secret = os.environ["WEBHOOK_TOKEN"]
    if not hmac.compare_digest(authorization.encode(), f"Bearer {secret}".encode()):
        raise HTTPException(401)
    folder = Path(os.getenv("REPORT_DIR", "reports"))
    folder.mkdir(parents=True, exist_ok=True)
    generated = []
    for alert in notification.alerts:
        if alert.status != "firing":
            continue
        incident = hashlib.sha256(f"{alert.fingerprint}|{alert.startsAt}".encode()).hexdigest()[:20]
        target = folder / f"{incident}.md"
        if not target.exists():
            started = time.monotonic()

            alert_name = alert.labels.get("alertname", "")[:120]
            trigger = Evidence("alertmanager", alert.startsAt, "", detail=alert_name)

            def evidence(event: Evidence = trigger) -> list[Evidence]:
                return [event, *collect()]

            state = investigate(incident, evidence, os.getenv("TRIAGE_MODE", "hybrid"),
                                graph=True, tool_calls=len(TOOLS), alert_name=alert_name)
            with tempfile.NamedTemporaryFile(mode="w", dir=folder, delete=False) as handle:
                handle.write(state["report"])
            Path(handle.name).replace(target)
            DURATION.observe(time.monotonic() - started)
            TOKENS.inc(state["tokens"])
            INVESTIGATIONS.labels(state["model_status"]).inc()
        generated.append(target.name)
    return {"reports": generated}
