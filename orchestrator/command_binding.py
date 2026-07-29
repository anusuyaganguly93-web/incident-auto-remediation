"""
Maps a runbook's suggested_commands label (e.g. "restart-pods") to a
fully-bound (tool_name, params) pair - no placeholders left for anything
downstream to interpret. This is what makes dispatch deterministic later:
by the time a human approves a proposed command, its exact tool call is
already fully specified.

Kept separate from orchestrator/activities/propose_commands.py (which
imports temporalio) so this logic is testable without temporalio
installed - same pattern as diagnostics/run_diagnostics.py being
independent of its Temporal activity wrapper.
"""
from typing import Optional


def bind_command(label: str, service: str, infra_metadata: dict) -> tuple[Optional[str], Optional[dict]]:
    """
    Returns (None, None) if this label can't be turned into an executable
    action for this service - e.g. no live target_app to act against
    (payment-api/inventory-api in this project), or a label like
    "escalate-only" that's a signal to the human, not an action.
    """
    metrics_url = infra_metadata.get("metrics_url")
    target_url = metrics_url.rsplit("/metrics", 1)[0] if metrics_url else None

    if label == "restart-pods":
        if not target_url:
            return None, None
        return "modify_infra", {"action": "restart", "service": service, "target_url": target_url}

    if label == "rollback-deploy":
        if not target_url:
            return None, None
        return "deploy_service", {"action": "rollback", "service": service, "target_url": target_url}

    # "escalate-only" and any unrecognized label -> no executable binding
    return None, None
