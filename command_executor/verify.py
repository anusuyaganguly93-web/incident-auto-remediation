"""
Post-action verification: re-query the service's live metrics after a
short wait and check whether the anomaly that triggered the incident has
actually cleared. Reuses anomaly_detection.py from diagnostics - no new
detection logic, just re-running the same proven check against fresh data.

classify_verification() is split out from verify_resolution() so the
outcome-determination logic is testable without a live target_app - same
lazy-import pattern used elsewhere in this codebase for live-only calls.
"""
import asyncio

from diagnostics.scripts.anomaly_detection import detect_anomaly


def classify_verification(series: list[float], metric_name: str = "p99_latency_ms") -> dict:
    try:
        result = detect_anomaly(series, metric_name)
    except ValueError:
        return {"outcome": "insufficient_data", "detail": "not enough samples yet to verify"}

    # detect_anomaly only flags a large z-score - it doesn't know whether
    # that change is an improvement or a degradation. A big DROP after a
    # remediation action (e.g. latency falling from 900ms to 250ms) is
    # exactly what success looks like, and must not be labeled "regressed"
    # just because it's statistically anomalous relative to the bad
    # baseline. Direction matters, not just magnitude.
    if not result.is_anomalous:
        outcome = "resolved"
    elif result.recent_mean < result.baseline_mean:
        outcome = "resolved"  # significant improvement
    else:
        outcome = "regressed"  # significant degradation

    return {
        "outcome": outcome,
        "baseline_mean": result.baseline_mean,
        "recent_mean": result.recent_mean,
        "pct_change": result.pct_change,
    }


async def verify_resolution(target_url: str, metric_name: str = "p99_latency_ms",
                             wait_seconds: int = 5) -> dict:
    await asyncio.sleep(wait_seconds)

    import httpx
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{target_url}/metrics")
        resp.raise_for_status()
        series = resp.json().get(metric_name, [])

    return classify_verification(series, metric_name)
