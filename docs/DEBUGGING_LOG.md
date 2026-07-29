# Debugging Log

A chronological record of everything that actually broke while building this,
how it was diagnosed, and how it was fixed. Kept deliberately unpolished —
the point of this document is to show the real debugging process, not a
retroactively cleaned-up version of it.

Each entry: **Symptom → Root Cause → Fix → Lesson**

---

## 1. Downloaded zip produced no files

**Symptom**: after the first batch of Phase 1 files was generated, nothing
was downloadable on the user's end.

**Root cause**: files were handed off as a raw folder path rather than a
packaged file. The file-delivery mechanism shares individual files, not
directories.

**Fix**: zip the project folder into a single `.zip` before sharing it.
Adopted as the standard delivery method for every phase after this.

**Lesson**: always package multi-file deliverables into a single archive
before handoff — don't assume a folder reference is downloadable.

---

## 2. Docker daemon not running

**Symptom**:
```
unable to get image 'postgres:16': Cannot connect to the Docker daemon at
unix:///Users/amitmajumder/.docker/run/docker.sock. Is the docker daemon running?
```

**Root cause**: Docker Desktop was installed but not started.

**Fix**: `open -a Docker` on macOS, wait for it to fully start, then retry.

---

## 3. `pip: command not found`, then missing `requests` / `pytest`

**Symptom**:
```
zsh: command not found: pip
ModuleNotFoundError: No module named 'requests'
zsh: command not found: pytest
```

**Root cause**: macOS zsh only exposes `pip3` by default, and no virtual
environment was active — commands were being run against system Python or
an inactive venv.

**Fix**: created a project-scoped venv (`python3 -m venv venv`,
`source venv/bin/activate`), and made sure every terminal used for this
project activates it before running anything. This class of error recurred
several times throughout the project whenever a **new terminal tab** was
opened without re-activating the venv — see entries below.

---

## 4. `pytest` couldn't find the `shared`/`ingestion` packages

**Symptom**:
```
ModuleNotFoundError: No module named 'shared'
```
raised from inside `tests/test_dedup.py`, despite the modules existing.

**Root cause**: pytest, finding no `__init__.py` in `tests/`, inserted
`tests/` itself into `sys.path` rather than the project root — so sibling
packages (`shared/`, `ingestion/`) were invisible to the import system.

**Fix**: added `pytest.ini` with `pythonpath = .` (a built-in pytest ≥7.0
option) to explicitly add the project root to `sys.path` before test
collection.

---

## 5. Missing `pytest` in `requirements.txt`

**Symptom**: `pip install -r requirements.txt` succeeded, but `pytest` was
still not found afterward.

**Root cause**: `requirements.txt` originally listed only runtime
dependencies (`fastapi`, `uvicorn`, `pydantic`, `psycopg`, `requests`) —
`pytest` was never added as a test dependency in the first pass.

**Fix**: added `pytest==8.3.3` (later also `pytest-asyncio==0.24.0` for the
Phase 2 async test suite) to `requirements.txt`.

---

## 6. Stray literal folder `{shared,migrations}` in the delivered zip

**Symptom**: an oddly-named folder `{shared,migrations}` appeared in the
project tree on the user's machine, unrelated to anything in the codebase.

**Root cause**: an earlier `mkdir -p {shared,migrations,...}` brace-expansion
command didn't expand as intended in the build environment, creating a
literal folder named with the braces still in it, which then got swept into
a later zip.

**Fix**: `rm -rf "{shared,migrations}"`. Also tightened the build process to
verify the actual file tree (`find ... -type f | sort`) before packaging
every subsequent release, specifically to catch this class of artifact.

---

## 7. Requirements/README drift between the build environment and delivered zip

**Symptom**: fixes described as "already applied" (e.g. `pytest-asyncio`,
`anthropic` in `requirements.txt`; a Temporal setup section in the README)
were missing from files the user actually received.

**Root cause**: edits were sometimes applied directly to the packaged output
copy of the project rather than the working copy, so the next full rebuild
(copying working copy → output) silently reverted them.

**Fix**: adopted a strict single-source-of-truth workflow — all edits go to
the working copy first, then the *entire* project directory is wiped and
re-copied fresh into the output location before every zip, rather than
patching the output copy directly. Eliminated this entire class of bug for
the rest of the project.

**Lesson**: when maintaining two copies of anything (working directory vs.
delivery artifact), never let both become independently editable — pick one
source of truth and always rebuild the other from it.

---

## 8. `is_new: False` on what looked like a fresh test run

**Symptom**:
```
'is_new' True count : 0
❌ Dedup NOT collapsing correctly — investigate fingerprint logic.
```
This recurred **repeatedly** throughout Phase 2 testing, each time looking
like a regression.

**Root cause**: not a bug. Postgres data persists across `docker-compose up`
restarts via the named `pgdata` volume. Every fresh test run's alerts were
correctly matching a still-open incident (`status = 'new'`) left over from
an *earlier* test session — dedup was working exactly as designed, matching
across sessions, days, and container restarts.

**Fix**: none needed for the underlying logic. For clean demo/test runs,
either wipe the volume (`docker-compose down -v`) or manually resolve the
stale incident:
```sql
UPDATE incidents SET status = 'resolved' WHERE status = 'new';
```

**Lesson**: a monitoring/demo script's pass/fail check that assumes a clean
database is itself a source of false alarms — the underlying system was
correct every single time this fired.

---

## 9. `temporal: command not found`

**Symptom**: `temporal server start-dev` failed outright.

**Root cause**: the Temporal CLI was never installed — a genuine missing
prerequisite, not a config issue.

**Fix**: `brew install temporal` on macOS.

---

## 10. Multi-terminal confusion

**Symptom**: commands typed into a terminal that was already running a
foreground process (`docker-compose up`, the Temporal worker) either did
nothing or produced confusing errors, because the intended command was
never actually executed there.

**Root cause**: this project's local dev setup genuinely requires **4
concurrent long-running terminals** (Temporal server, worker process, Docker
Compose, and a scratch terminal for demo commands) — easy to lose track of
which terminal is doing what.

**Fix**: no code fix — just explicit, repeated clarification of which
terminal owns which long-running process, documented plainly in the README's
"Running it" sections.

---

## 11. `ingestion` container couldn't reach the Temporal dev server

**Root cause (caught before it happened, via code review, not live
debugging)**: `ingestion` runs inside Docker; `temporal server start-dev`
runs on the host machine. Plain `localhost:7233` from inside a container
resolves to the container itself, not the host — this would have failed
silently or with a confusing connection-refused error.

**Fix**: `docker-compose.yml`'s `ingestion` service was configured with
`TEMPORAL_TARGET=host.docker.internal:7233` and
`extra_hosts: ["host.docker.internal:host-gateway"]` (the latter needed for
cross-platform compatibility, not just macOS). This worked correctly on the
first real test — the one piece of Docker/Temporal networking that *didn't*
need a live debugging round.

---

## 12. Migrations didn't apply to an existing Postgres volume

**Symptom**:
```
psycopg.errors.UndefinedTable: relation "service_registry" does not exist
```

**Root cause**: Docker's Postgres image only runs `/docker-entrypoint-initdb.d`
scripts (our migration files) on a **freshly created** volume. Since the
`pgdata` volume already existed from earlier testing, the two new migration
files added in Phase 2 slice 2 (`service_registry`, `incident_events`) were
never applied.

**Fix**: applied manually —
```bash
docker exec -i <container> psql -U postgres -d incidents < migrations/002_....sql
docker exec -i <container> psql -U postgres -d incidents < migrations/003_....sql
```
(or `docker-compose down -v` to force a fresh volume, at the cost of losing
existing test data).

---

## 13. Worker kept running old code after files were updated

**Symptom**:
```
temporalio.exceptions.ApplicationError: NotFoundError: Activity function
store_evidence for workflow ... is not registered on this worker, available
activities: generate_and_post_comment, resolve_infra_metadata, run_diagnostics_activity
```
Also, more subtly: the "live" metrics evidence showed the *exact same*
numbers as the old fixture-based test run (`121.8 -> 895.17`, down to the
z-score) — a near-impossible coincidence for data meant to be randomly
generated live.

**Root cause**: the Temporal worker process was started *before* the new
code (including the new `store_evidence` activity and the live-query logic
in the subagents) was unzipped into the project directory. Python processes
don't hot-reload source files — the worker had the old module versions
loaded in memory, and simply overwriting files on disk did nothing until it
was restarted.

**Fix**: `Ctrl+C` the worker process, restart it (`python3 -m orchestrator.worker`).

**Lesson**: the exact-match-to-old-fixture-data observation was actually the
faster diagnostic signal here — a "coincidence" that specific should always
be treated as a stale-state bug, not investigated as new logic.

---

## 14. Anomaly detector reported "no anomalies" during a live chaos injection

**Symptom**: with chaos genuinely on and the live target service genuinely
returning elevated latency, the metrics subagent still reported
`no anomalies detected in queried metrics`.

**Root cause**: not a bug in the detection logic — a property of the
30-sample rolling window combined with how long chaos had already been
toggled on. The detector compares a "baseline" sub-window against a "recent"
sub-window; if chaos has been active long enough that *both* sub-windows are
already saturated with elevated values, there's no contrast left to detect.
The window doesn't distinguish "chronically bad" from "recently changed."

**Fix**: restarted the `target-app` container (`docker-compose restart
target-app`), which resets its in-memory sample deque and immediately
reseeds 15 healthy baseline ticks on startup, guaranteeing a clean
baseline-then-chaos contrast for the next test.

**Lesson**: a z-score/windowed anomaly detector is answering "did this
just change," not "is this currently bad" — worth being explicit about
which question a detector is actually answering, since the two silently
diverge once the "abnormal" state persists longer than the window itself.

---

---

## 15. Verification classified a successful remediation as "regressed"

**Symptom**: after approving and dispatching `restart-pods` against a genuinely
chaos-degraded `checkout-api`, the action clearly worked — the live run showed:
```
Action result: {'result': {'chaos': {'latency': False, 'errors': False}}}
Verification: {'outcome': 'regressed', 'baseline_mean': 895.19, 'recent_mean': 250.02, 'pct_change': -72.1}
```
Latency dropped 72% (895ms → 250ms) — a clear success — but the system
labeled the outcome `"regressed"`.

**Root cause**: a genuine logic bug, not an environment issue (the first one
in this log that is). `classify_verification()` mapped `detect_anomaly()`'s
`is_anomalous` flag straight to `"regressed"`, without checking *direction*.
`detect_anomaly()` only measures the *magnitude* of a z-score deviation — a
large statistical anomaly caused by a sharp *improvement* (latency dropping
after a fix) triggers the exact same `is_anomalous=True` flag as a sharp
*degradation* would. The classification logic needed its own direction
check on top of the existing anomaly flag, and didn't have one.

**Fix**: added a `recent_mean < baseline_mean` check — an anomalous change
now only classifies as `"regressed"` if the metric got *worse*; an
anomalous *improvement* correctly classifies as `"resolved"`.

**How it was caught**: not by the test suite — the original tests only
covered "stays healthy" (resolved) and "healthy degrades to chaos"
(regressed), never "chaos improves back to healthy," which is exactly the
shape every real successful remediation produces. The bug only surfaced
because a live end-to-end run happened to exercise the one case the test
suite didn't. A regression test for this exact scenario
(`test_classify_verification_recovering_series_is_resolved_not_regressed`)
was added afterward.

**Lesson**: for any before/after comparison built on a magnitude-only
anomaly detector, explicitly enumerate and test both directions of change
(worse *and* better), not just "changed vs. unchanged." The most important
test case for a remediation-verification system — "did the fix actually
work?" — is precisely the one that's easiest to omit if you're only
thinking about detecting *problems*, not confirming *fixes*.

## Summary: categories of bugs encountered

| Category | Count | Representative example |
|---|---|---|
| Local environment/tooling setup | 4 | venv not activated, pip vs pip3, Temporal CLI missing |
| Delivery/packaging process | 2 | folder-not-zip, stray brace-expansion artifact |
| Build-environment drift (my error) | 1 | requirements.txt fixes not reaching delivered zip |
| Not-actually-a-bug (correct behavior misread as failure) | 2 | dedup persistence across sessions, appeared twice |
| Docker/container networking & migrations | 2 | host.docker.internal, migrations-on-existing-volume (recurred for each new migration added) |
| Stale runtime state | 1 | worker running old code after file updates |
| Genuine application-logic bugs/subtleties | 2 | anomaly window saturation; verification direction bug |

Fourteen of these fifteen entries were environment, state, delivery, or
process-lifecycle related — not core algorithm logic. **Entry #15 is the
exception**: a real bug in the verification classification logic, caught
only because a live end-to-end run happened to exercise the one case
(successful remediation) that the original test suite didn't cover. Worth
being honest about that distinction rather than lumping it in with the
rest — everything else on this list would have been caught by careful
setup; #15 needed the actual system to run against real, messy data before
it was visible at all. That distinction is itself a useful signal about
what kind of project this is: mostly environment and process-lifecycle
friction, with exactly one genuine algorithm bug, found the way most real
bugs actually get found — by running the thing against real data, not by
staring at the code.
