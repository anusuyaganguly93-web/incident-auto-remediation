CREATE TABLE IF NOT EXISTS incident_chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id UUID REFERENCES incidents(id),
    role TEXT NOT NULL,   -- 'user' | 'assistant'
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_incident_chat_messages_incident_id
    ON incident_chat_messages (incident_id, created_at);
