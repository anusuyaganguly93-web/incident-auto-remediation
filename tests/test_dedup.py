"""
Run with: pytest tests/test_dedup.py -v

Proves the core claim of the whole ingestion design: a correlated storm
of alerts from one bad deploy collapses into exactly ONE incident and
ONE Jira ticket, not N.
"""
from datetime import datetime, timedelta, timezone

from shared.db import InMemoryIncidentRepo
from shared.fingerprint import compute_fingerprint
from shared.schemas import StandardizedAlert
from ingestion.dedup import process_alert, should_reescalate


def make_alert(service="checkout-api", alert_type="high_latency", env="prod", offset_seconds=0):
    started_at = datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)
    return StandardizedAlert(
        raw_source="pagerduty",
        service=service,
        alert_type=alert_type,
        severity="P1",
        env=env,
        started_at=started_at,
        fingerprint=compute_fingerprint(service, alert_type, env),
    )


def test_first_alert_creates_new_incident():
    repo = InMemoryIncidentRepo()
    result = process_alert(repo, make_alert())
    assert result.is_new is True
    assert result.incident.alert_count == 1


def test_correlated_storm_collapses_to_one_incident():
    """The headline demo: 50 alerts from one bad deploy -> 1 incident."""
    repo = InMemoryIncidentRepo()

    results = [process_alert(repo, make_alert(offset_seconds=i)) for i in range(50)]

    new_incident_count = sum(1 for r in results if r.is_new)
    assert new_incident_count == 1, "exactly one incident should be created, not 50"

    final_incident = results[-1].incident
    assert final_incident.alert_count == 50
    # all 50 results should point at the SAME incident id
    assert len({r.incident.id for r in results}) == 1


def test_different_services_create_separate_incidents():
    repo = InMemoryIncidentRepo()
    r1 = process_alert(repo, make_alert(service="checkout-api"))
    r2 = process_alert(repo, make_alert(service="payment-api"))
    assert r1.is_new and r2.is_new
    assert r1.incident.id != r2.incident.id


def test_different_alert_types_on_same_service_are_separate_incidents():
    repo = InMemoryIncidentRepo()
    r1 = process_alert(repo, make_alert(alert_type="high_latency"))
    r2 = process_alert(repo, make_alert(alert_type="high_error_rate"))
    assert r1.is_new and r2.is_new
    assert r1.incident.id != r2.incident.id


def test_reescalation_threshold_crossing():
    assert should_reescalate(alert_count_before=9, alert_count_after=10) is True
    assert should_reescalate(alert_count_before=10, alert_count_after=11) is False
    assert should_reescalate(alert_count_before=95, alert_count_after=100) is True
    assert should_reescalate(alert_count_before=5, alert_count_after=9) is False
