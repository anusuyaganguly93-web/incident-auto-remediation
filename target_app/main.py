"""
A toy service standing in for `checkout-api`. Exposes real /metrics and
/logs endpoints that the metrics_subagent / logs_subagent can query live,
plus a /chaos endpoint to inject latency spikes or elevated error rates —
this is what makes the demo GIF possible: inject chaos, fire an alert,
watch the diagnostic subagents pull real (if simulated) evidence instead
of static JSON fixtures.

Run standalone: uvicorn target_app.main:app --port 8080
Or via docker-compose (see docker-compose.yml).
"""
import asyncio
import random
from collections import deque
from datetime import datetime, timezone

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Toy Target Service (checkout-api stand-in)")

MAX_SAMPLES = 30
latency_samples: deque = deque(maxlen=MAX_SAMPLES)
error_samples: deque = deque(maxlen=MAX_SAMPLES)
log_lines: deque = deque(maxlen=50)

chaos_state = {"latency": False, "errors": False}


class ChaosRequest(BaseModel):
    latency: bool | None = None
    errors: bool | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tick() -> None:
    """One simulated traffic sample. Called every ~1s by the background loop."""
    if chaos_state["latency"]:
        lat = max(random.gauss(900, 25), 1)
        err = max(random.gauss(4.5, 0.4), 0)
        log_lines.append({
            "ts": _now_iso(), "level": "ERROR",
            "msg": "upstream call to payment-api timed out after 5000ms",
        })
    else:
        lat = max(random.gauss(120, 5), 1)
        err = max(random.gauss(0.2, 0.05), 0)
        log_lines.append({
            "ts": _now_iso(), "level": "INFO",
            "msg": f"request completed in {lat:.0f}ms",
        })

    if chaos_state["errors"]:
        err = max(err, random.gauss(6.0, 0.5))
        log_lines.append({"ts": _now_iso(), "level": "ERROR", "msg": "returned 503 to caller"})

    latency_samples.append(round(lat, 1))
    error_samples.append(round(err, 2))


async def _traffic_loop() -> None:
    # seed a full baseline immediately so anomaly_detection has enough
    # samples to work with right away, rather than waiting ~15-30s
    for _ in range(15):
        _tick()
    while True:
        await asyncio.sleep(1.0)
        _tick()


@app.on_event("startup")
async def startup() -> None:
    asyncio.create_task(_traffic_loop())


@app.get("/health")
def health():
    return {"status": "ok", "chaos": chaos_state}


@app.get("/metrics")
def metrics():
    """Shape matches diagnostics/fixtures/fake_metrics.json's per-service entries,
    so metrics_subagent's anomaly_detection call is unchanged either way."""
    return {"p99_latency_ms": list(latency_samples), "error_rate_pct": list(error_samples)}


@app.get("/logs")
def logs():
    """Shape matches diagnostics/fixtures/fake_logs.json's per-stream entries."""
    return list(log_lines)


@app.post("/chaos")
def set_chaos(req: ChaosRequest):
    if req.latency is not None:
        chaos_state["latency"] = req.latency
    if req.errors is not None:
        chaos_state["errors"] = req.errors
    return {"chaos": chaos_state}
