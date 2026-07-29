CREATE TABLE IF NOT EXISTS proposed_commands (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id UUID REFERENCES incidents(id),
    command_label TEXT NOT NULL,   -- "restart-pods", "rollback-deploy" - matches runbook suggested_commands
    tool_name TEXT NOT NULL,       -- "modify_infra", "deploy_service" - the MCP-style tool to dispatch to
    params JSONB NOT NULL,         -- fully bound at proposal time, no placeholders left to interpret
    proposed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    consumed BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_proposed_commands_incident_id ON proposed_commands (incident_id);
