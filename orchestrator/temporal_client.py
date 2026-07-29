"""
Called from ingestion/main.py's enqueue_for_triage() on every NEW incident.

Connects to Temporal fresh on every call, which is wasteful for
production (you'd want a shared long-lived Client), but keeps this
service's startup simple for now. Flagging as a known simplification,
same as the sync-blocking-call note in post_summary.py.
"""
import os

from temporalio.client import Client

from orchestrator.workflows.incident_workflow import IncidentWorkflow, IncidentWorkflowInput

# Defaults to localhost for running this module directly on the host.
# docker-compose.yml overrides this to host.docker.internal:7233 for the
# ingestion container, since `temporal server start-dev` runs on the HOST,
# not inside Docker - "localhost" from inside a container means the
# container itself, not your machine.
TEMPORAL_TARGET = os.getenv("TEMPORAL_TARGET", "localhost:7233")
TASK_QUEUE = "incident-triage"


async def start_incident_workflow(
    incident_id: str, service: str, alert_type: str, jira_ticket_id: str
) -> str:
    client = await Client.connect(TEMPORAL_TARGET)
    handle = await client.start_workflow(
        IncidentWorkflow.run,
        IncidentWorkflowInput(
            incident_id=incident_id, service=service, alert_type=alert_type, jira_ticket_id=jira_ticket_id
        ),
        id=incident_id,  # workflow ID = incident ID -> idempotent, per the original design
        task_queue=TASK_QUEUE,
    )
    return handle.id
