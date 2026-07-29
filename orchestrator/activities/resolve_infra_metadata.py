"""
Temporal activity: resolves infra metadata for a service, from the
Postgres-backed service_registry table (migrations/002_create_service_registry.sql,
seeded via shared/service_registry_seed.py).

Previously fixture-backed in slice 1 — now real, as of Phase 2 slice 2 part 2.
"""
from temporalio import activity

from shared.service_registry_repo import get_service


@activity.defn
async def resolve_infra_metadata(service: str) -> dict:
    return get_service(service)

