CREATE TABLE IF NOT EXISTS incident_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id UUID REFERENCES incidents(id),
    event_type TEXT NOT NULL,   -- evidence_metrics | evidence_logs | evidence_deploy_history | evidence_runbook
    payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_incident_events_incident_id ON incident_events (incident_id);
