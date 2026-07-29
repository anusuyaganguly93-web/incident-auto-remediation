"""
Converts source-specific raw payloads into the StandardizedAlert schema.
Add one function per alert source — keeps the webhook handler itself dumb.
"""
from datetime import datetime, timezone

from shared.fingerprint import compute_fingerprint
from shared.schemas import RawWebhookPayload, StandardizedAlert


def normalize(raw: RawWebhookPayload) -> StandardizedAlert:
    if raw.source == "pagerduty":
        return _normalize_pagerduty(raw.payload)
    if raw.source == "zenduty":
        return _normalize_zenduty(raw.payload)
    if raw.source == "alertmanager":
        return _normalize_alertmanager(raw.payload)
    raise ValueError(f"Unknown alert source: {raw.source}")


def _normalize_pagerduty(payload: dict) -> StandardizedAlert:
    incident = payload.get("incident", payload)
    service = incident["service"]["summary"] if isinstance(incident.get("service"), dict) else incident.get("service", "unknown")
    alert_type = incident.get("alert_type", incident.get("title", "unknown"))
    env = incident.get("custom_details", {}).get("env", "prod")
    severity = _map_pd_urgency_to_severity(incident.get("urgency", "high"))
    started_at = _parse_ts(incident.get("created_at"))

    fp = compute_fingerprint(service, alert_type, env)
    return StandardizedAlert(
        raw_source="pagerduty", service=service, alert_type=alert_type,
        severity=severity, env=env, started_at=started_at,
        labels={"region": incident.get("custom_details", {}).get("region", "unknown")},
        fingerprint=fp,
    )


def _normalize_zenduty(payload: dict) -> StandardizedAlert:
    service = payload.get("service", "unknown")
    alert_type = payload.get("alert_type", payload.get("title", "unknown"))
    env = payload.get("env", "prod")
    severity = payload.get("severity", "P2")
    started_at = _parse_ts(payload.get("created_at"))

    fp = compute_fingerprint(service, alert_type, env)
    return StandardizedAlert(
        raw_source="zenduty", service=service, alert_type=alert_type,
        severity=severity, env=env, started_at=started_at,
        labels={"region": payload.get("region", "unknown")},
        fingerprint=fp,
    )


def _normalize_alertmanager(payload: dict) -> StandardizedAlert:
    alert = payload.get("alerts", [payload])[0]
    labels = alert.get("labels", {})
    service = labels.get("service", "unknown")
    alert_type = labels.get("alertname", "unknown")
    env = labels.get("env", "prod")
    severity = labels.get("severity", "P2")
    started_at = _parse_ts(alert.get("startsAt"))

    fp = compute_fingerprint(service, alert_type, env)
    return StandardizedAlert(
        raw_source="alertmanager", service=service, alert_type=alert_type,
        severity=severity, env=env, started_at=started_at,
        labels=labels, fingerprint=fp,
    )


def _map_pd_urgency_to_severity(urgency: str) -> str:
    return {"high": "P1", "low": "P3"}.get(urgency, "P2")


def _parse_ts(ts) -> datetime:
    if ts is None:
        return datetime.now(timezone.utc)
    if isinstance(ts, datetime):
        return ts
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
