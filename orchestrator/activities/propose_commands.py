"""
Temporal activity: reads the runbook evidence's suggested_commands,
binds each to a fully-specified tool call via orchestrator.command_binding,
and persists them as proposed_commands rows with a TTL. A human approves
one later via command_executor/approve_command.py (simulating a Jira tag).

No business logic here beyond orchestrating the binding + persistence -
the actual binding rules live in orchestrator/command_binding.py, which
is deliberately kept free of the temporalio import so it's unit-testable
standalone.
"""
from dataclasses import dataclass
from datetime import timedelta

from temporalio import activity

from orchestrator.command_binding import bind_command
from shared.command_repo import PostgresCommandRepo

PROPOSAL_TTL = timedelta(hours=1)


@dataclass
class ProposeCommandsInput:
    incident_id: str
    service: str
    infra_metadata: dict
    evidence_dicts: list[dict]


@activity.defn
async def propose_commands_activity(input: ProposeCommandsInput) -> list[dict]:
    runbook_evidence = next((e for e in input.evidence_dicts if e.get("subagent") == "runbook"), None)
    if not runbook_evidence:
        return []

    best_match = runbook_evidence.get("raw", {}).get("best_match")
    if not best_match:
        return []

    suggested_labels = best_match.get("suggested_commands", [])
    repo = PostgresCommandRepo()

    proposed = []
    for label in suggested_labels:
        tool_name, params = bind_command(label, input.service, input.infra_metadata)
        if tool_name is None:
            continue  # e.g. "escalate-only", or no live target_app for this service

        proposed_id = repo.insert_proposed_command(
            incident_id=input.incident_id, command_label=label,
            tool_name=tool_name, params=params, ttl=PROPOSAL_TTL,
        )
        proposed.append({
            "id": proposed_id, "command_label": label, "tool_name": tool_name, "params": params,
        })

    activity.logger.info(f"proposed {len(proposed)} executable command(s) for incident {input.incident_id}")
    return proposed
