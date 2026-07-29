"""
Stub. Demonstrates the tool-binding *pattern* without a concrete backing
action - there's no real database migration scenario in this toy system.
The policy gate denies this tool outright (not reversible, high blast
radius, see policy/rules.py) before dispatch would ever reach here, so
this function existing mainly documents what a real implementation's
signature would look like.
"""
async def update_database(migration_id: str, service: str) -> dict:
    raise NotImplementedError(
        "update_database is a stub, not implemented for this project — "
        "and denied by policy before dispatch regardless"
    )
