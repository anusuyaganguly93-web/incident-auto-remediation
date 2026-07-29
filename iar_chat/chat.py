"""
The core IAR chat turn: user message in, assistant reply out, with
conversation history persisted per-incident so a multi-turn back-and-forth
(across multiple CLI/API calls, even across sessions) has memory.

No 90-second SLA here — this is explicitly the "slow path" subsystem from
the original design split. It can afford a full conversational retrieval
loop that the fast triage path never could.
"""
from shared.iar_chat_repo import IARChatRepo
from iar_chat.retrieval import build_context
from iar_chat.llm_chat_client import generate_chat_reply


def ask(repo: IARChatRepo, incident_id: str, user_message: str) -> str:
    # raises ValueError early (via build_context) if the incident doesn't
    # exist, BEFORE persisting the user's message - avoids leaving an
    # orphaned message for a nonexistent incident
    context = build_context(repo, incident_id)

    repo.save_chat_message(incident_id, "user", user_message)
    history = repo.get_chat_history(incident_id)  # includes the message just saved

    reply = generate_chat_reply(context, history)

    repo.save_chat_message(incident_id, "assistant", reply)
    return reply
