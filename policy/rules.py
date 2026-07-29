"""
Rule-based policy gate. No LLM involved, deliberately - per the design
decision locked early on, the write path never has an LLM deciding
whether or what to execute.

This gate runs even AFTER a human has already approved a specific
proposed command (see command_executor/approve_command.py) - a human's
tag is necessary but not sufficient. A tired on-call engineer at 3am
tagging the wrong command shouldn't be the only thing standing between
an incident and an irreversible production action.
"""
from dataclasses import dataclass

# tool_name -> (reversible, blast_radius). Kept as a flat table rather than
# a rules engine - simple enough for this project's scope, and the
# tradeoffs are visible at a glance rather than buried in branching logic.
ACTION_POLICY = {
    "modify_infra": {"reversible": True, "blast_radius": "low"},
    "deploy_service": {"reversible": True, "blast_radius": "medium"},
    "update_database": {"reversible": False, "blast_radius": "high"},
}


@dataclass
class PolicyDecision:
    approved: bool
    reason: str


def evaluate_policy(tool_name: str, service_criticality_tier: int = 3) -> PolicyDecision:
    """
    service_criticality_tier is accepted but not currently used to restrict
    anything further - kept in the signature so a future iteration can add
    tier-based rules (e.g. "tier-1 services need a second approver for
    medium blast radius") without changing every call site. Documented
    simplification, not an oversight.
    """
    policy = ACTION_POLICY.get(tool_name)
    if policy is None:
        return PolicyDecision(approved=False, reason=f"unknown tool '{tool_name}' — no policy defined")

    if not policy["reversible"]:
        return PolicyDecision(
            approved=False,
            reason=f"'{tool_name}' is not reversible — requires manual execution outside this system",
        )

    if policy["blast_radius"] == "high":
        return PolicyDecision(
            approved=False,
            reason=f"'{tool_name}' has high blast radius — too risky for automated dispatch",
        )

    return PolicyDecision(
        approved=True,
        reason=f"'{tool_name}' is reversible with {policy['blast_radius']} blast radius — within auto-dispatch policy",
    )
