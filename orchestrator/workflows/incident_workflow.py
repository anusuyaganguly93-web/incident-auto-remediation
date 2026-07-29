"""
The durable workflow that replaces the standalone diagnostics.execute()
CLI entrypoint from Phase 2 slice 1. Workflow ID = incident ID (see
orchestrator/temporal_client.py) — this is what gives us idempotency per
incident: Temporal rejects starting a second workflow with an ID that's
already running, so a duplicate enqueue can't double-trigger triage.

State progression this covers so far: new -> (resolve infra) -> (diagnose,
in parallel internally) -> (propose commands from the runbook's
suggested_commands) -> (persist evidence + synthesize/post comment
including the proposed command menu, in parallel with each other) ->
diagnosed. Actual command execution happens OUTSIDE this workflow, via
command_executor/approve_command.py, triggered by a human (Phase 4) - this
workflow's job stops at proposing, never executing.
"""
import asyncio
from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from orchestrator.activities.resolve_infra_metadata import resolve_infra_metadata
    from orchestrator.activities.run_diagnostics_activity import (
        run_diagnostics_activity,
        RunDiagnosticsInput,
    )
    from orchestrator.activities.propose_commands import (
        propose_commands_activity,
        ProposeCommandsInput,
    )
    from orchestrator.activities.post_summary import (
        generate_and_post_comment,
        GenerateAndPostCommentInput,
    )
    from orchestrator.activities.store_evidence import (
        store_evidence,
        StoreEvidenceInput,
    )


@dataclass
class IncidentWorkflowInput:
    incident_id: str
    service: str
    alert_type: str
    jira_ticket_id: str


# Read-only, side-effect-free activities are safe to retry more aggressively
# than the write-adjacent comment-posting step, which we don't want to
# accidentally double-post on a flaky retry.
READ_ONLY_RETRY = RetryPolicy(maximum_attempts=3, backoff_coefficient=2.0)
COMMENT_POST_RETRY = RetryPolicy(maximum_attempts=2, backoff_coefficient=2.0)


@workflow.defn
class IncidentWorkflow:
    @workflow.run
    async def run(self, input: IncidentWorkflowInput) -> dict:
        infra_metadata = await workflow.execute_activity(
            resolve_infra_metadata,
            input.service,
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=READ_ONLY_RETRY,
        )

        evidence_dicts = await workflow.execute_activity(
            run_diagnostics_activity,
            RunDiagnosticsInput(service=input.service, alert_type=input.alert_type),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=READ_ONLY_RETRY,
        )

        proposed_commands = await workflow.execute_activity(
            propose_commands_activity,
            ProposeCommandsInput(
                incident_id=input.incident_id,
                service=input.service,
                infra_metadata=infra_metadata,
                evidence_dicts=evidence_dicts,
            ),
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=READ_ONLY_RETRY,
        )

        # persisting evidence and posting the human-facing comment don't
        # depend on each other, so run them concurrently rather than
        # burning an extra sequential round on the latency budget
        comment, stored_count = await asyncio.gather(
            workflow.execute_activity(
                generate_and_post_comment,
                GenerateAndPostCommentInput(
                    service=input.service,
                    alert_type=input.alert_type,
                    evidence_dicts=evidence_dicts,
                    jira_ticket_id=input.jira_ticket_id,
                    proposed_commands=proposed_commands,
                ),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=COMMENT_POST_RETRY,
            ),
            workflow.execute_activity(
                store_evidence,
                StoreEvidenceInput(incident_id=input.incident_id, evidence_dicts=evidence_dicts),
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=READ_ONLY_RETRY,
            ),
        )

        return {
            "status": "diagnosed",
            "infra_metadata": infra_metadata,
            "evidence_count": len(evidence_dicts),
            "evidence_rows_stored": stored_count,
            "proposed_commands": proposed_commands,
            "comment": comment,
        }
