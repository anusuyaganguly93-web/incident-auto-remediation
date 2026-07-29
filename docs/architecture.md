# Architecture & Design Rationale

This document captures the *why* behind the system — the design decisions made
before any code was written, and the constraints they were made against. For
*how to run it*, see [README.md](../README.md). For a chronological account of
what broke during implementation and how it was fixed, see
[DEBUGGING_LOG.md](DEBUGGING_LOG.md).

## The problem, framed

An incident auto-remediation system, similar in spirit to incident.io: ingest
alerts, triage them, and optionally act — at 5,000 alerts/day steady state,
with a **90-second p99 time-to-first-action**, in a single region.

The dominant engineering challenge isn't the AI reasoning — it's that the
system is **coordination-heavy, real-time, and correctness-critical**
simultaneously. Getting any one of those right in isolation is easy. Getting
all three at once is what makes this a systems design problem, not a prompt
engineering problem.

## 1. Augment or replace?

This isn't a one-time decision — it's a **tiered autonomy ladder**:

- **Tier 0 (augment)**: triage, gather evidence, propose a fix, human approves.
  This is where every alert type starts, and where this project currently sits
  in full — see "What's deferred" below.
- **Tier 1 (auto-act on allowlist)**: reversible, low-blast-radius actions only
  (restart a pod, scale out, clear a cache). Promotion is earned per alert
  signature based on real execution history, not designed in from day one.
- **Tier 2 (fully autonomous)**: earned after a long track record at Tier 1.

The guiding principle: a false-positive auto-fix that causes an outage is
strictly worse than a missed auto-fix that pages a human. **Correctness under
uncertainty, not coverage, is the metric that matters.**

## 2. Deduplication is the load-bearing design decision

5,000 alerts/day is *not* 5,000 incidents. A single bad deploy can fire
50-200 correlated alerts within a minute. Naive "1 alert = 1 ticket" ingestion
would flood the on-call engineer's board precisely when they most need signal,
not noise.

**Fix**: alerts are fingerprinted on `(service, alert_type, env)`. A Postgres
partial unique index —
`UNIQUE(fingerprint) WHERE status NOT IN ('resolved','escalated')` — enforces
"at most one open incident per fingerprint" at the database level, not just in
application code, so it's race-safe under concurrent webhook delivery.

Ticket creation is explicitly gated on this: **only a genuinely new
fingerprint creates a Jira ticket.** This was a deliberate choice over letting
PagerDuty's native auto-ticketing integration create tickets directly — that
path fires before any dedup logic runs, so it would produce one ticket per
alert regardless of how good the dedup logic downstream is. PagerDuty/ZenDuty's
native ticket-creation integrations must be disabled for this reason.

Verified: 50 correlated alerts → 1 incident, 1 ticket, `alert_count` correctly
tracked. See README for the actual captured output.

## 3. The LLM call budget is derived from measured latency, not guessed

- Per-call latency: **20 seconds, measured** (not a planning estimate — see
  the conversation history where this was explicitly locked as ground truth
  over a faster theoretical estimate).
- Time budget: 90s p99, minus ~5-10s reserved for ingestion/dedup overhead,
  leaves ~80s for triage compute.
- 80s ÷ 20s/call = **4 sequential rounds**. Running 5 calls in parallel per
  round gives a **20-call total budget**.

This produces a hard architectural constraint, not a soft guideline: **the
diagnostic subagents (metrics, logs, deploy_history, runbook) must fan out in
parallel via `asyncio.gather`, or the 90s SLA is mathematically unreachable.**
If they ran sequentially, the four of them alone would burn most of the
budget before even reaching decision-making or comment synthesis.

In practice, the implemented path uses far fewer than 20 calls — one
embedding-class call for runbook similarity search, one generation call for
the final comment. That headroom is intentionally reserved for retry loops
and more complex evidence-gathering on ambiguous incidents later, not spent
by default.

## 4. Read-only diagnostic executor vs. write-capable command executor

This is the single most important safety property in the design: **the
process that gathers evidence and the process that can change production
infrastructure are architecturally separate**, with different credentials,
different trigger mechanisms, and no shared code path.

- **Diagnostic executor** (implemented): queries metrics, logs, deploy
  history, runbooks. Read-only. Runs automatically on every new incident.
- **Command executor** (not yet implemented — Phase 4): would only ever fire
  on an explicit human trigger, via **deterministic dispatch, not LLM
  interpretation** — see the "Option B" decision below.

## 5. Where evidence goes: Jira gets the summary, Postgres gets everything

Only the LLM-synthesized comment goes to Jira — short, human-readable,
scannable in 10 seconds by a tired on-call engineer. All raw evidence
(anomaly scores, log clusters, deploy timestamps, runbook match details)
is persisted to Postgres (`incident_events`), keyed by incident, referenced
by pointer rather than dumped into the ticket. This keeps Jira tickets
readable at scale and gives Phase 3 (IAR chat / RAG) something structured
to query against.

## 6. Deterministic command dispatch (Option B), not LLM-mediated actions

When a human approves a remediation action (Phase 4, not yet built), the
design explicitly rejects free-text intent parsing by an LLM in the write
path. Instead: IAR chat proposes a **fixed menu of pre-parameterized
commands** during triage; the human tags one specific pre-built option; the
tag maps to an exact MCP tool call via table lookup, not inference.

This was chosen deliberately over the more "flexible" alternative (LLM
parses free-text intent into a tool call) because it keeps the LLM's role in
the write path at **zero**. The distinction that mattered in the design
conversation: *"an AI decided to run `update_database`"* vs. *"a human
clicked a specific, already-fully-specified button."* For a system that
touches production infrastructure and databases, that distinction is worth
the loss of flexibility.

## 7. Confidence scoring — deferred to Phase 2+, deliberately

The system tracks command execution outcomes from day one (schema exists,
even before command execution itself is built), but **auto-promotion based
on confidence scores is explicitly out of scope** until there's enough real
execution history to make the scores meaningful. Faking that data for a
demo would undercut the credibility of the rest of the design — the project
is honest about the difference between "the system could compute a
confidence score" and "the system should be trusted to act on one."

## 8. IAR chat: same repo-abstraction pattern, deliberately narrow scope for slice 1

IAR chat is the "slow path" subsystem named early in the design conversation
— no 90-second SLA, conversational, multi-turn, helping an on-call engineer
who's already looking at the triage comment ask follow-up questions.

Two decisions worth calling out:

- **Repo abstraction, not a direct Postgres dependency.** `IARChatRepo` is an
  abstract interface (`get_incident`, `get_evidence`, `get_chat_history`,
  `save_chat_message`) with a real Postgres implementation and an in-memory
  fake — the same pattern used for `IncidentRepo` in Phase 1. This is what
  made it possible to verify the entire conversational logic (context
  building, multi-turn history, the missing-incident edge case) in a sandbox
  with zero external dependencies, before ever touching a live database.
- **Retrieval, deliberately kept simple for this slice.** A single incident's
  evidence is 4 rows — small enough that "retrieval" here is closer to
  structured context assembly than a true vector-search RAG pipeline.
  Cross-incident semantic search (matching a new incident's symptoms against
  *past resolved* incidents via embeddings) is the natural next extension,
  but wasn't built in slice 1 — it would need its own retrieval
  infrastructure (pgvector, an embedding pipeline) that a single-incident
  context block doesn't.

The system prompt keeps IAR chat's role in the write path at exactly zero,
consistent with the Option B decision in §6: it's explicitly instructed to
never claim it can execute anything, and to redirect any action request
toward the (not-yet-built) Phase 4 command-dispatch flow.

## 9. Phase 4: closing the loop from diagnosis to actual remediation

This is the piece that makes the system genuinely "auto-remediation" rather
than "auto-diagnosis with a chat window." Three design decisions carried
straight through from the original planning conversation:

- **Proposals are generated automatically, execution is not.** After
  diagnostics complete, the workflow reads the matched runbook's
  `suggested_commands` and binds each one to a fully-specified tool call
  (`orchestrator/command_binding.py`) — no placeholders left for anything
  downstream to fill in or infer. These proposals are persisted with a TTL,
  surfaced in the Jira comment as a menu, and then the workflow stops. It
  never executes anything itself.
- **The policy gate is a second check, not a substitute for human approval.**
  `policy/rules.py` evaluates reversibility × blast-radius on every
  dispatch attempt — even ones a human has already explicitly approved. A
  tired on-call engineer tagging the wrong command at 3am shouldn't be the
  only thing standing between an incident and an irreversible action. This
  is why `update_database` is denied outright regardless of who asks: it's
  marked non-reversible with high blast radius, full stop.
- **Dispatch is a table lookup, never an LLM decision.** `command_executor/dispatcher.py`
  maps `tool_name` to a function via a plain dict. There is no point in this
  pipeline, from proposal through to execution, where an LLM decides *which*
  action to take or *what parameters* to pass — that was all fixed at
  proposal time. This is Option B from the original design conversation,
  implemented literally: "a human clicked a specific, already-fully-specified
  button," never "an AI decided to run `update_database`."

**Verification reuses, rather than reimplements, detection logic.**
`command_executor/verify.py` calls the exact same `anomaly_detection.py`
script used during triage to check whether an action actually worked — re-querying
live metrics after a short wait and checking if the anomaly cleared. No
separate "did this work" logic needed to be invented; the system already
had a proven way to answer "is this metric currently anomalous."

**What's simulated vs. real for this toy system**: the two implemented MCP-style
tools (`modify_infra`, `deploy_service`) both work by calling `target_app`'s
`/chaos` endpoint to clear induced chaos — standing in for what a real pod
restart or deploy rollback would actually achieve on the metrics it exposes.
This is a deliberate simplification of the *backing action*, not of the
*safety architecture* around it — the policy gate, deterministic dispatch,
and verification loop are all doing exactly what they'd do against real
infrastructure.

## What's built vs. what's deferred

| Component | Status |
|---|---|
| Webhook ingestion, normalization, fingerprinting | ✅ Built & verified |
| Dedup/upsert, conditional Jira ticketing | ✅ Built & verified |
| Diagnostic subagents (metrics/logs/deploy_history/runbook) | ✅ Built & verified |
| Parallel fan-out (latency-budget-critical) | ✅ Built & verified |
| Cross-service dependency attribution (one-hop walk) | ✅ Built & verified |
| LLM comment synthesis (mock + real Claude API) | ✅ Built & verified |
| Temporal durable orchestration | ✅ Built & verified |
| Live toy target service (chaos injection) | ✅ Built & verified |
| Postgres-backed service registry | ✅ Built & verified |
| Evidence persistence (`incident_events`) | ✅ Built & verified |
| IAR chat / RAG (single-incident context + conversation memory) | ✅ Built & verified (including live Postgres path) |
| Policy gate (reversibility × blast-radius) | ✅ Built & verified (pure logic) |
| Deterministic command dispatch + MCP-style tools | ✅ Built (logic verified; live target_app dispatch not) |
| Verification loop (post-action, reusing anomaly_detection.py) | ✅ Built (classification logic verified; live path not) |
| Command execution wired into Temporal (currently standalone CLI) | ⬜ Not built |
| Cross-incident semantic search (embeddings + pgvector) | ⬜ Not built |
| Confidence scoring + auto-promotion | ⬜ Deliberately deferred |

## Known simplifications (not bugs — documented tradeoffs)

- `generate_and_post_comment` and `store_evidence` activities make
  blocking/sync calls (`anthropic` SDK, `requests`, `psycopg`) inside `async
  def` Temporal activities, which blocks the worker's event loop for the
  call's duration. Acceptable for this portfolio-scale single-worker
  deployment; production would use async clients or a dedicated activity
  executor.
- `orchestrator/temporal_client.py` opens a fresh Temporal connection on
  every workflow start rather than reusing a shared client. Fine at this
  scale, wasteful at production scale.
- Deploy history and runbook matching remain fixture-backed even after the
  live target service was introduced — a fake CI/CD pipeline or a keyword
  scorer standing in for embedding search wouldn't add real signal for a
  portfolio demo, so effort went into the pieces that would (live metrics/logs).
- `command_executor/approve_command.py` is a standalone CLI, not a Temporal
  workflow/activity — command approval and execution aren't durable the way
  diagnosis is. A real deployment would want retries and an audit trail via
  workflow history for this step too, same as the rest of the pipeline.
- `evaluate_policy()`'s `service_criticality_tier` parameter is accepted but
  doesn't currently restrict anything — it's there so a future rule (e.g.
  "tier-1 services need a second approver for medium blast radius") can be
  added without changing every call site, not because tier-based rules
  were implemented and then removed.
- There's no real Jira webhook triggering `approve_command.py` — since Jira
  itself is fully mocked in this project, "a human tags the agent" is
  simulated by running the CLI directly with a specific incident + command
  label, rather than parsing an actual Jira comment.
