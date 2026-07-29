"""
Run: python3 -m orchestrator.worker

Requires a running Temporal server (see README — `temporal server start-dev`
for local development, no docker-compose entry needed for this).

This process must be running for any incident workflow to actually
progress — the ingestion service only ever STARTS workflows, it never
executes them directly.
"""
import asyncio
import logging
import os

from temporalio.client import Client
from temporalio.worker import Worker

from orchestrator.workflows.incident_workflow import IncidentWorkflow
from orchestrator.activities.resolve_infra_metadata import resolve_infra_metadata
from orchestrator.activities.run_diagnostics_activity import run_diagnostics_activity
from orchestrator.activities.propose_commands import propose_commands_activity
from orchestrator.activities.post_summary import generate_and_post_comment
from orchestrator.activities.store_evidence import store_evidence

# The worker runs directly on your HOST machine (see README), not in Docker,
# so it talks to the Temporal dev server via plain localhost.
TEMPORAL_TARGET = os.getenv("TEMPORAL_TARGET", "localhost:7233")
TASK_QUEUE = "incident-triage"

logging.basicConfig(level=logging.INFO)


async def main():
    client = await Client.connect(TEMPORAL_TARGET)
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[IncidentWorkflow],
        activities=[
            resolve_infra_metadata, run_diagnostics_activity, propose_commands_activity,
            generate_and_post_comment, store_evidence,
        ],
    )
    print(f"Worker started. Polling task queue '{TASK_QUEUE}' on {TEMPORAL_TARGET}...")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
