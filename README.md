# Incident Auto-Remediation System

An incident auto-remediation system, similar in spirit to incident.io: ingests
alerts, deduplicates and triages them, gathers diagnostic evidence in
parallel, posts a synthesized summary, and — with human approval — actually
executes a remediation and verifies it worked. All within a 90-second p99
time-to-first-action, at a steady-state load of 5,000 alerts/day.

Built as a portfolio project to demonstrate systems design under real
constraints (coordination-heavy, real-time, correctness-critical), not just
"wire an LLM to some tools." See [`docs/architecture.md`](docs/architecture.md)
for the full design rationale, and [`docs/DEBUGGING_LOG.md`](docs/DEBUGGING_LOG.md)
for a chronological account of everything that broke during implementation
and how it was fixed — including one genuine logic bug, found and fixed live.

This README is organized **phase by phase**. Each phase section is
self-contained: its own architecture diagram, how to run it, and exactly
what output confirms it worked. Phases build on each other in order —
Phase 2 needs Phase 1's ingestion running, Phase 3 needs Phase 2's evidence
to exist, Phase 4 needs Phase 2's runbook match to exist.

## Status

| Component | Status |
|---|---|
| Phase 1 — Webhook ingestion, dedup/upsert, conditional Jira ticketing | ✅ Built & verified |
| Phase 2 — Diagnostic subagents, parallel fan-out, Temporal orchestration, live target service | ✅ Built & verified |
| Phase 3 — IAR chat (RAG, single-incident context + conversation memory) | ✅ Built & verified |
| Phase 4 — Policy gate + deterministic command dispatch + verification | ✅ Built & verified |
| Command execution wired into Temporal (currently a standalone CLI) | ⬜ Not built (see roadmap) |
| Cross-incident semantic search (embeddings + pgvector) | ⬜ Not built (see roadmap) |
| Confidence scoring + auto-promotion | ⬜ Deliberately deferred (see roadmap) |

## Full system architecture (all phases)

```
PagerDuty/ZenDuty webhook
        │
        ▼
Ingestion: normalize → fingerprint → dedup/upsert (Postgres)          ── Phase 1
        │
        ├── new fingerprint ──► create Jira ticket ──► start Temporal workflow
        └── existing open fingerprint ──► bump alert_count (no duplicate ticket)
                                                              │
                                                              ▼
                                          IncidentWorkflow (Temporal, durable)   ── Phase 2
                                                              │
                              resolve_infra_metadata (Postgres service_registry)
                                                              │
                          run_diagnostics_activity — PARALLEL fan-out:
                          ┌──────────┬──────────┬────────────────┬──────────┐
                          metrics    logs    deploy_history    runbook
                          (live)    (live)    (fixture)       (fixture)
                          └──────────┴──────────┴────────────────┴──────────┘
                                                              │
                                              propose_commands_activity        ── Phase 4
                                        (binds runbook's suggested_commands
                                         to fully-specified tool calls)
                                                              │
                          ┌───────────────────────────────────┴──────────────┐
                          generate_and_post_comment (LLM)          store_evidence (Postgres)
                          — runs concurrently, not sequentially —


        ═══════════════════════ no 90s SLA below this line ═══════════════════════

        IAR chat (Postgres RAG, conversational, multi-turn)                    ── Phase 3
        reads: incidents + incident_events + incident_chat_messages
        read-only / advisory — never executes anything itself

        Human approves a proposed command (simulated Jira tag)                 ── Phase 4
                │
                ▼
        policy gate (reversibility × blast radius) → dispatcher (table lookup,
        never an LLM decision) → real MCP-style tool call → target_app
                │
                ▼
        verification (reuses anomaly_detection.py) → command_executions
```

"Live" = queried from the real `target_app` toy service via HTTP.
"Fixture" = deliberately kept as static JSON — a fake CI/CD pipeline or
keyword-scorer standing in for embedding search wouldn't add real signal for
a demo, so effort went into the pieces that would.

## Project structure

```
ingestion/          webhook → normalize → dedup/upsert → conditional Jira ticket
diagnostics/         subagents (metrics/logs/deploy_history/runbook), scripts,
                      LLM client, fixtures, standalone execute() entrypoint
orchestrator/         Temporal workflow, activities, worker, client helper
iar_chat/              retrieval, LLM chat client, conversation orchestration, CLI
policy/                 rule-based policy gate (reversibility × blast radius)
command_executor/       MCP-style tools, dispatcher, verification, approval CLI
target_app/           toy service standing in for checkout-api, chaos injection
shared/                data contracts, fingerprinting, DB repos
migrations/            Postgres schema (001-006, one per phase's new tables)
tests/                  pytest suites, one file per phase's logic
docs/                  architecture.md, DEBUGGING_LOG.md
```

## Prerequisites

- Docker Desktop
- Python 3.11+
- [Temporal CLI](https://docs.temporal.io/cli#install) (`brew install temporal` on macOS)
- Optional: `ANTHROPIC_API_KEY` for real LLM synthesis, in both the triage
  comment (Phase 2) and IAR chat (Phase 3) — falls back to a deterministic
  mock otherwise. The whole system is fully runnable and testable without
  an API key; every "Verified results" block below was captured in mock mode.

### One-time setup (before any phase)

```bash
git clone <this repo> && cd incident-auto-remediation
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

# Phase 1 — Ingestion, Dedup, Conditional Jira Ticketing

## Architecture

```
PagerDuty / ZenDuty / AlertManager
        │  webhook: POST /webhooks/alerts/{source}
        ▼
Ingestion service (FastAPI)
        │
        ▼
normalize()  →  StandardizedAlert
        │
        ▼
compute_fingerprint(service, alert_type, env)
        │
        ▼
Dedup/upsert against Postgres `incidents` table
  partial unique index: at most ONE open incident per fingerprint
        │
   ┌────┴─────────────────────────────┐
   ▼                                  ▼
new fingerprint                existing open fingerprint
   │                                  │
   ▼                                  ▼
create Jira ticket (mocked)     bump alert_count
enqueue for Phase 2 triage      re-escalation comment at 10x/100x/1000x
```

The dedup/upsert step is the single most load-bearing piece of the whole
system: without it, one bad deploy firing 50-200 correlated alerts in a
minute would flood the on-call board with 50-200 tickets instead of one.

## How to run

```bash
docker-compose up --build
```
Starts Postgres (with `migrations/001_create_incidents.sql` auto-applied on
a fresh volume) and the ingestion service on `localhost:8000`.

Fire a correlated alert storm at it:
```bash
python3 ingestion/simulate_alert_storm.py --count 50
```

## What to check

**The storm should collapse into exactly one incident, one ticket:**
```
Fired 50 correlated alerts.
  Distinct incidents created : 1
  Distinct Jira tickets      : 1
  'is_new' True count        : 1
✅ Dedup working as designed: storm collapsed into ONE incident.
```

**Confirm independently via direct DB query:**
```bash
docker exec -it incident-auto-remediation-postgres-1 psql -U postgres -d incidents -c \
  "SELECT id, fingerprint, alert_count, jira_ticket_id, status FROM incidents;"
```
```
                  id                  |                   fingerprint                   | alert_count | jira_ticket_id | status
--------------------------------------+-------------------------------------------------+-------------+----------------+--------
 c3177366-c723-433a-a793-f98d940d4231 | checkout-api:high_latency:prod:80b7642a02ea1e59 |          55 | INC-B5951A     | new
```
(`55`, not `50` — this row accumulated alerts across multiple test sessions
over several days, which is itself evidence dedup works correctly even
across container restarts, not just within one run. See debugging log #8.)

**Run the test suite:**
```bash
pytest tests/test_dedup.py -v
```
```
tests/test_dedup.py::test_first_alert_creates_new_incident PASSED
tests/test_dedup.py::test_correlated_storm_collapses_to_one_incident PASSED
tests/test_dedup.py::test_different_services_create_separate_incidents PASSED
tests/test_dedup.py::test_different_alert_types_on_same_service_are_separate_incidents PASSED
tests/test_dedup.py::test_reescalation_threshold_crossing PASSED
```

---

# Phase 2 — Diagnostic Subagents + Temporal Orchestration + Live Target Service

## Architecture

```
[Phase 1: new incident created]
        │
        ▼
Temporal Client starts IncidentWorkflow — workflow_id = incident_id
  (idempotent: a duplicate enqueue can't double-trigger triage)
        │
        ▼
┌──────────────────────────── IncidentWorkflow ────────────────────────────┐
│                                                                            │
│  resolve_infra_metadata ──► Postgres `service_registry`                  │
│         │                                                                  │
│         ▼                                                                  │
│  run_diagnostics_activity — PARALLEL fan-out (asyncio.gather):            │
│  this is load-bearing for the 90s budget, not an optimization             │
│                                                                             │
│  ┌───────────┬───────────┬─────────────────┬───────────┐                  │
│  │  metrics  │   logs    │ deploy_history  │  runbook  │                  │
│  │ query →   │ query →   │  one-hop        │ keyword   │                  │
│  │ target_app│ target_app│  dependency     │ match     │                  │
│  │ /metrics  │  /logs    │  walk (fixture) │ (fixture) │                  │
│  │ anomaly_  │ filter +  │                 │           │                  │
│  │ detection │ cluster   │                 │           │                  │
│  │  .py      │           │                 │           │                  │
│  └───────────┴───────────┴─────────────────┴───────────┘                  │
│         │                                                                   │
│         ▼                                                                   │
│  ┌────────────────────────────┴──────────────────────┐                     │
│  generate_and_post_comment (LLM)          store_evidence (Postgres)        │
│  — run CONCURRENTLY, not sequentially —                                    │
└─────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
target_app (toy checkout-api stand-in, real FastAPI service)
  GET  /metrics   — live rolling window of p99_latency_ms / error_rate_pct
  GET  /logs      — live rolling window of structured log lines
  POST /chaos     — inject_chaos.py toggles simulated latency/error spikes
```

## How to run

**Terminal 1 — Temporal dev server** (leave running):
```bash
temporal server start-dev
```
Web UI at http://localhost:8233.

**Terminal 2 — Docker Compose** (leave running — same command as Phase 1,
now also builds `target-app`):
```bash
docker-compose up --build
```

**One-time seed** (any terminal, once Postgres is up):
```bash
python3 shared/service_registry_seed.py
```
Should print `seeded 3 service_registry rows`.

**Terminal 3 — the Temporal worker** (leave running):
```bash
source venv/bin/activate
python3 -m orchestrator.worker
```
Should print `Worker started. Polling task queue 'incident-triage' on localhost:7233...`

⚠️ **Restart this process after any code change** — Python doesn't
hot-reload (debugging log #13).

**Terminal 4 — the actual demo:**
```bash
source venv/bin/activate
curl http://localhost:8080/metrics                    # confirm target_app is healthy
python3 target_app/inject_chaos.py --latency on        # inject a latency spike
python3 ingestion/simulate_alert_storm.py --count 5    # fire the alert
```

To reset for a clean re-run:
```bash
python3 target_app/inject_chaos.py --latency off --errors off
docker-compose restart target-app   # gives a clean baseline window — see gotcha #5
```

## What to check

**Terminal 2 (ingestion) should show:**
```
[MOCK JIRA] Created INC-530881 for service=checkout-api severity=P1
[TEMPORAL] started workflow 8b361b1a-... for incident 8b361b1a-...
```

**Terminal 3 (worker) should show the live HTTP calls, parallel fan-out
timing, and the synthesized comment:**
```
INFO:httpx:HTTP Request: GET http://localhost:8080/logs "HTTP/1.1 200 OK"
INFO:httpx:HTTP Request: GET http://localhost:8080/metrics "HTTP/1.1 200 OK"
INFO:temporalio.activity:diagnostics parallel fan-out wall time: 612.7ms
INFO:temporalio.activity:stored 4 evidence rows for incident 8b361b1a-4acf-4e26-8275-dda7caa68649

[MOCK JIRA] Comment on INC-530881: **Triage summary — checkout-api (high_latency)**
- [metrics] p99_latency_ms anomalous: 117.01 -> 906.43 (+674.7%, z=163.95); error_rate_pct anomalous: 0.16 -> 4.57 (+2704.7%, z=86.44)
- [logs] [ERROR] 'upstream call to payment-api timed out after Nms' x16
- [deploy_history] payment-api deployed v2.8.3 at 2026-07-25T14:01:45Z (1m ago)
- [runbook] best match: 'High latency due to downstream dependency timeout' (score=2)
Suggested next step per runbook: restart-pods, rollback-deploy
```

The `117.01 -> 906.43` numbers are randomly generated **live** by
`target_app` (`random.gauss()`) — different on every run, unlike the static
fixture values (always exactly `121.8 -> 895.17`). This is the detail that
confirms the live HTTP path is actually being exercised, not silently
falling back to fixture data.

**Cross-service root cause attribution** — the scenario the deploy-history
one-hop dependency walk was specifically built to catch: `checkout-api`
fires the alert, but the evidence correctly attributes it to a deploy on
its *dependency*, `payment-api`, one minute earlier. The system never
recommends "restart checkout-api," which would be the wrong fix.

**Confirm evidence persistence:**
```bash
docker exec -it incident-auto-remediation-postgres-1 psql -U postgres -d incidents -c \
  "SELECT event_type, created_at FROM incident_events WHERE incident_id = '<incident_id>' ORDER BY created_at;"
```
```
       event_type        |          created_at
-------------------------+-------------------------------
 evidence_metrics        | 2026-07-25 10:53:15.557862+00
 evidence_logs           | 2026-07-25 10:53:15.557862+00
 evidence_deploy_history | 2026-07-25 10:53:15.557862+00
 evidence_runbook        | 2026-07-25 10:53:15.557862+00
```

**Run the test suite:**
```bash
pytest tests/test_diagnostics.py -v
```
```
tests/test_diagnostics.py::test_anomaly_detection_catches_injected_latency_spike PASSED
tests/test_diagnostics.py::test_anomaly_detection_does_not_flag_flat_series PASSED
tests/test_diagnostics.py::test_log_filter_clusters_repeated_errors_and_drops_info PASSED
tests/test_diagnostics.py::test_deploy_history_attributes_checkout_incident_to_payment_api_dependency PASSED
tests/test_diagnostics.py::test_runbook_subagent_picks_dependency_timeout_runbook_for_checkout PASSED
tests/test_diagnostics.py::test_inventory_api_shows_no_anomalies_no_false_positive PASSED
tests/test_diagnostics.py::test_parallel_fanout_is_actually_parallel_not_sequential PASSED
tests/test_diagnostics.py::test_execute_end_to_end_produces_comment_referencing_all_evidence PASSED
```

---

# Phase 3 — IAR Chat (RAG)

## Architecture

```
On-call engineer
        │
        ▼
python3 -m iar_chat.cli <incident_id>
        │
        ▼
PostgresIARChatRepo
  reads: incidents, incident_events (Phase 2's evidence), incident_chat_messages
        │
        ▼
retrieval.build_context()
  assembles incident metadata + all evidence findings into one context block
        │
        ▼
llm_chat_client.generate_chat_reply()
  read-only / advisory system prompt — never claims to execute anything
  (mock fallback if no ANTHROPIC_API_KEY)
        │
        ▼
save_chat_message() × 2  →  incident_chat_messages (Postgres)
  conversation persists across separate CLI invocations, not just in-session

     ═══ no 90-second SLA — this is the "slow path" subsystem ═══
```

## How to run

Requires Phase 1 + 2 already running (Temporal, Docker Compose, worker),
plus a triaged incident to talk about.

New migration (won't auto-apply to an existing Postgres volume — see
gotcha #2):
```bash
docker exec -i incident-auto-remediation-postgres-1 psql -U postgres -d incidents \
  < migrations/004_create_incident_chat_messages.sql
```

Get an incident_id:
```bash
docker exec -it incident-auto-remediation-postgres-1 psql -U postgres -d incidents -c \
  "SELECT id, service, status FROM incidents ORDER BY created_at DESC LIMIT 5;"
```

Then:
```bash
source venv/bin/activate
python3 -m iar_chat.cli <incident_id>
```

## What to check

**A real conversation against real evidence** (this is actual captured
output, incident `3b73beec-...`, `checkout-api`):
```
IAR chat — incident 3b73beec-3be7-4bbf-9b25-2a1fda3e7c8f (checkout-api, status=new)
Type 'exit' to quit.

you> what's going on with this service?
iar-chat> (mock reply — set ANTHROPIC_API_KEY for real chat)
You asked: "what's going on with this service?"
Based on the retrieved evidence:
Incident: 3b73beec-3be7-4bbf-9b25-2a1fda3e7c8f
Service: checkout-api
Status: new
Severity: P1
Alert count: 5
Diagnostic evidence gathered during automated triage:
- [evidence_metrics] p99_latency_ms anomalous: 120.09 -> 242.53 (+102.0%, z=19.85); error_rate_pct anomalous: 0.19 -> 0.91 (+369.1%, z=14.37)
- [evidence_logs] [ERROR] 'upstream call to payment-api timed out after Nms' x1
- [evidence_deploy_history] payment-api deployed v2.8.3 at 2026-07-25T14:01:45Z (1m ago)
- [evidence_runbook] best match: 'High latency due to downstream dependency timeout' (score=2) — ...
I'm read-only and advisory — I can't execute anything here. To take action, tag the agent on the Jira ticket with an approved command.
```

**The read-only guardrail holds even when explicitly asked to act:**
```
you> can you restart it for me?
iar-chat> (mock reply — set ANTHROPIC_API_KEY for real chat)
...
I'm read-only and advisory — I can't execute anything here. To take action, tag the agent on the Jira ticket with an approved command.
```

**Conversation persists across separate process invocations** — kill the
CLI (`Ctrl+C` or `exit`) and start a brand new one against the same
incident_id:
```bash
python3 -m iar_chat.cli 3b73beec-3be7-4bbf-9b25-2a1fda3e7c8f
```
It replays **both** prior questions and both replies before dropping you
into a fresh prompt — confirming history lives in Postgres
(`incident_chat_messages`), not in-memory, and survives across completely
separate process runs, not just within one session.

**Run the test suite** (zero external dependencies needed — pure
in-memory repo + mock LLM):
```bash
pytest tests/test_iar_chat.py -v
```
```
tests/test_iar_chat.py::test_context_includes_service_and_evidence_findings PASSED
tests/test_iar_chat.py::test_context_raises_for_missing_incident PASSED
tests/test_iar_chat.py::test_ask_returns_reply_referencing_retrieved_evidence PASSED
tests/test_iar_chat.py::test_ask_persists_both_user_and_assistant_messages PASSED
tests/test_iar_chat.py::test_multi_turn_history_accumulates_across_calls PASSED
tests/test_iar_chat.py::test_ask_raises_for_missing_incident_without_persisting_orphan_message PASSED
tests/test_iar_chat.py::test_separate_incidents_have_independent_conversation_history PASSED
```

---

# Phase 4 — Policy Gate + Command Executor

## Architecture

```
[Phase 2 workflow, extended]
        │
        ▼
propose_commands_activity
  reads the runbook evidence's suggested_commands (e.g. ["restart-pods","rollback-deploy"])
  binds each to a FULLY-SPECIFIED tool call — no placeholders left downstream
        │
        ▼
Postgres `proposed_commands`  (TTL, unconsumed)
        │
        ▼
Jira comment now includes:
  **Available actions** (tag the agent with the label to run one):
  - `restart-pods`
  - `rollback-deploy`
        │
        ▼
Human approves — simulated via CLI (no real Jira webhook in this project):
  python3 -m command_executor.approve_command <incident_id> restart-pods
        │
        ▼
policy/rules.py — evaluate_policy(tool_name)
  reversible? blast_radius? → APPROVE / DENY
  runs even AFTER human approval — a second safety check, not a rubber stamp
        │
   ┌────┴─────┐
   ▼          ▼
 DENIED     APPROVED
   │          │
   │          ▼
   │    command_executor/dispatcher.py
   │      tool_name → function, a plain dict lookup — NEVER an LLM decision
   │          │
   │          ▼
   │    MCP-style tool (modify_infra / deploy_service)
   │      real HTTP call → target_app's /chaos endpoint
   │          │
   │          ▼
   │    command_executor/verify.py
   │      re-query target_app's live /metrics, re-run anomaly_detection.py,
   │      check DIRECTION of change (not just magnitude)
   │          │
   └──────────┴──► outcome recorded in Postgres `command_executions`
                   resolved | regressed | denied_by_policy | insufficient_data
```

## How to run

Requires Phase 1 + 2 already running, plus a triaged incident with a
runbook match that produced proposed commands.

New migrations:
```bash
docker exec -i incident-auto-remediation-postgres-1 psql -U postgres -d incidents \
  < migrations/005_create_proposed_commands.sql
docker exec -i incident-auto-remediation-postgres-1 psql -U postgres -d incidents \
  < migrations/006_create_command_executions.sql
```

⚠️ Restart the Temporal worker after applying these — the workflow itself
changed to include `propose_commands_activity` (debugging log #13).

Trigger a fresh incident (same as Phase 2's demo), then approve a command:
```bash
source venv/bin/activate
python3 -m command_executor.approve_command <incident_id> restart-pods
```

## What to check

**The Jira comment should include an action menu** (Terminal 3, worker
logs):
```
Suggested next step per runbook: restart-pods, rollback-deploy
_(mock LLM output — set ANTHROPIC_API_KEY for real synthesis)_
**Available actions** (tag the agent with the label to run one):
- `restart-pods`
- `rollback-deploy`
```

**Approving and executing should show the full real chain** — this is
actual captured output from a live run, including the corrected
verification outcome (see `docs/DEBUGGING_LOG.md` #15 for the direction
bug this caught and fixed):
```
Policy check: APPROVED — 'modify_infra' is reversible with low blast radius — within auto-dispatch policy
Dispatching modify_infra({'action': 'restart', 'service': 'checkout-api', 'target_url': 'http://localhost:8080'}) ...
Action result: {'action': 'restart', 'service': 'checkout-api', 'result': {'chaos': {'latency': False, 'errors': False}}}
Waiting to verify resolution...
Verification: {'outcome': 'resolved', 'baseline_mean': 908.63, 'recent_mean': 260.83, 'pct_change': -71.3}
Outcome recorded: resolved
```
The `-71.3%` confirms this is real: `target_app`'s `/chaos` endpoint was
actually called, latency actually dropped, and the verification step
actually re-queried live data and correctly classified the improvement.

**Confirm the outcome was persisted:**
```bash
docker exec -it incident-auto-remediation-postgres-1 psql -U postgres -d incidents -c \
  "SELECT tool_name, outcome, executed_at FROM command_executions ORDER BY executed_at DESC LIMIT 5;"
```

**End-to-end proof that real diagnostic evidence proposes the right
commands** — real `checkout-api` runbook match fed through the binding
logic:
```
Runbook suggested_commands: ['restart-pods', 'rollback-deploy']

PASS: real runbook evidence -> exactly 2 correctly-bound proposed commands:
  {'command_label': 'restart-pods', 'tool_name': 'modify_infra', 'params': {'action': 'restart', 'service': 'checkout-api', 'target_url': 'http://localhost:8080'}}
  {'command_label': 'rollback-deploy', 'tool_name': 'deploy_service', 'params': {'action': 'rollback', 'service': 'checkout-api', 'target_url': 'http://localhost:8080'}}
```

**Run the test suites:**
```bash
pytest tests/test_policy.py tests/test_command_executor.py -v
```
```
tests/test_policy.py::test_modify_infra_approved PASSED
tests/test_policy.py::test_deploy_service_approved PASSED
tests/test_policy.py::test_update_database_denied_not_reversible PASSED
tests/test_policy.py::test_unknown_tool_denied PASSED
tests/test_policy.py::test_criticality_tier_accepted_but_not_currently_restrictive PASSED
tests/test_command_executor.py::test_bind_restart_pods_to_modify_infra PASSED
tests/test_command_executor.py::test_bind_rollback_deploy_to_deploy_service PASSED
tests/test_command_executor.py::test_bind_returns_none_when_no_live_target PASSED
tests/test_command_executor.py::test_bind_returns_none_for_escalate_only PASSED
tests/test_command_executor.py::test_bind_returns_none_for_unrecognized_label PASSED
tests/test_command_executor.py::test_repo_propose_then_get_active PASSED
tests/test_command_executor.py::test_repo_consumed_command_no_longer_active PASSED
tests/test_command_executor.py::test_repo_expired_command_no_longer_active PASSED
tests/test_command_executor.py::test_dispatcher_registry_has_all_three_tools PASSED
tests/test_command_executor.py::test_dispatch_raises_for_unknown_tool PASSED
tests/test_command_executor.py::test_classify_verification_healthy_series_is_resolved PASSED
tests/test_command_executor.py::test_classify_verification_spiking_series_is_regressed PASSED
tests/test_command_executor.py::test_classify_verification_recovering_series_is_resolved_not_regressed PASSED
tests/test_command_executor.py::test_classify_verification_short_series_is_insufficient_data PASSED
```

---

## Full test suite (all 4 phases, 39 tests)

```bash
pytest tests/ -v
```
All 39 tests pass: 5 (dedup) + 8 (diagnostics) + 7 (IAR chat) + 5 (policy) + 14 (command executor).

## Known gotchas (see `docs/DEBUGGING_LOG.md` for full detail on each)

1. **Postgres data persists across `docker-compose up` restarts.** If a
   dedup test shows `is_new: False` unexpectedly, it's very likely matching
   a still-open incident from a previous session, not a bug. Either
   `docker-compose down -v` or manually
   `UPDATE incidents SET status = 'resolved' WHERE status = 'new';`.
2. **New migrations don't auto-apply to an existing Postgres volume** —
   Docker only runs init scripts on a fresh volume. Apply manually via
   `psql`, or reset with `down -v`.
3. **The worker process doesn't hot-reload.** Restart it after any code
   change, including new activities (Phase 4's `propose_commands_activity`
   hit this directly — see debugging log #13).
4. **`ingestion` runs in Docker, Temporal runs on the host** —
   `host.docker.internal:7233`, not `localhost:7233`, is required for the
   ingestion container to reach Temporal. Already handled in
   `docker-compose.yml`; only relevant if you're modifying that config.
5. **The anomaly detector needs a clean baseline window.** If chaos has been
   on long enough to saturate the entire 30-sample rolling window, there's no
   contrast left to detect. `docker-compose restart target-app` gives a
   clean baseline instantly.
6. **Always activate the venv in every new terminal** — `source venv/bin/activate`.
7. **A verification outcome is about direction, not just magnitude of
   change.** A statistically large improvement and a large degradation both
   register as "anomalous" — classification logic has to check which
   direction the metric moved, not just that it moved a lot. This was a
   real bug (debugging log #15), not just a gotcha to configure around.

## Roadmap (not built)

- **Cross-incident semantic search**: IAR chat (Phase 3) currently
  retrieves only the *current* incident's evidence. Retrieving "have we
  seen this pattern before" across *past* resolved incidents would need
  embeddings + pgvector similarity search — a natural extension, not built.
- **Command execution wired into Temporal**: `approve_command.py` (Phase 4)
  is currently a standalone CLI, not a Temporal workflow/activity — a real
  deployment would want this durable too (retries, audit trail via workflow
  history). Also: a real Jira webhook trigger (currently simulated via the
  CLI, since Jira itself is mocked), and tier-based policy restrictions
  beyond the current reversibility/blast-radius check (the
  `service_criticality_tier` parameter is accepted but not yet restrictive
  — see architecture doc).
- **Confidence scoring + auto-promotion**: `command_executions` now tracks
  real outcomes (resolved/regressed/denied), which is the raw material this
  needs — but auto-promotion based on confidence scores remains deliberately
  deferred until there's enough real execution history to make the scores
  meaningful. See architecture doc, §7.

## Design rationale (short version)

The dedup/upsert step is the single most important piece of this system.
Without it, 5,000 alerts/day at steady state becomes unmanageable the moment
anything actually breaks — one bad deploy can fire 50-200 correlated alerts
in under a minute, and naive "1 alert = 1 ticket" ingestion floods the
on-call engineer's board precisely when they need signal, not noise. The
partial unique index on
`incidents(fingerprint) WHERE status NOT IN ('resolved','escalated')`
enforces this at the database level, not just in application code, so it's
race-safe under concurrent webhook delivery.

The write path (Phase 4) never lets an LLM decide *what* to execute — every
proposed command is fully bound at proposal time, dispatch is a table
lookup, and a rule-based policy gate runs even after a human has approved
something. Full rationale, including the LLM call budget derivation and why
confidence scoring was deliberately deferred, is in
[`docs/architecture.md`](docs/architecture.md).
