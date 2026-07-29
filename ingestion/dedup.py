"""
The single most important piece of logic in the whole system:

Turns "how many alerts fired" into "how many INCIDENTS exist", and makes
sure a Jira ticket is created ONLY on a genuinely new incident — never
on every alert. This is what prevents a 50-alert correlated storm from
becoming 50 Jira tickets.

IMPORTANT: PagerDuty/ZenDuty's own native "auto-create Jira ticket"
integration must be DISABLED. Ticket creation happens here, and only here,
gated on `is_new`.
"""
from dataclasses import dataclass

from shared.db import IncidentRepo
from shared.fingerprint import compute_fingerprint
from shared.schemas import StandardizedAlert, Incident


@dataclass
class DedupResult:
    incident: Incident
    is_new: bool


def process_alert(repo: IncidentRepo, alert: StandardizedAlert) -> DedupResult:
    """
    Idempotent: calling this twice with the same alert produces the same
    incident, just bumped twice. Safe to retry.
    """
    fingerprint = alert.fingerprint or compute_fingerprint(
        alert.service, alert.alert_type, alert.env
    )

    existing = repo.get_open_incident_by_fingerprint(fingerprint)

    if existing is None:
        incident = repo.create_incident(
            fingerprint=fingerprint,
            service=alert.service,
            severity=alert.severity,
            started_at=alert.started_at,
        )
        return DedupResult(incident=incident, is_new=True)

    incident = repo.bump_incident(existing, last_alert_at=alert.started_at)
    return DedupResult(incident=incident, is_new=False)


# Thresholds at which we re-notify on an EXISTING incident even though we
# don't create a new ticket — otherwise the on-call engineer has no signal
# that things are getting worse while 49 more alerts pile in silently.
REESCALATION_ALERT_COUNT_MULTIPLES = (10, 100, 1000)


def should_reescalate(alert_count_before: int, alert_count_after: int) -> bool:
    """
    Returns True if alert_count just crossed one of the re-escalation
    thresholds. Used by ingestion/main.py to decide whether to post a
    lightweight "still firing, now Nx" comment on the existing Jira ticket.
    """
    for threshold in REESCALATION_ALERT_COUNT_MULTIPLES:
        if alert_count_before < threshold <= alert_count_after:
            return True
    return False
