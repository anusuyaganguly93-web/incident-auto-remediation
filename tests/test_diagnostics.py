"""
Run with: pytest tests/test_diagnostics.py -v

No external dependencies needed beyond pytest — everything here is
stdlib + asyncio against fixture data, so it runs identically in CI,
locally, or in a sandbox with no network access.
"""
import asyncio
import pytest

from diagnostics.scripts.anomaly_detection import detect_anomaly
from diagnostics.scripts.filter_logs_by_error_level import filter_logs_by_error_level
from diagnostics.run_diagnostics import run_diagnostics
from diagnostics.execute import execute


def test_anomaly_detection_catches_injected_latency_spike():
    series = [120, 118, 125, 122, 119, 124, 121, 123, 120, 126, 118, 122, 121, 890, 910, 875]
    result = detect_anomaly(series, "p99_latency_ms")
    assert result.is_anomalous is True
    assert result.pct_change > 100


def test_anomaly_detection_does_not_flag_flat_series():
    series = [60, 62, 61, 59, 60, 61, 60, 62, 59, 60, 61, 60, 59, 61, 62, 60]
    result = detect_anomaly(series, "p99_latency_ms")
    assert result.is_anomalous is False


def test_log_filter_clusters_repeated_errors_and_drops_info():
    lines = [
        {"ts": "t1", "level": "INFO", "msg": "ok"},
        {"ts": "t2", "level": "ERROR", "msg": "timed out after 5000ms"},
        {"ts": "t3", "level": "ERROR", "msg": "timed out after 5000ms"},
        {"ts": "t4", "level": "ERROR", "msg": "timed out after 3000ms"},  # same normalized msg
    ]
    clusters = filter_logs_by_error_level(lines, min_level="WARN")
    assert len(clusters) == 1  # both ERROR lines normalize to the same cluster
    assert clusters[0].count == 3
    assert clusters[0].level == "ERROR"


@pytest.mark.asyncio
async def test_deploy_history_attributes_checkout_incident_to_payment_api_dependency():
    """
    The key scenario from our design discussion: checkout-api alerts, but
    the ROOT CAUSE is a deploy to its dependency payment-api. The
    dependency-walk logic must surface this, not just check checkout-api's
    own (unremarkable) deploy history.
    """
    evidence, _ = await run_diagnostics("checkout-api", "high_latency")
    deploy_evidence = next(e for e in evidence if e.subagent == "deploy_history")
    assert "payment-api" in deploy_evidence.finding
    assert "v2.8.3" in deploy_evidence.finding


@pytest.mark.asyncio
async def test_runbook_subagent_picks_dependency_timeout_runbook_for_checkout():
    evidence, _ = await run_diagnostics("checkout-api", "high_latency")
    runbook_evidence = next(e for e in evidence if e.subagent == "runbook")
    assert runbook_evidence.raw["best_match"]["id"] == "rb-high-latency-001"


@pytest.mark.asyncio
async def test_inventory_api_shows_no_anomalies_no_false_positive():
    """Sanity check: a healthy service should NOT get flagged."""
    evidence, _ = await run_diagnostics("inventory-api", "high_error_rate")
    metrics_evidence = next(e for e in evidence if e.subagent == "metrics")
    assert "no anomalies detected" in metrics_evidence.finding


@pytest.mark.asyncio
async def test_parallel_fanout_is_actually_parallel_not_sequential():
    """
    Proves the load-bearing latency claim: metrics/logs/deploy_history run
    concurrently. Sum of their simulated latencies is 0.4+0.5+0.3=1.2s;
    if they ran sequentially, total wall time would be >= 1.2s plus the
    runbook round. Parallel execution should keep total wall time well
    under that sum.
    """
    evidence, wall_time_ms = await run_diagnostics("checkout-api", "high_latency")

    per_subagent_latencies = {e.subagent: e.latency_ms for e in evidence}
    sequential_sum_ms = sum(per_subagent_latencies.values())

    assert wall_time_ms < sequential_sum_ms, (
        f"expected parallel fan-out to beat sequential sum "
        f"({wall_time_ms}ms vs {sequential_sum_ms}ms) — did asyncio.gather stop working?"
    )
    # allow generous margin for CI slowness — the key assertion is < sequential sum, not exact timing
    assert wall_time_ms < 1000


@pytest.mark.asyncio
async def test_execute_end_to_end_produces_comment_referencing_all_evidence():
    result = await execute("checkout-api", "high_latency")
    comment = result["comment"]
    assert "metrics" in comment
    assert "logs" in comment
    assert "deploy_history" in comment
    assert "runbook" in comment
    assert "payment-api" in comment  # the cross-service root cause must surface in the final comment
