CREATE TABLE IF NOT EXISTS incidents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fingerprint TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    service TEXT NOT NULL,
    severity TEXT,
    jira_ticket_id TEXT,
    first_alert_at TIMESTAMPTZ NOT NULL,
    last_alert_at TIMESTAMPTZ NOT NULL,
    alert_count INT NOT NULL DEFAULT 1,
    confidence FLOAT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Only one OPEN incident per fingerprint at a time. This partial unique
-- index is what makes the dedup/upsert semantics correct and race-safe
-- at the database level, not just in application code.
CREATE UNIQUE INDEX IF NOT EXISTS idx_incidents_open_fingerprint
    ON incidents (fingerprint)
    WHERE status NOT IN ('resolved', 'escalated');

CREATE INDEX IF NOT EXISTS idx_incidents_service ON incidents (service);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents (status);
