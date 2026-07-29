"""
Deterministic fingerprinting so that a correlated storm of alerts
(e.g. 50 alerts from one bad deploy) collapses into ONE incident,
rather than one Jira ticket per alert.

Fingerprint = hash(service, alert_type, env) bucketed into a coarse
time window. Two alerts for the same (service, alert_type, env) within
the same open incident window are considered the SAME incident.

NOTE: we deliberately do NOT include exact timestamp or raw alert id
in the fingerprint — that would defeat the whole purpose of dedup.
"""
import hashlib


def compute_fingerprint(service: str, alert_type: str, env: str) -> str:
    """
    Returns a stable string fingerprint. This is intentionally simple —
    it does not bucket by time. Whether an alert collapses into an
    EXISTING incident or starts a NEW one is governed by whether there's
    still an OPEN incident row with this fingerprint (see dedup.py),
    not by a time bucket baked into the hash itself.
    """
    key = f"service:{service}|type:{alert_type}|env:{env}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return f"{service}:{alert_type}:{env}:{digest}"


def generalize_fingerprint_pattern(service: str, alert_type: str) -> str:
    """
    Used later (phase 2+) for rolling up command execution outcomes
    across ALL services of a given alert_type, e.g. for confidence scoring.
    Not used in phase 1, but defined here so the contract is stable.
    """
    return f"pattern:{alert_type}"
