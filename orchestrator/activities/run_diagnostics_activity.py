"""
Temporal activity wrapping diagnostics.run_diagnostics — the parallel
metrics/logs/deploy_history/runbook fan-out we built and verified in
Phase 2 slice 1. No new business logic here; this is purely the Temporal
plumbing around already-proven code.

As of slice 2 part 2, fetches the FULL Postgres-backed service_registry
(needed for deploy_history_subagent's dependency walk) and passes it in
explicitly, rather than letting run_diagnostics() fall back to the JSON
fixture. This is what makes checkout-api's metrics/logs subagents query
the live toy target_app.

Returns list[dict] rather than list[Evidence] — Temporal's default data
converter can round-trip dataclasses, but converting to plain dicts here
keeps the wire format simple and avoids relying on that machinery.

Timeout is set generously (30s) relative to the ~0.8s this actually took
in testing, to leave headroom now that metrics/logs subagents make real
HTTP calls to target_app instead of pure in-memory fixture reads.
"""
from dataclasses import dataclass, asdict

from temporalio import activity

from diagnostics.run_diagnostics import run_diagnostics
from shared.service_registry_repo import get_service_registry


@dataclass
class RunDiagnosticsInput:
    service: str
    alert_type: str


@activity.defn
async def run_diagnostics_activity(input: RunDiagnosticsInput) -> list[dict]:
    registry = get_service_registry()
    evidence, wall_ms = await run_diagnostics(input.service, input.alert_type, service_registry=registry)
    activity.logger.info(f"diagnostics parallel fan-out wall time: {wall_ms}ms")
    return [asdict(e) for e in evidence]
