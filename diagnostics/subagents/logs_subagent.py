"""
Queries logs for a service and runs the filter_logs_by_error_level script.
Zero LLM calls — pure filtering + clustering.

If infra_metadata["logs_url"] is set, queries the real toy target_app
live. Otherwise falls back to the fixture file with simulated latency —
same pattern as metrics_subagent.py.
"""
import asyncio
import time

from diagnostics.fixtures_loader import load_fixture
from diagnostics.scripts.filter_logs_by_error_level import filter_logs_by_error_level
from diagnostics.subagents.base import Evidence

SIMULATED_QUERY_LATENCY_SECONDS = 0.5  # log backends are typically slower than metrics backends


async def run(infra_metadata: dict, service: str) -> Evidence:
    start = time.monotonic()

    logs_url = infra_metadata.get("logs_url")
    if logs_url:
        lines = await _query_live_logs(logs_url)
        stream = f"live:{logs_url}"
    else:
        await asyncio.sleep(SIMULATED_QUERY_LATENCY_SECONDS)
        logs = load_fixture("fake_logs.json")
        stream = infra_metadata["log_stream"]
        lines = logs.get(stream, [])

    clusters = filter_logs_by_error_level(lines, min_level="WARN")

    if clusters:
        top = clusters[:3]  # cap what goes into the LLM prompt later
        finding = "; ".join(
            f"[{c.level}] '{c.normalized_msg}' x{c.count}" for c in top
        )
    else:
        finding = "no WARN/ERROR level logs found"

    latency_ms = (time.monotonic() - start) * 1000
    return Evidence(
        subagent="logs",
        finding=finding,
        raw={"clusters": [c.__dict__ for c in clusters], "stream": stream},
        latency_ms=round(latency_ms, 1),
    )


async def _query_live_logs(url: str) -> list[dict]:
    import httpx

    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()
