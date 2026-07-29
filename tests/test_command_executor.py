"""
Run with: pytest tests/test_command_executor.py -v

Covers command binding (runbook label -> tool call), the in-memory repo
(proposal lifecycle: propose -> active -> consumed / expired), the
dispatcher's table lookup, and verification outcome classification.
None of this touches a live target_app or Postgres.
"""
from datetime import timedelta

import pytest

from orchestrator.command_binding import bind_command
from shared.command_repo import InMemoryCommandRepo
from command_executor.dispatcher import TOOL_REGISTRY, dispatch
from command_executor.verify import classify_verification


CHECKOUT_INFRA_METADATA = {"metrics_url": "http://localhost:8080/metrics"}
NO_LIVE_TARGET_METADATA = {"metrics_url": None}


def test_bind_restart_pods_to_modify_infra():
    tool_name, params = bind_command("restart-pods", "checkout-api", CHECKOUT_INFRA_METADATA)
    assert tool_name == "modify_infra"
    assert params == {"action": "restart", "service": "checkout-api", "target_url": "http://localhost:8080"}


def test_bind_rollback_deploy_to_deploy_service():
    tool_name, params = bind_command("rollback-deploy", "checkout-api", CHECKOUT_INFRA_METADATA)
    assert tool_name == "deploy_service"
    assert params["action"] == "rollback"
    assert params["target_url"] == "http://localhost:8080"


def test_bind_returns_none_when_no_live_target():
    tool_name, params = bind_command("restart-pods", "payment-api", NO_LIVE_TARGET_METADATA)
    assert tool_name is None
    assert params is None


def test_bind_returns_none_for_escalate_only():
    tool_name, params = bind_command("escalate-only", "inventory-api", CHECKOUT_INFRA_METADATA)
    assert tool_name is None


def test_bind_returns_none_for_unrecognized_label():
    tool_name, params = bind_command("some-made-up-command", "checkout-api", CHECKOUT_INFRA_METADATA)
    assert tool_name is None


def test_repo_propose_then_get_active():
    repo = InMemoryCommandRepo()
    pid = repo.insert_proposed_command(
        "inc-1", "restart-pods", "modify_infra", {"service": "checkout-api"}, ttl=timedelta(hours=1)
    )
    active = repo.get_active_proposed_command("inc-1", "restart-pods")
    assert active is not None
    assert active.id == pid
    assert active.consumed is False


def test_repo_consumed_command_no_longer_active():
    repo = InMemoryCommandRepo()
    pid = repo.insert_proposed_command(
        "inc-1", "restart-pods", "modify_infra", {}, ttl=timedelta(hours=1)
    )
    repo.mark_consumed(pid)
    assert repo.get_active_proposed_command("inc-1", "restart-pods") is None


def test_repo_expired_command_no_longer_active():
    repo = InMemoryCommandRepo()
    repo.insert_proposed_command(
        "inc-1", "restart-pods", "modify_infra", {}, ttl=timedelta(seconds=-1)  # already expired
    )
    assert repo.get_active_proposed_command("inc-1", "restart-pods") is None


def test_dispatcher_registry_has_all_three_tools():
    assert set(TOOL_REGISTRY.keys()) == {"modify_infra", "deploy_service", "update_database"}


@pytest.mark.asyncio
async def test_dispatch_raises_for_unknown_tool():
    with pytest.raises(ValueError):
        await dispatch("nonexistent_tool", {})


def test_classify_verification_healthy_series_is_resolved():
    healthy = [120, 118, 122, 121, 119, 120, 121, 118, 122, 120, 119, 121, 120, 118, 121, 120]
    result = classify_verification(healthy)
    assert result["outcome"] == "resolved"


def test_classify_verification_spiking_series_is_regressed():
    spiking = [120, 118, 122, 121, 119, 120, 121, 118, 122, 120, 900, 895, 910, 888, 902, 897]
    result = classify_verification(spiking)
    assert result["outcome"] == "regressed"


def test_classify_verification_recovering_series_is_resolved_not_regressed():
    """
    Regression test for a real bug: a big statistical anomaly caused by
    an IMPROVEMENT (e.g. latency dropping sharply after a remediation
    action) must classify as 'resolved', not 'regressed'. detect_anomaly()
    only measures magnitude of change, not direction - classify_verification
    has to add that direction check itself.
    """
    recovering = [900, 895, 910, 888, 902, 897, 905, 891, 898, 903, 250, 245, 260, 248, 252, 255]
    result = classify_verification(recovering)
    assert result["outcome"] == "resolved"
    assert result["recent_mean"] < result["baseline_mean"]


def test_classify_verification_short_series_is_insufficient_data():
    result = classify_verification([100, 101, 102])
    assert result["outcome"] == "insufficient_data"
