CREATE TABLE IF NOT EXISTS command_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id UUID REFERENCES incidents(id),
    proposed_command_id UUID REFERENCES proposed_commands(id),
    tool_name TEXT NOT NULL,
    params JSONB NOT NULL,
    approved_by TEXT,               -- who/what triggered execution (simulated for now - no real Jira webhook)
    executed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    verification_metric TEXT,
    verification_window_seconds INT,
    outcome TEXT NOT NULL,          -- 'resolved' | 'regressed' | 'insufficient_data' | 'denied_by_policy'
    resolved_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_command_executions_incident_id ON command_executions (incident_id);
