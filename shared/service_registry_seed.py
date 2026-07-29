"""
Run once (or anytime you want to reset it): python3 shared/service_registry_seed.py

Seeds the same 3 services as the JSON fixture, but checkout-api now points
at the real toy target_app's /metrics and /logs endpoints (assumes
docker-compose's target-app service is mapped to localhost:8080 - this
script runs on the HOST, same as the worker process, so `localhost` is
correct here, unlike ingestion's DATABASE_URL which needs the docker
network hostname).
"""
import psycopg

DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/incidents"

ROWS = [
    dict(
        service="checkout-api",
        log_stream="checkout-api-prod",
        metric_namespace="checkout_api",
        deploy_pipeline_id="pipeline-checkout-001",
        db_identifiers=["checkout-db-primary"],
        asg_names=["asg-checkout-api-prod"],
        runbook_ids=["rb-high-latency-001", "rb-oom-001"],
        owning_team="payments-platform",
        criticality_tier=1,
        depends_on=["payment-api", "inventory-api"],
        metrics_url="http://localhost:8080/metrics",
        logs_url="http://localhost:8080/logs",
    ),
    dict(
        service="payment-api",
        log_stream="payment-api-prod",
        metric_namespace="payment_api",
        deploy_pipeline_id="pipeline-payment-001",
        db_identifiers=["payment-db-primary"],
        asg_names=["asg-payment-api-prod"],
        runbook_ids=["rb-high-latency-001", "rb-db-connection-pool-001"],
        owning_team="payments-platform",
        criticality_tier=1,
        depends_on=[],
        metrics_url=None,
        logs_url=None,
    ),
    dict(
        service="inventory-api",
        log_stream="inventory-api-prod",
        metric_namespace="inventory_api",
        deploy_pipeline_id="pipeline-inventory-001",
        db_identifiers=["inventory-db-primary"],
        asg_names=["asg-inventory-api-prod"],
        runbook_ids=["rb-high-error-rate-001"],
        owning_team="catalog-team",
        criticality_tier=2,
        depends_on=[],
        metrics_url=None,
        logs_url=None,
    ),
]


def main():
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            for r in ROWS:
                cur.execute(
                    """
                    INSERT INTO service_registry (
                        service, log_stream, metric_namespace, deploy_pipeline_id,
                        db_identifiers, asg_names, runbook_ids, owning_team,
                        criticality_tier, depends_on, metrics_url, logs_url
                    ) VALUES (
                        %(service)s, %(log_stream)s, %(metric_namespace)s, %(deploy_pipeline_id)s,
                        %(db_identifiers)s, %(asg_names)s, %(runbook_ids)s, %(owning_team)s,
                        %(criticality_tier)s, %(depends_on)s, %(metrics_url)s, %(logs_url)s
                    )
                    ON CONFLICT (service) DO UPDATE SET
                        log_stream = EXCLUDED.log_stream,
                        metric_namespace = EXCLUDED.metric_namespace,
                        deploy_pipeline_id = EXCLUDED.deploy_pipeline_id,
                        db_identifiers = EXCLUDED.db_identifiers,
                        asg_names = EXCLUDED.asg_names,
                        runbook_ids = EXCLUDED.runbook_ids,
                        owning_team = EXCLUDED.owning_team,
                        criticality_tier = EXCLUDED.criticality_tier,
                        depends_on = EXCLUDED.depends_on,
                        metrics_url = EXCLUDED.metrics_url,
                        logs_url = EXCLUDED.logs_url
                    """,
                    r,
                )
        conn.commit()
    print(f"seeded {len(ROWS)} service_registry rows")


if __name__ == "__main__":
    main()
