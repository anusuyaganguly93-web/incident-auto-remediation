"""
Data access for proposed commands and their execution outcomes. Same
pattern as shared/db.py and shared/iar_chat_repo.py: an abstract interface
so the binding/dispatch/policy logic can be unit-tested with
InMemoryCommandRepo, no DB or network required.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid


@dataclass
class ProposedCommand:
    id: str
    incident_id: str
    command_label: str
    tool_name: str
    params: dict
    proposed_at: datetime
    expires_at: datetime
    consumed: bool = False


class CommandRepo(ABC):
    @abstractmethod
    def insert_proposed_command(self, incident_id: str, command_label: str, tool_name: str,
                                 params: dict, ttl: timedelta) -> str:
        ...

    @abstractmethod
    def get_active_proposed_command(self, incident_id: str, command_label: str) -> Optional[ProposedCommand]:
        ...

    @abstractmethod
    def mark_consumed(self, proposed_command_id: str) -> None:
        ...

    @abstractmethod
    def insert_command_execution(self, incident_id: str, proposed_command_id: str, tool_name: str,
                                  params: dict, approved_by: str, outcome: str,
                                  verification_metric: Optional[str] = None,
                                  verification_window_seconds: Optional[int] = None) -> str:
        ...

    @abstractmethod
    def get_service_metadata(self, service: str) -> dict:
        ...


class InMemoryCommandRepo(CommandRepo):
    def __init__(self):
        self._proposed: dict[str, ProposedCommand] = {}
        self._executions: list[dict] = []
        self._services: dict[str, dict] = {}

    def seed_service(self, service: str, metadata: dict) -> None:
        self._services[service] = metadata

    def get_service_metadata(self, service: str) -> dict:
        return self._services.get(service, {})

    def insert_proposed_command(self, incident_id, command_label, tool_name, params, ttl) -> str:
        pid = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        self._proposed[pid] = ProposedCommand(
            id=pid, incident_id=incident_id, command_label=command_label,
            tool_name=tool_name, params=params, proposed_at=now, expires_at=now + ttl,
        )
        return pid

    def get_active_proposed_command(self, incident_id, command_label) -> Optional[ProposedCommand]:
        now = datetime.now(timezone.utc)
        candidates = [
            c for c in self._proposed.values()
            if c.incident_id == incident_id and c.command_label == command_label
            and not c.consumed and c.expires_at > now
        ]
        candidates.sort(key=lambda c: c.proposed_at, reverse=True)
        return candidates[0] if candidates else None

    def mark_consumed(self, proposed_command_id: str) -> None:
        if proposed_command_id in self._proposed:
            self._proposed[proposed_command_id].consumed = True

    def insert_command_execution(self, incident_id, proposed_command_id, tool_name, params,
                                  approved_by, outcome, verification_metric=None,
                                  verification_window_seconds=None) -> str:
        eid = str(uuid.uuid4())
        self._executions.append(dict(
            id=eid, incident_id=incident_id, proposed_command_id=proposed_command_id,
            tool_name=tool_name, params=params, approved_by=approved_by, outcome=outcome,
            verification_metric=verification_metric,
            verification_window_seconds=verification_window_seconds,
        ))
        return eid


class PostgresCommandRepo(CommandRepo):
    """Real implementation. Lazy psycopg import, same pattern as elsewhere."""

    def __init__(self, database_url: Optional[str] = None):
        import os
        self.database_url = database_url or os.getenv(
            "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/incidents"
        )

    def _connect(self):
        import psycopg
        return psycopg.connect(self.database_url)

    def insert_proposed_command(self, incident_id, command_label, tool_name, params, ttl) -> str:
        import json
        expires_at = datetime.now(timezone.utc) + ttl
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO proposed_commands (incident_id, command_label, tool_name, params, expires_at)
                       VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                    (incident_id, command_label, tool_name, json.dumps(params), expires_at),
                )
                row = cur.fetchone()
            conn.commit()
        return str(row[0])

    def get_active_proposed_command(self, incident_id, command_label) -> Optional[ProposedCommand]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, incident_id, command_label, tool_name, params,
                              proposed_at, expires_at, consumed
                       FROM proposed_commands
                       WHERE incident_id = %s AND command_label = %s
                             AND consumed = false AND expires_at > now()
                       ORDER BY proposed_at DESC LIMIT 1""",
                    (incident_id, command_label),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return ProposedCommand(
            id=str(row[0]), incident_id=str(row[1]), command_label=row[2], tool_name=row[3],
            params=row[4], proposed_at=row[5], expires_at=row[6], consumed=row[7],
        )

    def mark_consumed(self, proposed_command_id: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE proposed_commands SET consumed = true WHERE id = %s", (proposed_command_id,))
            conn.commit()

    def insert_command_execution(self, incident_id, proposed_command_id, tool_name, params,
                                  approved_by, outcome, verification_metric=None,
                                  verification_window_seconds=None) -> str:
        import json
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO command_executions
                       (incident_id, proposed_command_id, tool_name, params, approved_by,
                        outcome, verification_metric, verification_window_seconds)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (incident_id, proposed_command_id, tool_name, json.dumps(params), approved_by,
                     outcome, verification_metric, verification_window_seconds),
                )
                row = cur.fetchone()
            conn.commit()
        return str(row[0])

    def get_service_metadata(self, service: str) -> dict:
        from shared.service_registry_repo import get_service
        return get_service(service)
