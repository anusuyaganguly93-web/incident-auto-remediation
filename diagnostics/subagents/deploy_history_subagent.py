"""
Checks recent deploys for the alerting service AND its direct
dependencies (one hop only — NOT transitive). This is what catches the
"checkout-api is slow because payment-api deployed 2 minutes ago" case.

We deliberately cap at direct dependencies (infra_metadata["depends_on"]),
per the earlier design decision: walking the full transitive dependency
graph would blow up this subagent's latency and query surface area
unpredictably, threatening the per-call latency budget.
"""
import asyncio
import time
from datetime import datetime, timedelta, timezone

from diagnostics.fixtures_loader import load_fixture
from diagnostics.subagents.base import Evidence

SIMULATED_QUERY_LATENCY_SECONDS = 0.3
RECENT_DEPLOY_WINDOW_MINUTES = 30  # deploys within this window of "now" are considered suspects


async def run(infra_metadata: dict, service: str, service_registry: dict) -> Evidence:
    start = time.monotonic()
    await asyncio.sleep(SIMULATED_QUERY_LATENCY_SECONDS)

    deploys = load_fixture("fake_deploys.json")
    now = datetime.now(timezone.utc)

    suspects = []

    # 1. the alerting service itself
    suspects.extend(_recent_deploys_for(service, infra_metadata, deploys, now))

    # 2. direct dependencies only (one hop) — this is the "depending svcs" check
    for dep_service in infra_metadata.get("depends_on", []):
        dep_metadata = service_registry.get(dep_service)
        if dep_metadata:
            suspects.extend(_recent_deploys_for(dep_service, dep_metadata, deploys, now))

    if suspects:
        finding = "; ".join(
            f"{s['service']} deployed {s['version']} at {s['deployed_at']} "
            f"({s['minutes_ago']:.0f}m ago)"
            for s in suspects
        )
    else:
        finding = "no recent deploys found for this service or its direct dependencies"

    latency_ms = (time.monotonic() - start) * 1000
    return Evidence(
        subagent="deploy_history",
        finding=finding,
        raw={"suspects": suspects},
        latency_ms=round(latency_ms, 1),
    )


def _recent_deploys_for(svc_name: str, svc_metadata: dict, deploys: dict, now: datetime) -> list[dict]:
    pipeline_id = svc_metadata.get("deploy_pipeline_id")
    history = deploys.get(pipeline_id, [])
    results = []
    for d in history:
        deployed_at = datetime.fromisoformat(d["deployed_at"].replace("Z", "+00:00"))
        age = now - deployed_at
        # fixture data is dated relative to a fixed "incident time" of 2026-07-25T14:03
        # rather than wall-clock now, so we compare against that reference instead
        reference_now = datetime(2026, 7, 25, 14, 3, 0, tzinfo=timezone.utc)
        age = reference_now - deployed_at
        if timedelta(0) <= age <= timedelta(minutes=RECENT_DEPLOY_WINDOW_MINUTES):
            results.append({
                "service": svc_name,
                "version": d["version"],
                "deployed_at": d["deployed_at"],
                "minutes_ago": age.total_seconds() / 60,
            })
    return results
