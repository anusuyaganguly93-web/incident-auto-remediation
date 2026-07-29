"""
Ingestion service entrypoint.

POST /webhooks/alerts/{source}  <-  PagerDuty / ZenDuty / AlertManager

Flow (matches the locked design):
  1. normalize raw payload -> StandardizedAlert
  2. dedup/upsert against incidents table
  3. if NEW incident -> create exactly one Jira ticket, enqueue for triage
  4. if EXISTING incident -> bump counters; re-notify only at threshold crossings
  5. never block on the diagnostic executor here - just enqueue and return fast
"""
import os
import psycopg
from fastapi import FastAPI, HTTPException
from psycopg.rows import tuple_row

from shared.db import PostgresIncidentRepo
from shared.schemas import RawWebhookPayload
from ingestion.normalizer import normalize
from ingestion.dedup import process_alert, should_reescalate
from ingestion.jira_client import JiraClient

app = FastAPI(title="Incident Ingestion Service")
jira = JiraClient(
    base_url=os.getenv("JIRA_BASE_URL", ""),
    email=os.getenv("JIRA_EMAIL", ""),
    api_token=os.getenv("JIRA_API_TOKEN", ""),
)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/incidents")


def get_conn():
    return psycopg.connect(DATABASE_URL, row_factory=tuple_row)


# Starts the durable IncidentWorkflow (see orchestrator/). Runs asyncio.run()
# inside this sync FastAPI handler - safe because FastAPI executes sync `def`
# routes in a threadpool, not the main event loop, so this isn't competing
# for the same loop. Workflow START is fast (just enqueues on the Temporal
# server); actual triage work happens asynchronously in the worker process,
# so this does NOT block the ingestion response.
def enqueue_for_triage(incident_id: str, service: str, alert_type: str, jira_ticket_id: str) -> None:
    import asyncio
    from orchestrator.temporal_client import start_incident_workflow

    try:
        workflow_id = asyncio.run(
            start_incident_workflow(incident_id, service, alert_type, jira_ticket_id)
        )
        print(f"[TEMPORAL] started workflow {workflow_id} for incident {incident_id}")
    except Exception as e:
        # Don't let a Temporal connectivity issue break ingestion itself -
        # the incident + Jira ticket already exist; triage can be retried
        # separately. Ingestion's job is just to get the ticket created fast.
        print(f"[TEMPORAL] failed to start workflow for incident {incident_id}: {e}")


@app.post("/webhooks/alerts/{source}")
def receive_alert(source: str, payload: dict):
    try:
        raw = RawWebhookPayload(source=source, payload=payload)
        alert = normalize(raw)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"failed to normalize alert: {e}")

    with get_conn() as conn:
        repo = PostgresIncidentRepo(conn)
        alert_count_before = None
        existing = repo.get_open_incident_by_fingerprint(alert.fingerprint)
        if existing:
            alert_count_before = existing.alert_count

        result = process_alert(repo, alert)

        if result.is_new:
            ticket_id = jira.create_ticket(
                service=alert.service,
                severity=alert.severity,
                summary=f"[{alert.severity}] {alert.alert_type} - {alert.service}",
                description=f"Auto-created from {alert.raw_source} alert. Fingerprint: {alert.fingerprint}",
            )
            repo.set_jira_ticket(result.incident, ticket_id)
            enqueue_for_triage(result.incident.id, alert.service, alert.alert_type, ticket_id)
        else:
            if alert_count_before is not None and should_reescalate(
                alert_count_before, result.incident.alert_count
            ):
                jira.post_comment(
                    result.incident.jira_ticket_id,
                    f"⚠️ Still firing — now {result.incident.alert_count}x alerts received.",
                )

    return {
        "incident_id": result.incident.id,
        "is_new": result.is_new,
        "alert_count": result.incident.alert_count,
        "jira_ticket_id": result.incident.jira_ticket_id,
    }


@app.get("/health")
def health():
    return {"status": "ok"}
