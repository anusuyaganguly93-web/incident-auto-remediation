"""
Data access for IAR chat: reading an incident + its diagnostic evidence,
and reading/writing conversation history.

Same pattern as shared/db.py's IncidentRepo: an abstract interface so
iar_chat/chat.py's logic can be unit-tested with InMemoryIARChatRepo (no DB,
no network) without touching PostgresIARChatRepo at all.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ChatMessage:
    role: str  # "user" | "assistant"
    content: str
    created_at: Optional[datetime] = None


class IARChatRepo(ABC):
    @abstractmethod
    def get_incident(self, incident_id: str) -> Optional[dict]:
        ...

    @abstractmethod
    def get_evidence(self, incident_id: str) -> list[dict]:
        ...

    @abstractmethod
    def get_chat_history(self, incident_id: str) -> list[ChatMessage]:
        ...

    @abstractmethod
    def save_chat_message(self, incident_id: str, role: str, content: str) -> None:
        ...


class InMemoryIARChatRepo(IARChatRepo):
    """Pure-python fake used in unit tests. Call seed_incident() to set up
    fixture data before exercising chat.ask()."""

    def __init__(self):
        self._incidents: dict[str, dict] = {}
        self._evidence: dict[str, list[dict]] = {}
        self._messages: dict[str, list[ChatMessage]] = {}

    def seed_incident(self, incident_id: str, incident: dict, evidence: list[dict]) -> None:
        self._incidents[incident_id] = incident
        self._evidence[incident_id] = evidence
        self._messages.setdefault(incident_id, [])

    def get_incident(self, incident_id: str) -> Optional[dict]:
        return self._incidents.get(incident_id)

    def get_evidence(self, incident_id: str) -> list[dict]:
        return self._evidence.get(incident_id, [])

    def get_chat_history(self, incident_id: str) -> list[ChatMessage]:
        return list(self._messages.get(incident_id, []))

    def save_chat_message(self, incident_id: str, role: str, content: str) -> None:
        self._messages.setdefault(incident_id, []).append(ChatMessage(role=role, content=content))


class PostgresIARChatRepo(IARChatRepo):
    """Real implementation. Lazy psycopg import so this module stays
    importable (and InMemoryIARChatRepo testable) without psycopg installed."""

    def __init__(self, database_url: Optional[str] = None):
        import os
        self.database_url = database_url or os.getenv(
            "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/incidents"
        )

    def _connect(self):
        import psycopg
        return psycopg.connect(self.database_url)

    def get_incident(self, incident_id: str) -> Optional[dict]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, fingerprint, status, service, severity, jira_ticket_id,
                       first_alert_at, last_alert_at, alert_count
                       FROM incidents WHERE id = %s""",
                    (incident_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        cols = ["id", "fingerprint", "status", "service", "severity", "jira_ticket_id",
                "first_alert_at", "last_alert_at", "alert_count"]
        return dict(zip(cols, row))

    def get_evidence(self, incident_id: str) -> list[dict]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT event_type, payload, created_at FROM incident_events
                       WHERE incident_id = %s ORDER BY created_at""",
                    (incident_id,),
                )
                rows = cur.fetchall()
        return [{"event_type": r[0], "payload": r[1], "created_at": r[2]} for r in rows]

    def get_chat_history(self, incident_id: str) -> list[ChatMessage]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT role, content, created_at FROM incident_chat_messages
                       WHERE incident_id = %s ORDER BY created_at""",
                    (incident_id,),
                )
                rows = cur.fetchall()
        return [ChatMessage(role=r[0], content=r[1], created_at=r[2]) for r in rows]

    def save_chat_message(self, incident_id: str, role: str, content: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO incident_chat_messages (incident_id, role, content) VALUES (%s, %s, %s)",
                    (incident_id, role, content),
                )
            conn.commit()
