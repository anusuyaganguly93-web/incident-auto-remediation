"""
Simulates the human-approval trigger. In a real deployment this would be
a Jira comment-webhook (see the design conversation - "someone tags agent
on Jira"); since this project mocks Jira entirely, this CLI stands in for
that trigger: a human explicitly choosing one specific, already-bound
proposed command.

Run: python3 -m command_executor.approve_command <incident_id> <command_label>
"""
import argparse
import asyncio

from shared.command_repo import PostgresCommandRepo
from policy.rules import evaluate_policy
from command_executor.dispatcher import dispatch
from command_executor.verify import verify_resolution


async def approve_and_execute(incident_id: str, command_label: str, approved_by: str = "cli-demo") -> None:
    repo = PostgresCommandRepo()

    proposed = repo.get_active_proposed_command(incident_id, command_label)
    if proposed is None:
        print(f"No active (unconsumed, unexpired) proposed command '{command_label}' "
              f"found for incident {incident_id}.")
        return

    service_metadata = repo.get_service_metadata(proposed.params.get("service", ""))
    criticality_tier = service_metadata.get("criticality_tier", 3)

    decision = evaluate_policy(proposed.tool_name, criticality_tier)
    print(f"Policy check: {'APPROVED' if decision.approved else 'DENIED'} — {decision.reason}")

    if not decision.approved:
        repo.insert_command_execution(
            incident_id=incident_id, proposed_command_id=proposed.id,
            tool_name=proposed.tool_name, params=proposed.params,
            approved_by=approved_by, outcome="denied_by_policy",
        )
        return

    # mark consumed BEFORE dispatch, not after - a proposed command should
    # only ever be actionable once, even if execution itself fails partway
    repo.mark_consumed(proposed.id)

    print(f"Dispatching {proposed.tool_name}({proposed.params}) ...")
    result = await dispatch(proposed.tool_name, proposed.params)
    print(f"Action result: {result}")

    print("Waiting to verify resolution...")
    verification = await verify_resolution(proposed.params["target_url"])
    print(f"Verification: {verification}")

    repo.insert_command_execution(
        incident_id=incident_id, proposed_command_id=proposed.id,
        tool_name=proposed.tool_name, params=proposed.params,
        approved_by=approved_by, outcome=verification["outcome"],
        verification_metric="p99_latency_ms", verification_window_seconds=5,
    )
    print(f"\nOutcome recorded: {verification['outcome']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("incident_id")
    parser.add_argument("command_label", choices=["restart-pods", "rollback-deploy"])
    args = parser.parse_args()
    asyncio.run(approve_and_execute(args.incident_id, args.command_label))


if __name__ == "__main__":
    main()
