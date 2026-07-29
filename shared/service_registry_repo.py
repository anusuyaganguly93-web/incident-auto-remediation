"""
Real service_registry lookups, backed by Postgres instead of
diagnostics/fixtures/service_registry.json.

Used by orchestrator/activities/*.py (i.e. only in the real Temporal path).
diagnostics/execute.py and tests/test_diagnostics.py keep using the JSON
fixture directly and are UNCHANGED by this - see the `service_registry`
parameter added to diagnostics.run_diagnostics.run_diagnostics(), which
defaults to the fixture when not explicitly passed a registry dict.
"""
import os
import psycopg

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/incidents")

COLUMNS = [
    "service", "log_stream", "metric_namespace", "deploy_pipeline_id",
    "db_identifiers", "asg_names", "runbook_ids", "owning_team",
    "criticality_tier", "depends_on", "metrics_url", "logs_url",
]


def get_service_registry() -> dict:
    """Returns the full registry as {service_name: metadata_dict}, same shape
    as the JSON fixture (plus metrics_url/logs_url keys)."""
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {','.join(COLUMNS)} FROM service_registry")
            rows = cur.fetchall()
    return {row[0]: dict(zip(COLUMNS, row)) for row in rows}


def get_service(service: str) -> dict:
    registry = get_service_registry()
    metadata = registry.get(service)
    if metadata is None:
        raise ValueError(f"no service_registry entry for service={service}")
    return metadata
