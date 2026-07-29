"""
Table lookup from tool_name -> function. This is the deterministic
dispatch boundary (Option B from the design conversation): the mapping
from an already-approved, already-fully-parameterized proposed command to
the actual function call is a plain dict lookup, never an LLM inference.
"""
from command_executor.tools.modify_infra import modify_infra
from command_executor.tools.deploy_service import deploy_service
from command_executor.tools.update_database import update_database

TOOL_REGISTRY = {
    "modify_infra": modify_infra,
    "deploy_service": deploy_service,
    "update_database": update_database,
}


async def dispatch(tool_name: str, params: dict) -> dict:
    tool_fn = TOOL_REGISTRY.get(tool_name)
    if tool_fn is None:
        raise ValueError(f"no tool registered for '{tool_name}'")
    return await tool_fn(**params)
