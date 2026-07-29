"""
Builds the context block IAR chat feeds the LLM. Deliberately simple for
this slice: the evidence for a single incident is small (4 rows), so this
is closer to "structured context assembly" than a true vector-search RAG
pipeline. Cross-incident semantic search (e.g. "have we seen this pattern
before" against resolved incidents) is a natural extension, not built here
— see README's "what's deferred" for this slice.
"""
from shared.iar_chat_repo import IARChatRepo


def build_context(repo: IARChatRepo, incident_id: str) -> str:
    incident = repo.get_incident(incident_id)
    if incident is None:
        raise ValueError(f"no incident found for incident_id={incident_id}")

    evidence = repo.get_evidence(incident_id)

    lines = [
        f"Incident: {incident_id}",
        f"Service: {incident.get('service')}",
        f"Status: {incident.get('status')}",
        f"Severity: {incident.get('severity')}",
        f"Alert count: {incident.get('alert_count')}",
        "",
        "Diagnostic evidence gathered during automated triage:",
    ]

    if not evidence:
        lines.append("(no evidence recorded yet for this incident)")
    else:
        for e in evidence:
            payload = e.get("payload", {})
            finding = payload.get("finding", str(payload)) if isinstance(payload, dict) else str(payload)
            lines.append(f"- [{e.get('event_type')}] {finding}")

    return "\n".join(lines)
