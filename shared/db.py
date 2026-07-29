"""
Repository layer for the `incidents` table.

We define an abstract IncidentRepo interface so the dedup logic in
ingestion/dedup.py can be unit-tested with an in-memory fake (see
tests/test_dedup.py) without needing a real Postgres instance.

PostgresIncidentRepo is the real implementation used at runtime,
wired up via docker-compose.
"""
from __future__ import annotations
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from shared.schemas import Incident, IncidentStatus


class IncidentRepo(ABC):
    @abstractmethod
    def get_open_incident_by_fingerprint(self, fingerprint: str) -> Optional[Incident]:
        ...

    @abstractmethod
    def create_incident(self, fingerprint: str, service: str, severity: str,
                         started_at: datetime) -> Incident:
        ...

    @abstractmethod
    def bump_incident(self, incident: Incident, last_alert_at: datetime) -> Incident:
        ...

    @abstractmethod
    def set_jira_ticket(self, incident: Incident, jira_ticket_id: str) -> Incident:
        ...


class InMemoryIncidentRepo(IncidentRepo):
    """Pure-python fake used in unit tests — no DB, no network required."""

    def __init__(self):
        self._store: dict[str, Incident] = {}

    def get_open_incident_by_fingerprint(self, fingerprint: str) -> Optional[Incident]:
        for inc in self._store.values():
            if inc.fingerprint == fingerprint and inc.status not in (
                IncidentStatus.RESOLVED, IncidentStatus.ESCALATED
            ):
                return inc
        return None

    def create_incident(self, fingerprint, service, severity, started_at) -> Incident:
        inc = Incident(
            id=str(uuid.uuid4()),
            fingerprint=fingerprint,
            status=IncidentStatus.NEW,
            service=service,
            severity=severity,
            first_alert_at=started_at,
            last_alert_at=started_at,
            alert_count=1,
        )
        self._store[inc.id] = inc
        return inc

    def bump_incident(self, incident: Incident, last_alert_at: datetime) -> Incident:
        incident.last_alert_at = last_alert_at
        incident.alert_count += 1
        self._store[incident.id] = incident
        return incident

    def set_jira_ticket(self, incident: Incident, jira_ticket_id: str) -> Incident:
        incident.jira_ticket_id = jira_ticket_id
        self._store[incident.id] = incident
        return incident


class PostgresIncidentRepo(IncidentRepo):
    """
    Real implementation, used at runtime. Requires `psycopg[binary]` and a
    running Postgres (see docker-compose.yml). Kept intentionally thin —
    raw SQL, no ORM, so the upsert semantics are exactly what we designed:
    ON CONFLICT on fingerprint WHERE status is still open.
    """

    def __init__(self, conn):
        self.conn = conn  # a psycopg connection

    def get_open_incident_by_fingerprint(self, fingerprint: str) -> Optional[Incident]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, fingerprint, status, service, severity, jira_ticket_id,
                       first_alert_at, last_alert_at, alert_count, confidence
                FROM incidents
                WHERE fingerprint = %s AND status NOT IN ('resolved', 'escalated')
                LIMIT 1
                """,
                (fingerprint,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return _row_to_incident(row)

    def create_incident(self, fingerprint, service, severity, started_at) -> Incident:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO incidents (fingerprint, service, severity, first_alert_at, last_alert_at)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, fingerprint, status, service, severity, jira_ticket_id,
                          first_alert_at, last_alert_at, alert_count, confidence
                """,
                (fingerprint, service, severity, started_at, started_at),
            )
            row = cur.fetchone()
            self.conn.commit()
            return _row_to_incident(row)

    def bump_incident(self, incident: Incident, last_alert_at: datetime) -> Incident:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE incidents
                SET last_alert_at = %s, alert_count = alert_count + 1
                WHERE id = %s
                RETURNING id, fingerprint, status, service, severity, jira_ticket_id,
                          first_alert_at, last_alert_at, alert_count, confidence
                """,
                (last_alert_at, incident.id),
            )
            row = cur.fetchone()
            self.conn.commit()
            return _row_to_incident(row)

    def set_jira_ticket(self, incident: Incident, jira_ticket_id: str) -> Incident:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE incidents SET jira_ticket_id = %s WHERE id = %s",
                (jira_ticket_id, incident.id),
            )
            self.conn.commit()
        incident.jira_ticket_id = jira_ticket_id
        return incident


def _row_to_incident(row) -> Incident:
    return Incident(
        id=str(row[0]), fingerprint=row[1], status=row[2], service=row[3],
        severity=row[4], jira_ticket_id=row[5], first_alert_at=row[6],
        last_alert_at=row[7], alert_count=row[8], confidence=row[9],
    )
