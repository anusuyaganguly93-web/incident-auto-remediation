"""
Temporal activity: persists each piece of diagnostic evidence as a row in
incident_events (migrations/003_create_incident_events.sql). This is what
makes evidence queryable after the fact - the raw material Phase 3's IAR
chat RAG will read from, and the audit trail for "why did the system say
what it said."
"""
from dataclasses import dataclass
import json
import os

import psycopg
from temporalio import activity

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/incidents")


@dataclass
class StoreEvidenceInput:
    incident_id: str
    evidence_dicts: list[dict]


@activity.defn
async def store_evidence(input: StoreEvidenceInput) -> int:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            for e in input.evidence_dicts:
                cur.execute(
                    "INSERT INTO incident_events (incident_id, event_type, payload) VALUES (%s, %s, %s)",
                    (input.incident_id, f"evidence_{e['subagent']}", json.dumps(e)),
                )
        conn.commit()
    activity.logger.info(f"stored {len(input.evidence_dicts)} evidence rows for incident {input.incident_id}")
    return len(input.evidence_dicts)
