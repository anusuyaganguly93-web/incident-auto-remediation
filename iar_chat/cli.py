"""
Run: python3 -m iar_chat.cli <incident_id>

Interactive terminal chat against a real incident's evidence, backed by
Postgres. Get an incident_id from the ingestion logs (or query Postgres
directly) after running the Phase 2 demo.
"""
import argparse

from shared.iar_chat_repo import PostgresIARChatRepo
from iar_chat.chat import ask


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("incident_id")
    args = parser.parse_args()

    repo = PostgresIARChatRepo()
    incident = repo.get_incident(args.incident_id)
    if incident is None:
        print(f"No incident found with id={args.incident_id}")
        return

    print(f"IAR chat — incident {args.incident_id} ({incident.get('service')}, status={incident.get('status')})")
    print("Type 'exit' to quit.\n")

    # replay any prior conversation for this incident, so re-attaching to
    # an incident you've chatted about before shows the history
    for msg in repo.get_chat_history(args.incident_id):
        prefix = "you>" if msg.role == "user" else "iar-chat>"
        print(f"{prefix} {msg.content}\n")

    while True:
        try:
            user_message = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if user_message.lower() in ("exit", "quit"):
            break
        if not user_message:
            continue

        reply = ask(repo, args.incident_id, user_message)
        print(f"\niar-chat> {reply}\n")


if __name__ == "__main__":
    main()
