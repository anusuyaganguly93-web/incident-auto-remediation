"""
Your service is the ONLY thing that creates Jira tickets for incidents
(Option A, locked earlier). PagerDuty/ZenDuty's native auto-ticketing
integration must be disabled in their dashboards, or you'll get duplicate
tickets even with correct dedup logic here.

This module is deliberately thin so it's easy to swap the real Jira API
client in for JIRA_MOCK_MODE=false without touching any calling code.
"""
import os
import uuid

JIRA_MOCK_MODE = os.getenv("JIRA_MOCK_MODE", "true").lower() == "true"


class JiraClient:
    def __init__(self, base_url: str = "", email: str = "", api_token: str = ""):
        self.base_url = base_url
        self.email = email
        self.api_token = api_token

    def create_ticket(self, service: str, severity: str, summary: str, description: str) -> str:
        if JIRA_MOCK_MODE:
            ticket_id = f"INC-{uuid.uuid4().hex[:6].upper()}"
            print(f"[MOCK JIRA] Created {ticket_id} for service={service} severity={severity}")
            return ticket_id

        import requests
        resp = requests.post(
            f"{self.base_url}/rest/api/3/issue",
            auth=(self.email, self.api_token),
            json={
                "fields": {
                    "project": {"key": "INC"},
                    "summary": summary,
                    "description": description,
                    "issuetype": {"name": "Incident"},
                    "priority": {"name": severity},
                }
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()["key"]

    def post_comment(self, ticket_id: str, body: str) -> None:
        if JIRA_MOCK_MODE:
            print(f"[MOCK JIRA] Comment on {ticket_id}: {body}")
            return

        import requests
        requests.post(
            f"{self.base_url}/rest/api/3/issue/{ticket_id}/comment",
            auth=(self.email, self.api_token),
            json={"body": body},
            timeout=10,
        )
