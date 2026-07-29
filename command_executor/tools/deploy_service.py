"""
MCP-style action tool: rollback. Simulated as a full chaos reset (both
latency and error-rate) — representing a rollback removing whatever a bad
deploy introduced, a stronger remediation than a bare restart.
"""
async def deploy_service(action: str, service: str, target_url: str,
                          target_version: str | None = None) -> dict:
    if action != "rollback":
        raise ValueError(f"deploy_service: unsupported action '{action}'")

    import httpx
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(f"{target_url}/chaos", json={"latency": False, "errors": False})
        resp.raise_for_status()
        return {"action": action, "service": service, "target_version": target_version, "result": resp.json()}
