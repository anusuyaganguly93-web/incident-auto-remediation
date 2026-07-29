"""
Shared data contracts used across ingestion, orchestrator, and executors.
Keeping these in one place means every service agrees on the same shape.
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, Field


class RawWebhookPayload(BaseModel):
    """Whatever the alert source (PagerDuty/ZenDuty/AlertManager) sends us, unmodified."""
    source: str  # "pagerduty" | "zenduty" | "alertmanager" | ...
    payload: dict[str, Any]


class StandardizedAlert(BaseModel):
    """
    The normalized shape every downstream component works with.
    Produced by ingestion/normalizer.py from a RawWebhookPayload.
    """
    raw_source: str
    service: str
    alert_type: str
    severity: str  # P1 | P2 | P3 ...
    env: str
    region: Optional[str] = None
    started_at: datetime
    labels: dict[str, str] = Field(default_factory=dict)
    fingerprint: str  # computed by shared/fingerprint.py, NOT set by caller


class IncidentStatus:
    NEW = "new"
    TRIAGING = "triaging"
    DIAGNOSING = "diagnosing"
    DECIDING = "deciding"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class Incident(BaseModel):
    id: str
    fingerprint: str
    status: str
    service: str
    severity: str
    jira_ticket_id: Optional[str] = None
    first_alert_at: datetime
    last_alert_at: datetime
    alert_count: int = 1
    confidence: Optional[float] = None
