"""
Run with: pytest tests/test_iar_chat.py -v

Uses InMemoryIARChatRepo + the mock LLM fallback (no ANTHROPIC_API_KEY
needed), so this runs with zero external dependencies - no Postgres,
no network, no API key.
"""
import pytest

from shared.iar_chat_repo import InMemoryIARChatRepo
from iar_chat.chat import ask
from iar_chat.retrieval import build_context


def make_seeded_repo():
    repo = InMemoryIARChatRepo()
    repo.seed_incident(
        "inc-1",
        {"service": "checkout-api", "status": "new", "severity": "P1", "alert_count": 5},
        [
            {"event_type": "evidence_metrics", "payload": {"finding": "p99_latency_ms anomalous: 120 -> 900"}},
            {"event_type": "evidence_deploy_history", "payload": {"finding": "payment-api deployed v2.8.3 1m ago"}},
        ],
    )
    return repo


def test_context_includes_service_and_evidence_findings():
    repo = make_seeded_repo()
    context = build_context(repo, "inc-1")
    assert "checkout-api" in context
    assert "p99_latency_ms anomalous: 120 -> 900" in context
    assert "payment-api deployed v2.8.3" in context


def test_context_raises_for_missing_incident():
    repo = InMemoryIARChatRepo()
    with pytest.raises(ValueError):
        build_context(repo, "nonexistent")


def test_ask_returns_reply_referencing_retrieved_evidence():
    repo = make_seeded_repo()
    reply = ask(repo, "inc-1", "what's going on with checkout-api?")
    assert "p99_latency_ms anomalous" in reply
    assert "read-only" in reply.lower()


def test_ask_persists_both_user_and_assistant_messages():
    repo = make_seeded_repo()
    ask(repo, "inc-1", "what's going on?")
    history = repo.get_chat_history("inc-1")
    assert len(history) == 2
    assert history[0].role == "user"
    assert history[0].content == "what's going on?"
    assert history[1].role == "assistant"


def test_multi_turn_history_accumulates_across_calls():
    repo = make_seeded_repo()
    ask(repo, "inc-1", "first question")
    ask(repo, "inc-1", "second question")

    history = repo.get_chat_history("inc-1")
    assert len(history) == 4  # 2 user + 2 assistant, in order
    assert history[0].content == "first question"
    assert history[2].content == "second question"


def test_ask_raises_for_missing_incident_without_persisting_orphan_message():
    repo = InMemoryIARChatRepo()
    with pytest.raises(ValueError):
        ask(repo, "nonexistent", "hello")
    # confirm no message was left behind for a nonexistent incident
    assert repo.get_chat_history("nonexistent") == []


def test_separate_incidents_have_independent_conversation_history():
    repo = make_seeded_repo()
    repo.seed_incident(
        "inc-2",
        {"service": "payment-api", "status": "new", "severity": "P2", "alert_count": 1},
        [],
    )
    ask(repo, "inc-1", "question about checkout")
    ask(repo, "inc-2", "question about payment")

    assert len(repo.get_chat_history("inc-1")) == 2
    assert len(repo.get_chat_history("inc-2")) == 2
    assert "checkout" in repo.get_chat_history("inc-1")[0].content
    assert "payment" in repo.get_chat_history("inc-2")[0].content
