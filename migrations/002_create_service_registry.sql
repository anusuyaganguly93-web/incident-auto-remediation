CREATE TABLE IF NOT EXISTS service_registry (
    service TEXT PRIMARY KEY,
    log_stream TEXT,
    metric_namespace TEXT,
    deploy_pipeline_id TEXT,
    db_identifiers TEXT[],
    asg_names TEXT[],
    runbook_ids TEXT[],
    owning_team TEXT,
    criticality_tier INT,
    depends_on TEXT[],
    metrics_url TEXT,   -- if set, subagents query this live instead of fixture data
    logs_url TEXT
);
