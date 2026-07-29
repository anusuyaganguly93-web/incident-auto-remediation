"""
Queries metrics for a service and runs the anomaly_detection script
against each series. Zero LLM calls — pure query + statistics.

If infra_metadata["metrics_url"] is set (populated for checkout-api in
shared/service_registry_seed.py), queries the real toy target_app live.
Otherwise falls back to the fixture file with simulated latency — this is
what keeps diagnostics/execute.py and tests/test_diagnostics.py working
unchanged from slice 1.
"""
import asyncio
import time

from diagnostics.fixtures_loader import load_fixture
from diagnostics.scripts.anomaly_detection import detect_anomaly
from diagnostics.subagents.base import Evidence

SIMULATED_QUERY_LATENCY_SECONDS = 0.4  # stand-in for a real metrics backend round trip


async def run(infra_metadata: dict, service: str) -> Evidence:
    start = time.monotonic()

    metrics_url = infra_metadata.get("metrics_url")
    if metrics_url:
        series = await _query_live_metrics(metrics_url)
        namespace = f"live:{metrics_url}"
    else:
        await asyncio.sleep(SIMULATED_QUERY_LATENCY_SECONDS)
        metrics = load_fixture("fake_metrics.json")
        namespace = infra_metadata["metric_namespace"]
        series = metrics.get(namespace, {})

    anomalies = []
    for metric_name, values in series.items():
        try:
            result = detect_anomaly(values, metric_name)
        except ValueError:
            continue
        if result.is_anomalous:
            anomalies.append(result)

    if anomalies:
        finding = "; ".join(
            f"{a.metric_name} anomalous: {a.baseline_mean} -> {a.recent_mean} "
            f"({a.pct_change:+.1f}%, z={a.z_score})"
            for a in anomalies
        )
    else:
        finding = "no anomalies detected in queried metrics"

    latency_ms = (time.monotonic() - start) * 1000
    return Evidence(
        subagent="metrics",
        finding=finding,
        raw={"anomalies": [a.__dict__ for a in anomalies], "namespace": namespace},
        latency_ms=round(latency_ms, 1),
    )


async def _query_live_metrics(url: str) -> dict:
    # lazy import: keeps this module importable (and the fixture path
    # testable) without httpx installed, same pattern as elsewhere in
    # this codebase for optional/live-only dependencies
    import httpx

    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()
