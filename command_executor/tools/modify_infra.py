"""
MCP-style action tool: restart. For this toy system, "restarting" a
service is simulated by clearing target_app's induced latency chaos -
functionally the same effect a real pod restart clearing a wedged
connection or hung process would have on the metrics it exposes.
"""
async def modify_infra(action: str, service: str, target_url: str) -> dict:
    if action != "restart":
        raise ValueError(f"modify_infra: unsupported action '{action}'")

    import httpx
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(f"{target_url}/chaos", json={"latency": False})
        resp.raise_for_status()
        return {"action": action, "service": service, "result": resp.json()}
