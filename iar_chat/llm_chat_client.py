"""
The conversational LLM call for IAR chat. Same mock-fallback pattern as
diagnostics/llm_client.py: falls back to a deterministic reply when no
ANTHROPIC_API_KEY is set, so the whole module is testable offline.

The system prompt is the important part here: IAR chat is explicitly
READ-ONLY and ADVISORY. It never claims to execute anything — per the
design decision locked earlier (Option B), the LLM's role in the write
path is zero. Any action still has to go through a human tagging a
specific pre-approved command on the Jira ticket (Phase 4, not built yet).
"""
import os

from shared.iar_chat_repo import ChatMessage

LLM_MOCK_MODE = os.getenv("ANTHROPIC_API_KEY") is None

SYSTEM_PROMPT = """You are IAR chat, helping an on-call engineer investigate a live incident.

Rules:
- Only answer based on the evidence provided below. If the evidence doesn't cover the
  question, say so plainly rather than speculating.
- You are READ-ONLY and ADVISORY. You never claim to take an action, execute a command,
  restart anything, or modify infrastructure. If asked to do so, explain that actions
  require the engineer to tag the agent on the Jira ticket with a specific approved
  command — you cannot do it here.
- Keep answers concise and practical. This is a real engineer investigating a live
  incident, not a report.
"""


def generate_chat_reply(context: str, history: list[ChatMessage]) -> str:
    if LLM_MOCK_MODE:
        return _mock_reply(context, history)

    import anthropic
    client = anthropic.Anthropic()

    messages = [{"role": m.role, "content": m.content} for m in history]

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        system=f"{SYSTEM_PROMPT}\n\nIncident context:\n{context}",
        messages=messages,
    )
    return "".join(block.text for block in response.content if block.type == "text")


def _mock_reply(context: str, history: list[ChatMessage]) -> str:
    """Deterministic reply used when no API key is present. Echoes the
    context back so tests (and manual smoke-testing) can verify retrieval
    is actually feeding the right evidence in, without needing a real key."""
    last_user_msg = history[-1].content if history else ""
    return (
        f"(mock reply — set ANTHROPIC_API_KEY for real chat)\n"
        f'You asked: "{last_user_msg}"\n\n'
        f"Based on the retrieved evidence:\n{context}\n\n"
        f"I'm read-only and advisory — I can't execute anything here. To take action, "
        f"tag the agent on the Jira ticket with an approved command."
    )
