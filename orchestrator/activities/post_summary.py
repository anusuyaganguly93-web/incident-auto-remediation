"""
Temporal activity: synthesizes the triage comment via diagnostics.llm_client
(mock fallback if no ANTHROPIC_API_KEY, exactly as in Phase 2 slice 1) and
posts it to Jira via ingestion.jira_client (mock mode by default).

As of Phase 4, also appends a menu of any executable proposed commands
(from orchestrator/activities/propose_commands.py) so a human reading the
ticket sees exactly what they can tag the agent with — approving a command
is a dispatch by label (see command_executor/approve_command.py), never
free-text interpretation.

NOTE: both underlying clients make blocking/sync calls (anthropic SDK,
requests). Running them inside an `async def` activity blocks the worker's
event loop for the duration of the call. Fine for this portfolio-scale
single-worker demo; in production you'd either use the async anthropic
client or run this as a sync activity with a dedicated activity_executor
on the Worker. Flagging as a known simplification, not fixing now.
"""
from dataclasses import dataclass, field
import os

from temporalio import activity

from diagnostics.llm_client import generate_triage_comment
from diagnostics.subagents.base import Evidence
from ingestion.jira_client import JiraClient


@dataclass
class GenerateAndPostCommentInput:
    service: str
    alert_type: str
    evidence_dicts: list[dict]
    jira_ticket_id: str
    proposed_commands: list[dict] = field(default_factory=list)


@activity.defn
async def generate_and_post_comment(input: GenerateAndPostCommentInput) -> str:
    evidence = [Evidence(**e) for e in input.evidence_dicts]
    comment = generate_triage_comment(input.service, input.alert_type, evidence)

    if input.proposed_commands:
        menu_lines = ["", "**Available actions** (tag the agent with the label to run one):"]
        for pc in input.proposed_commands:
            menu_lines.append(f"- `{pc['command_label']}`")
        comment += "\n" + "\n".join(menu_lines)

    jira = JiraClient(
        base_url=os.getenv("JIRA_BASE_URL", ""),
        email=os.getenv("JIRA_EMAIL", ""),
        api_token=os.getenv("JIRA_API_TOKEN", ""),
    )
    jira.post_comment(input.jira_ticket_id, comment)

    activity.logger.info(f"posted triage comment to {input.jira_ticket_id}")
    return comment
