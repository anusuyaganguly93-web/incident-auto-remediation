"""
Standalone entrypoint for this slice of Phase 2 — no Temporal yet.

Run: python3 -m diagnostics.execute --service checkout-api --alert-type high_latency

This mirrors the design pseudocode:

    def execute(jira_id):
        infra_metadata = get_infra_meta(service)
        subagents: metrics, logs, deploy_history (parallel) -> runbook
        comment = llm.generate(evidence)
        post_comment_jira(comment)
        store_raw_evidence(...)
"""
import argparse
import asyncio
import time

from diagnostics.run_diagnostics import run_diagnostics
from diagnostics.llm_client import generate_triage_comment


async def execute(service: str, alert_type: str) -> dict:
    overall_start = time.monotonic()

    evidence, diagnostics_wall_ms = await run_diagnostics(service, alert_type)

    comment = generate_triage_comment(service, alert_type, evidence)

    overall_ms = (time.monotonic() - overall_start) * 1000

    return {
        "evidence": evidence,
        "diagnostics_wall_time_ms": diagnostics_wall_ms,
        "total_execute_time_ms": round(overall_ms, 1),
        "comment": comment,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", default="checkout-api")
    parser.add_argument("--alert-type", default="high_latency")
    args = parser.parse_args()

    result = asyncio.run(execute(args.service, args.alert_type))

    print(f"\n--- Evidence gathered (wall time: {result['diagnostics_wall_time_ms']}ms) ---")
    for e in result["evidence"]:
        print(f"[{e.subagent}] ({e.latency_ms}ms) {e.finding}")

    print(f"\n--- Total execute() time: {result['total_execute_time_ms']}ms ---")
    print(f"\n--- Comment to post to Jira ---\n")
    print(result["comment"])


if __name__ == "__main__":
    main()
