# Reports and Run Logs

## Report Semantics

Pass rate is PASS / (PASS + FAIL + WARNING). Execution errors did not complete
an evaluation and are excluded from that denominator along with SKIPPED and
NOT_SUPPORTED. When the denominator is zero the UI shows Not evaluated, never
100%. Check coverage is the evaluated count / emitted result count, not a
percentage of database features supported or physical database rows scanned.

Mixed passing and incomplete categories are WARNING; errors and failures take
precedence. Unsupported and skipped results have separate counts and filters.
Issues sort by ERROR, FAIL, WARNING, NOT_SUPPORTED, SKIPPED, then by severity
within each status. Their next actions are conservative guidance, not inferred
root-cause diagnoses. Each issue links to its check and, for new reports, run logs.

Views, routines, triggers, partitions, custom queries, compatibility
rules and execution checks have explicit categories. Unknown future categories
remain visible under Unclassified Checks. Every result appears once. New column
results carry producer classification; combined datatype/attribute checks remain
one result. Older reports use the legacy message-based fallback for column grouping.
Object checks are labeled metadata presence/signature checks, not definition or
behavior equivalence certification.

Sample Data validation is retired. Its category and optional sample limit remain
readable in historical reports, but new runs do not execute it or show an empty
Sample Data category. Historical reports and logs are not rewritten.

## Coverage

New reports include execution start/end times and a run manifest: stages selected,
reached, not reached, and not selected by profile; configured exclusions; schema
options; and the checksum limit. Manifest entries are not synthetic results
and do not inflate result totals. Reached means started, not necessarily passed.

Checksum checks record actual fetched rows, columns, omitted source columns,
ordering, and configured limits when available. Historical sample coverage is
preserved as recorded, not treated as full-table coverage.

Checksum reads up to cap + 1 rows to detect a limit breach. A source-cap breach
skips hashing and target fetching. A target-cap breach still exposes a mismatch
against the smaller source but is explicitly marked capped, not a full target
scan. Hash counts and checksum format are recorded. Unknown/unperformed quantities
remain null, not invented zeros. Row-count checks expose database-reported totals
separately from fetched rows. Other validators retain their existing values and
show data coverage Not recorded where not instrumented.

No shared source/target snapshot is guaranteed. Counts from separate checks must
not be added as though they measured distinct rows. Existing reports are not
rewritten: absent run/coverage/timing fields display Not recorded. Rerun validation
to capture the new metadata. JSON, HTML and CSV exports preserve the coverage;
CSV adds columns and keeps one row per emitted check.

## Persistent Logs

Every validation execution receives a run ID. JSON metadata stores run state separately
from validation outcome, allowing completed + FAIL. Events include stage starts
and finishes, check outcomes, cleanup, and terminal failures even when no report
can be saved. Validator durations describe the whole validator, not independent
per-check timings; this distinction is explicit in new results.

The Run Logs view lists runs, filters events by level/stage/text, paginates them,
and downloads a JSONL stream. Browser activity remains separate and browser-local.
The validation screen polls actual stage events, without a fabricated percentage.

| Setting | Default | Purpose |
| --- | --- | --- |
| `MV_REPORT_DIR` | `reports` | JSON report directory |
| `MV_RUN_LOG_DIR` | `reports/logs` | Per-run JSONL events and JSON metadata |
| `MV_RUN_LOG_RETENTION_DAYS` | `0` | No deletion; positive values opt into finished-run expiry |
| `MV_HOST_DATA_DIR` | Required by Compose | Absolute host directory mounted at `/data` |

No logs are deleted automatically with the default settings. When retention is
explicitly enabled, expired finished runs and their events are purged when the next run starts.
Unfinished runs are not purged automatically. A process killed without cleanup
can leave a run marked running with no recorded completion; this is not evidence
that the process is still alive. There is no job-resume or cancellation service.
The store writes `run-<id>.jsonl` and atomically replaces `run-<id>.meta.json`.
Events are flushed and fsynced; per-run OS file locks serialize local processes.
A partial final event from an interrupted write is ignored and truncated before
the next append. Malformed complete lines raise an error. Metadata and terminal
events are separate writes, so an abrupt termination between them can leave
running metadata alongside a completed event. No automatic job recovery is inferred.
The `.locks` directory contains coordination files, not log history; do not remove
it while writers are active. Atomic replacement may leave harmless temporary files
after abrupt termination. Use writable local storage with working file locks;
multi-host/network filesystem storage is not supported. A storage failure is
surfaced rather than silently claiming durable logging succeeded.

Docker Compose mounts `${MV_HOST_DATA_DIR}` at `/data` and sets report and log
directories to `/data/reports` and `/data/logs`. The Windows `docker/desktop.ps1`
launcher uses `<UserProfile>/Desktop/MigrationValidator`, not a OneDrive-redirected
Windows Desktop. An explicit `MV_HOST_DATA_DIR` or `-HostDataDir` overrides this default.
Container recreation does not remove these host files. Remote Docker engines need
a path on their own host, not the client's Desktop. Full Docker web packaging
remains outside this phase. See the [Deployment guide](../README.md#deployment).

`migration-validator migrate-storage --destination <host-data-folder>
--source-reports reports --legacy-db reports/run-logs.sqlite3` copies previous
history. Stop old writers before migration. SQLite is read-only and used only by
this explicit import command, never for new logging. Original files are retained.
An identical import is a no-op; conflicting history is rejected without overwrite.
Each run is committed separately; after interruption, rerun the command to finish.
Event IDs/timestamps, metadata and report bytes are preserved. `MV_RUN_LOG_PATH`
is no longer an active setting. Changing only `MV_REPORT_DIR` does not move logs.

## Security and API

The persisted event schema allows only identifiers, status, duration and sanitized
error codes. It does not store raw exception messages, connection configurations,
passwords, tokens, SQL text or source/target row payloads. Unrecognized error text
is replaced by DETAILS_WITHHELD; recognized Oracle/SQLSTATE codes may be retained.
Names and object identifiers are operational metadata and may still be sensitive.
Existing report payloads can contain sample values and error details; sanitized
run logs are not a redacted replacement for those reports.

- `GET /api/runs?limit=100&offset=0`
- `GET /api/runs/{id}`
- `GET /api/runs/{id}/events?level=error&stage=checksum&query=...&limit=100&offset=0`
- `GET /api/runs/{id}/download`
- `POST /api/validate?run_id=<12-32 lowercase hex characters>` optionally correlates
  a caller-generated ID. Duplicate IDs are rejected, not reused.

The existing app has no authorization boundary on report endpoints; these log
endpoints likewise require a trusted local deployment or an authenticated reverse
proxy. Do not expose the service publicly without access control. No centralized
logging platform, tenant isolation, or encryption-at-rest feature is added here.

## Verification

Run `python -m pytest -q`, `npm --prefix app/web/frontend test`, and
`npm --prefix app/web/frontend run typecheck`. Development HTTP tests use FastAPI
and httpx ASGI transport; install the updated dev dependencies. Regression tests
cover incomplete statuses, grouping, ordering, measured sample/checksum counts,
caps, retention, concurrent log isolation, failure persistence, HTTP filters,
downloads, and early-abort manifests. Browser edge cases use synthetic responses,
not live database fixtures. Live driver integration remains a separate phase.