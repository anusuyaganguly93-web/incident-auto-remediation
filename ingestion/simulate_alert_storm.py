"""
Demo script: fires N correlated alerts (simulating one bad deploy causing
a burst of alerts across replicas/probes) at the running ingestion service,
and prints how many incidents / Jira tickets actually got created.

Run: python3 ingestion/simulate_alert_storm.py --count 50
Requires the ingestion service running (docker-compose up).
"""
import argparse
import time
import requests
from datetime import datetime, timezone


def fire_storm(base_url: str, count: int, service: str, alert_type: str):
    incident_ids = set()
    jira_tickets = set()
    new_count = 0

    for i in range(count):
        payload = {
            "incident": {
                "service": service,
                "alert_type": alert_type,
                "urgency": "high",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "custom_details": {"env": "prod", "region": "ap-south-1"},
            }
        }
        resp = requests.post(f"{base_url}/webhooks/alerts/pagerduty", json=payload, timeout=5)
        resp.raise_for_status()
        data = resp.json()

        incident_ids.add(data["incident_id"])
        jira_tickets.add(data["jira_ticket_id"])
        if data["is_new"]:
            new_count += 1

        time.sleep(0.05)  # simulate alerts arriving in a tight burst, not instantaneously

    print(f"\nFired {count} correlated alerts.")
    print(f"  Distinct incidents created : {len(incident_ids)}")
    print(f"  Distinct Jira tickets      : {len(jira_tickets)}")
    print(f"  'is_new' True count        : {new_count}")
    print(f"  Final alert_count on incident: (check GET /incidents/{{id}} once phase 2 adds that route)")

    if len(incident_ids) == 1 and new_count == 1:
        print("\n✅ Dedup working as designed: storm collapsed into ONE incident.")
    else:
        print("\n❌ Dedup NOT collapsing correctly — investigate fingerprint logic.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--service", default="checkout-api")
    parser.add_argument("--alert-type", default="high_latency")
    args = parser.parse_args()

    fire_storm(args.url, args.count, args.service, args.alert_type)
