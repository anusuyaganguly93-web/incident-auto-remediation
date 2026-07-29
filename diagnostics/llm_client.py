"""
Thin wrapper around the Claude API, used ONLY for the final comment
synthesis step. This is intentionally the ONE place in the diagnostic
path an LLM is called for open-ended generation — every subagent above
this does deterministic script-based detection, per the design principle
that scripts detect, the LLM interprets and writes the human-facing summary.

Falls back to a deterministic mock if no ANTHROPIC_API_KEY is set, so the
whole pipeline is runnable and testable without needing an API key.
"""
import os

LLM_MOCK_MODE = os.getenv("ANTHROPIC_API_KEY") is None

SYSTEM_PROMPT = """You are a triage assistant posting a summary comment on an incident ticket \
for an on-call engineer. You are given evidence gathered by read-only diagnostic subagents \
(metrics, logs, deploy history, runbook match). 

Rules:
- ONLY state what the evidence directly supports. Do not speculate beyond it.
- Do not claim a root cause with certainty unless the evidence strongly and specifically supports it.
- If evidence points to a dependency (not the alerting service itself), say so explicitly.
- Keep it under 150 words. Use plain language a tired on-call engineer can scan in 10 seconds.
- End with the runbook's suggested next step if one was found, phrased as a suggestion, not a command.
"""


def generate_triage_comment(service: str, alert_type: str, evidence: list) -> str:
    if LLM_MOCK_MODE:
        return _mock_generate(service, alert_type, evidence)

    import anthropic
    client = anthropic.Anthropic()

    evidence_block = "\n".join(f"- [{e.subagent}] {e.finding}" for e in evidence)
    user_prompt = f"Service: {service}\nAlert type: {alert_type}\n\nEvidence:\n{evidence_block}"

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return "".join(block.text for block in response.content if block.type == "text")


def _mock_generate(service: str, alert_type: str, evidence: list) -> str:
    """Deterministic template used when no API key is present — keeps the
    pipeline fully runnable/testable offline."""
    lines = [f"**Triage summary — {service} ({alert_type})**", ""]
    for e in evidence:
        lines.append(f"- [{e.subagent}] {e.finding}")

    runbook_ev = next((e for e in evidence if e.subagent == "runbook"), None)
    if runbook_ev and runbook_ev.raw.get("best_match"):
        suggested = runbook_ev.raw["best_match"].get("suggested_commands", [])
        if suggested:
            lines.append("")
            lines.append(f"Suggested next step per runbook: {', '.join(suggested)}")

    lines.append("")
    lines.append("_(mock LLM output — set ANTHROPIC_API_KEY for real synthesis)_")
    return "\n".join(lines)
