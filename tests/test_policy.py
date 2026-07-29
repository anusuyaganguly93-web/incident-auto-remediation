"""
Run with: pytest tests/test_policy.py -v
Pure logic, zero dependencies.
"""
from policy.rules import evaluate_policy


def test_modify_infra_approved():
    decision = evaluate_policy("modify_infra")
    assert decision.approved is True


def test_deploy_service_approved():
    decision = evaluate_policy("deploy_service")
    assert decision.approved is True


def test_update_database_denied_not_reversible():
    decision = evaluate_policy("update_database")
    assert decision.approved is False
    assert "not reversible" in decision.reason


def test_unknown_tool_denied():
    decision = evaluate_policy("delete_everything")
    assert decision.approved is False
    assert "unknown tool" in decision.reason


def test_criticality_tier_accepted_but_not_currently_restrictive():
    # documented simplification: tier is accepted for future extension,
    # doesn't change the outcome today
    decision_tier1 = evaluate_policy("modify_infra", service_criticality_tier=1)
    decision_tier3 = evaluate_policy("modify_infra", service_criticality_tier=3)
    assert decision_tier1.approved == decision_tier3.approved == True
