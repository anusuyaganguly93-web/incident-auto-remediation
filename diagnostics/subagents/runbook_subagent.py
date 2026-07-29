"""
Finds the most relevant runbook for this incident. In production this
is a pgvector cosine-similarity search over embedded runbook summaries
(one embedding call, cheap/fast, counted separately from the LLM
reasoning-call budget per our design discussion). Here it's a keyword
overlap scorer against the fixture runbook index — same interface,
swappable implementation later without touching callers.
"""
import asyncio
import time

from diagnostics.fixtures_loader import load_fixture
from diagnostics.subagents.base import Evidence

SIMULATED_QUERY_LATENCY_SECONDS = 0.3


async def run(infra_metadata: dict, service: str, alert_type: str, evidence_so_far: str = "") -> Evidence:
    start = time.monotonic()
    await asyncio.sleep(SIMULATED_QUERY_LATENCY_SECONDS)

    runbooks = load_fixture("fake_runbooks.json")
    query_text = f"{alert_type} {evidence_so_far}".lower()

    scored = []
    for rb in runbooks:
        if rb["id"] not in infra_metadata.get("runbook_ids", []):
            continue  # only consider runbooks this service has registered as relevant
        score = sum(1 for kw in rb["keywords"] if kw in query_text)
        if score > 0:
            scored.append((score, rb))

    scored.sort(key=lambda x: x[0], reverse=True)

    if scored:
        best_score, best_rb = scored[0]
        finding = f"best match: '{best_rb['title']}' (score={best_score}) — {best_rb['summary']}"
        raw = {"best_match": best_rb, "score": best_score, "candidates": [r["id"] for _, r in scored]}
    else:
        finding = "no matching runbook found for this service/alert_type"
        raw = {"best_match": None, "candidates": []}

    latency_ms = (time.monotonic() - start) * 1000
    return Evidence(
        subagent="runbook",
        finding=finding,
        raw=raw,
        latency_ms=round(latency_ms, 1),
    )
