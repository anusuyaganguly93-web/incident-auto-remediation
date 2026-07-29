"""
Fans out metrics/logs/deploy_history/runbook subagents in PARALLEL.

This is not an optimization — per the locked latency budget (20s/call,
measured), running these sequentially would burn 4x a single subagent's
latency before even reaching decision + comment generation, which alone
would blow the 90s p99 for most incidents. Parallel fan-out is a hard
requirement, not a nice-to-have.
"""
import asyncio
import time

from diagnostics.fixtures_loader import load_fixture
from diagnostics.subagents import metrics_subagent, logs_subagent, deploy_history_subagent, runbook_subagent
from diagnostics.subagents.base import Evidence


async def run_diagnostics(
    service: str, alert_type: str, service_registry: dict | None = None
) -> tuple[list[Evidence], float]:
    """
    `service_registry`, when provided, overrides the fixture load — this is
    how the real Temporal path (orchestrator/activities/run_diagnostics_activity.py)
    injects the Postgres-backed registry instead. diagnostics/execute.py and
    tests/test_diagnostics.py call this with no service_registry arg, so they
    keep using the fixture exactly as before, unaffected by this change.
    """
    if service_registry is None:
        service_registry = load_fixture("service_registry.json")

    infra_metadata = service_registry.get(service)
    if infra_metadata is None:
        raise ValueError(f"no service_registry entry for service={service}")

    start = time.monotonic()

    metrics_result, logs_result, deploy_result = await asyncio.gather(
        metrics_subagent.run(infra_metadata, service),
        logs_subagent.run(infra_metadata, service),
        deploy_history_subagent.run(infra_metadata, service, service_registry),
    )

    # runbook retrieval benefits from what the other subagents already found,
    # so it runs after the first round rather than in the same gather() —
    # still only 2 sequential "rounds" total, well within the 4-round budget.
    evidence_so_far = " ".join([metrics_result.finding, logs_result.finding, deploy_result.finding])
    runbook_result = await runbook_subagent.run(infra_metadata, service, alert_type, evidence_so_far)

    total_wall_time_ms = (time.monotonic() - start) * 1000
    all_evidence = [metrics_result, logs_result, deploy_result, runbook_result]
    return all_evidence, round(total_wall_time_ms, 1)
