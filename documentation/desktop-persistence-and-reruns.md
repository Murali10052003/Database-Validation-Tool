# Desktop Persistence and Scoped Reruns

## Implemented Changes

| Area | Implementation |
| --- | --- |
| Desktop deployment | Multi-stage frontend/Python image; web server on port 8000; non-root runtime; read-only container filesystem with temporary `/tmp`; localhost-only published port |
| Persistent host storage | Compose binds `%LOCALAPPDATA%\MigrationValidator` to `/app/data`; `MV_HOST_DATA_DIR` overrides the host directory |
| SQLite catalog | `/app/data/catalog.sqlite3`; transactional initialization, schema version 2, automatic version-1 backup/upgrade, initialization lock, foreign keys, 30-second busy timeout |
| Connection profiles | Backend CRUD, soft deletion, metadata-only allowlist; passwords/tokens are not saved as connection fields |
| Browser migration | Explicit **Import browser connections**, original localStorage records retained; repeated import updates the same IDs |
| Inventories | Immutable versioned snapshots; indexed schema/object records containing canonical metadata, including table columns, constraints, indexes, triggers and partitions |
| Mapping versions | Immutable source/target inventory references plus schema/table/column maps, type overrides and include/exclude scope; manual versions survive rediscovery |
| Validation history | Sanitized connection configuration, execution state and JSON report in SQLite; existing report files and per-run logs also remain on the host |
| Background execution | Browser submits a job and receives a run ID immediately; one background validation at a time; progress and reports remain available after closing the page |
| Reruns | Saved-inventory selection, selected/failed-object rerun actions, full/refresh/reuse modes, editable review before execution |
| Provenance | Report coverage contains metadata mode, source/target inventory IDs and mapping version; reuse warning appears in the report UI |
| Recovery | In-progress catalog runs become `interrupted` on application startup; no automatic query resumption |
| Backups/import | SQLite online backup API, desktop backup command, non-destructive legacy report/log import with conflict rejection |

## Schema Mapping and Skipping

An unmatched target schema starts as an empty box. Enter a target schema to include
it, or leave the box empty to skip that source schema and its objects. Clearing an
existing target also skips it. Empty entries are retained when loading/saving the
mapping and submitting validation; they do not fall back to the source name.
Skipped schemas are included in the final report's excluded scope. At least one
target schema must be filled before the web UI enables validation.

Match labels describe names, not whether a mapping was previously saved:

- `exact`: source and target names are identical.
- `case insensitive`: names differ only by letter case, such as
   `MIGRATION_TEST` to `migration_test`.
- `explicit`: a mapping to a differently named target schema.
- `unmatched`: blank target or no discovered target matching the entered name.

Ambiguous automatic matches are left blank for user selection. A saved manual
target is preserved; if that target is no longer discovered it is marked unmatched.
CLI configurations with no schema mapping keep their existing same-name behavior;
an explicitly blank schema entry means skip.

## Saving Progress When Validation Stops

### What Changed

The application now saves each completed check result in SQLite while validation
is running. Previously, results waited in memory until the whole run finished.
It also records which validation stages are pending, running, finished, in error,
or interrupted. The normal final report is still created when the run finishes.

This is the first stage of interruption handling: **keep completed results**.
Background execution is now also implemented as described below. Automatic resume,
automatic retries, user-requested query cancellation, and row-by-row checkpoints
are not implemented.

### A Simple Example

You select row-count checks for three tables: CUSTOMERS, ORDERS, and PAYMENTS.

1. CUSTOMERS finishes. Its result is saved immediately.
2. ORDERS finishes. Its result is saved immediately.
3. The application stops while checking PAYMENTS.
4. Start the application again using the same data directory.
5. Open **Logs > Run logs**, select the run, and look at **Saved check results**.

The first two results remain available. PAYMENTS has no finished result and must
be checked again. The run is shown as interrupted, not as a successful validation.
If a query fails but the application continues, its saved result may be ERROR.
If saving a result fails, for example because the disk is full, execution stops
rather than silently continuing without durable results.

For one table containing 15 lakh rows, a row-count result is saved only after that
query finishes. Stopping halfway through the query does not save half a row count.
The existing checksum cap is unchanged; this release does not add full large-table
streaming comparison or certify performance on million-row databases.

### How to View and Recover

1. Open **Logs > Run logs** and select the run.
2. Read **Saved check results** for saved PASS, FAIL, ERROR, or other check outcomes.
3. Expand **Check evidence** to inspect comparison values and coverage details.
4. Use **Previous checks / Next checks** for more results (100 checks per page).
5. If interrupted, fix the connection, storage, or database problem, test the
   connections again, and start a new validation for the necessary objects/checks.

Saved results refresh while the page is open. An incomplete run has an explicit
warning. Several saved PASS checks do not mean the whole migration passed. A stage
marked finished means it finished executing, not that every check passed. Pending
stages have not run. Logs and saved results are different: logs explain execution;
saved results retain completed comparison evidence.

There is no Resume button in this release. A new run does not automatically skip
previously completed tables. If the source or target data changed, earlier results
may no longer describe the current data, so revalidate the affected scope. Closing
the browser is not a reliable way to cancel a running database query.

### Storage and Upgrade

Results are stored in `run_results` and stage states in `run_stages` inside the
existing catalog. Writing the same check identity again updates that saved result
instead of adding a duplicate. These records are not a retry-attempt history.
Full result evidence can contain sensitive database values; protect the data folder
and backups. Connection passwords and authentication tokens are not checkpointed.

On Docker, the catalog is `/app/data/catalog.sqlite3` in the existing host bind
mount. Local development uses `MV_CATALOG_PATH` or the configured default. Keep
using the same directory after restart. Committed results survive a process stop;
disk loss, deletion, or corruption still requires backups.

The first startup with this code upgrades catalog version 1 to version 2. Before
upgrading an existing version-1 database, it creates a backup under
`backups/catalog-v1-<unique-id>.sqlite3`. The upgrade adds tables without deleting
saved connections, inventories, mappings, or reports. Older runs are not backfilled
with incremental results; their existing final reports remain available.

Stop all other instances before upgrading and keep a full data-directory backup.
**The older Docker image cannot read a version-2 catalog.** Do not point it at a
catalog upgraded by local development. To return to the older application, stop
all writers and restore a compatible backup into a separate directory; newer
results will not be present in that older backup. This change does not rebuild or
replace the previously exported Docker image.

### What Was Tested

Automated tests cover result persistence and deduplication, version-1 backup and
upgrade, partial-results API pagination, storage-write failures, and a subprocess
that exits abruptly during its third table. The first two committed results must
survive reopening; the third is absent and the run/stage becomes interrupted on
recovery. These use synthetic data, not live Oracle/PostgreSQL interruption tests.

The API is `GET /api/runs/{run_id}/results?limit=100&offset=0`. It returns saved
checks, counts, stage states, and an explicit completion indicator, not an overall
PASS for partial work. Results remain accessible independently of log retention.

## Background Validation in Simple Terms

### What It Does

Click **Start validation** as usual. The backend records the job and returns a run
ID without waiting for all checks to finish. A worker inside the backend process
then runs the validation. The page checks progress periodically; it no longer keeps
one HTTP request open for the full validation.

You can close the results dialog, leave the page, or close the browser after the
job has been accepted. The backend keeps working. Reopen the app, open **Logs >
Run logs**, and select the run to see its state and **Saved check results**. When
execution finishes, **Open report** opens its final report. A finished execution
can still have validation FAIL, WARNING, or ERROR results.

Only one background job is accepted at a time. A second submission is rejected;
it is not silently queued for later. The accepted job briefly has state `queued`
before changing to `running`. If the submission response is lost, check run history
before retrying: the job might already have been accepted. A temporary progress
connection failure does not mean validation failed.

### What Happens When Something Stops

| Action | Result |
| --- | --- |
| Close or refresh the browser | Accepted background validation continues |
| Lose the browser's connection to the app | Backend work can continue; reconnect to view progress |
| Lose the backend's database connection | Existing validator error handling applies; no automatic retry is added |
| Stop the backend or Docker container | Work is interrupted; completed checks remain in the persistent data directory |
| Start the backend again | Unfinished queued/running jobs become interrupted; they are not restarted |

Stopping the container does not delete the Docker image. Restarting it does not
resume an unfinished job. Enter credentials or sign in again and submit a new run.
Background execution does not change the checksum limit or add sampling, grouping,
row-range resume, skipped-table reuse, or automatic retries.

Passwords and browser tokens are held in backend memory for the accepted job, not
in the SQLite job record. References on the job configuration are cleared when
execution ends. Browser tokens are not automatically refreshed by a closed browser;
if a later database connection cannot authenticate, the existing error handling
applies. This is not a credential vault or a durable job queue.

### Implementation and Operation

The UI uses `POST /api/validations?run_id=<unique-hex-id>`, which returns HTTP 202
with `run_id` and `status_url`. It polls `GET /api/runs/{run_id}` for execution state
and the existing events/results APIs for progress. The original synchronous
`POST /api/validate` and CLI remain available for compatibility; they do not use
the background admission slot. Do not run those concurrently with background jobs
when a strict single-validation workload is required.

The worker is a dedicated daemon thread with its own event loop, including the
Windows selector loop required by the PostgreSQL driver. No Redis, external worker
service, or additional database is required. The catalog stays at version 2.

Run one web-server process per catalog, with FastAPI lifespan enabled. Startup
holds a catalog-specific `.worker.lock`; another current-version backend using
that catalog fails startup rather than marking active jobs interrupted. Do not use
multiple Uvicorn workers or share this data directory with an older app/CLI writer.
Use a separate data directory for another instance. Development `--reload` restarts
the backend when code changes and therefore interrupts active jobs.

On orderly shutdown, the app stops accepting jobs, requests task cancellation,
and gives the worker up to five seconds to exit. Some blocking driver calls may not
respond immediately; this is not a guarantee of server-side SQL cancellation. An
abrupt stop is recovered from the committed catalog on the next startup.

Automated tests use synthetic validators to verify HTTP 202 before completion,
completion after the submitting client closes, report retrieval by a new client,
saved progress, duplicate/concurrent rejection, credential cleanup, shutdown,
queued-run recovery, and exclusive backend ownership. Live database interruption
testing is still required for driver-specific behavior. The existing Docker image
and export are unchanged; rebuild separately to distribute this feature.

## Windows Startup

Use Docker Desktop with Linux containers and Docker Compose v2 supporting `up --wait`.
Building needs access to the Microsoft package mirrors and Docker Hub. Run from the repository root:

```powershell
.\docker\desktop.ps1
```

Open `http://localhost:8000`. When port 8000 is occupied:

```powershell
.\docker\desktop.ps1 -Port 8001
```

The launcher creates the host directory before startup. On first application startup,
SQLite creates the database and tables. No catalog, reports, credentials or customer
configuration is seeded from the image. The image includes application source, built
UI assets, dependencies and bundled datatype mappings only.

Compose can also be used directly on Windows; it resolves `LOCALAPPDATA` automatically:

```powershell
docker compose -p migration-validator-desktop -f docker/docker-compose.yml up -d --build --wait
```

For a custom location, use `-HostDataDir 'D:\MigrationValidator'` consistently for all
launcher actions. Alternatively set `MV_HOST_DATA_DIR` persistently in your environment.
Changing the directory selects a different catalog; it does not move the old one.
Do not run two application instances against the same directory. Use a local Docker
context: a remote daemon cannot mount your Windows application-data directory.

On Linux, set `MV_HOST_DATA_DIR` and grant the container UID 10001 write access to that
directory. Never use a network share or a synchronized folder for an active SQLite store.

## Build Package Sources

The Dockerfile defaults to the Microsoft Central Feed Services consumption proxies:

| Build argument | Default |
| --- | --- |
| `NPM_REGISTRY` | `https://packagefeedproxy.microsoft.io/npm/` |
| `PIP_INDEX_URL` | `https://packagefeedproxy.microsoft.io/pypi/simple/` |

Windows pip/npm configuration is not automatically inherited by Docker builds. The
frontend stage explicitly supplies its registry to `npm ci`; the Python stage supplies
the index to pip through a build argument, including isolated package build dependencies.
The application is installed with its `web` and `entra` extras so FastAPI, Uvicorn,
and optional CLI Entra credential support are present.
Node and Python base images still come from Docker Hub, not these package mirrors.

```powershell
docker build -f docker/Dockerfile -t migration-validator:local .
```

Other environments can override these arguments with their approved feed URLs using
`--build-arg`. Do not put passwords or tokens in build arguments; authenticated feeds
require a separate BuildKit secret configuration. TLS verification remains enabled.
The npm lockfile contains resolved Microsoft feed artifact URLs, so a registry override
alone is not a guarantee that all locked artifacts move to a different provider.

The tested image is `linux/arm64`, matching this Windows ARM64 Docker Desktop host.
Distribution to Intel/AMD machines requires a separately built and tested `linux/amd64`
image, or a tested multi-platform image. The build command above targets the local platform.

## Browser Entra Sign-In and Independent Connection Tests

The connection forms have separate **Test source connection** and **Test target
connection** buttons. Either can be tested with the other form incomplete. Editing
one form clears only that side's test result and invalidates the discovery plan.
Both tests must pass before continuing to discovery.

For Azure PostgreSQL with Microsoft Entra Browser sign-in, Test connection opens an
MSAL Browser account-selection popup on the user's computer. The Docker container
does not launch a browser or inherit the host's Azure CLI credentials. Browser
requests in Browser sign-in mode use the selected user's PostgreSQL access token; they do not fall back to
`DefaultAzureCredential`. CLI/YAML use retains the existing default credential chain.
Browser Entra support for Azure SQL and SQL Server is not implemented.

### Local Developer Testing Without an App Registration

For testing on Windows, run the backend directly on Windows and select **Microsoft
Entra ID**, then **Entra credential source > Local developer credentials**. This
explicit mode uses the existing `DefaultAzureCredential` helper for connection tests,
discovery, and validation. It does not invoke MSAL, require a Migration Validator app
registration, or open an account-selection popup. An existing supported credential
source (such as a signed-in Azure CLI) must be available to the backend process.
Windows sign-in alone does not guarantee a usable credential. The credential's
identity must have PostgreSQL permissions in the correct database tenant; entering
a database username does not choose the credential-chain account.

Enable the mode only for your trusted, loopback-bound development backend:

```powershell
$env:MV_ALLOW_LOCAL_ENTRA = 'true'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The local interpreter requires the project's `entra` extra (`azure-identity`). Use
the current frontend source with Vite or rebuild the frontend assets locally before
opening the backend's UI. This is not a Docker image build.

The backend rejects local mode unless the flag is explicitly enabled. Browser mode
never falls back to local credentials, even with the flag enabled. Local mode is a
temporary form selection and is not stored with profiles: loaded profiles default
back to browser sign-in. Both independent connection-test buttons remain available;
changing credential source invalidates that side's test and the discovery plan.

Docker cannot use the Windows host's credentials automatically. Do not enable this
setting in a shared or publicly reachable service, mount credential caches, or expose
a token-forwarding endpoint to work around that boundary. No image rebuild is needed
for local source-code testing. Existing Docker containers remain on their prior code.

### Enter Registration Details in the Website

For either Azure PostgreSQL connection, select **Microsoft Entra ID**, then
**Entra credential source > Browser sign-in**. Enter the IDs from your Entra app
registration's Overview page directly in the form:

- **Application (client) ID**: the application registration's client ID.
- **Directory (tenant) ID**: the database resource tenant where the application
   can sign in, including the resource tenant for guest access.
- **SPA redirect URI**: a read-only value reflecting the current website origin
   and callback path. Register this exact value as a Single-page application URI.

Then click **Test source connection** or **Test target connection** and select
your Microsoft account. No client secret is requested. Entered IDs must be UUIDs.
Source and target can use different client/tenant pairs; silent token acquisition
for discovery and validation uses each connection's own registration and account.
Editing the form clears that side's test and account association and invalidates
the discovery plan. Local developer mode hides these fields and does not use them.

These IDs are held in the current form session, not saved with connection profiles
or run history. Re-enter them after loading a profile or reloading the page. Tokens
remain in memory only. No server restart or Docker rebuild is needed to change IDs
in the website once this version is deployed.

Configure one publisher-owned application registration (or a customer-provided
registration), not one registration per database. Enable the intended organizational
account audience and the Azure OSSRDBMS Database delegated `user_impersonation`
permission, obtaining consent where required. Use the target database's tenant ID,
including when the signed-in user is a guest. Customers in another tenant may
require admin consent or a registration with the appropriate account audience.

Register the exact **Single-page application** redirect URI matching the URL users
open. For a production Docker app at `http://localhost:8000`, use:

```text
http://localhost:8000/static/auth-callback.html
```

The port, hostname (`localhost` versus `127.0.0.1`), and path must match the deployed
origin and registered URI. Prefer `localhost` for the local HTTP registration.
Use HTTPS for anything beyond loopback. For Vite development the callback path is
`/auth-callback.html` on the Vite origin. No client secret is used or distributed.

As an optional deployment default, set public IDs before starting/recreating
Compose, using your existing project, port and data directory settings:

```powershell
$env:MV_ENTRA_CLIENT_ID = '<application-client-id>'
$env:MV_ENTRA_TENANT_ID = '<database-tenant-id>'
```

Compose passes these defaults to `/api/auth/config`. Both form fields left empty
use the deployment default; otherwise both entered IDs are required and override
it together. Invalid or partial entries never fall back to the deployment default.
If neither a complete form pair nor a deployment default exists, Test connection
requests the IDs. Environment defaults require an application/container restart
and page reload after changes; user-entered IDs do not. Allow Microsoft sign-in popups.
The selected account is displayed separately from the database username: keep the
exact PostgreSQL role name, which can differ for group access or guest accounts.
Sign-in does not grant database permissions or fix firewall/VPN/DNS problems.

MSAL caches tokens only in browser memory. Tokens are sent in POST bodies only for
database tests, discovery and validation, never placed in the form state or saved
profiles. Backend token fields are secret-wrapped and excluded from model serialization;
validation errors omit request inputs. Browser driver-connect errors are sanitized.
The existing API is single-user/local-only, not a shared authenticated web service.
Keep the localhost bind, do not enable permissive CORS, and do not log request bodies.

Discovery and validation silently acquire fresh tokens for the selected account.
When interaction is required, test that side again. An in-flight validation uses its
request token; it cannot silently renew from the backend if it needs a new database
connection after token expiry. Restart that operation after signing in again.
Disconnect account removes the application's connection/account association; it
does not sign the user out of Microsoft globally or cancel an already-running task.
Reloading the page clears application token memory and requires testing again.

For Oracle hosted on the same Windows computer, use `host.docker.internal` instead
of `localhost` inside the connection form. An Oracle container must publish its port
to the host, or share a Docker network where its service name is reachable.

Reference: [Microsoft authorization code flow with PKCE](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow)
and [PostgreSQL Entra authentication](https://learn.microsoft.com/en-us/azure/postgresql/security/security-entra-configure).

## Storage Layout

```text
%LOCALAPPDATA%\MigrationValidator\
  catalog.sqlite3
  catalog.sqlite3.lock
  catalog.sqlite3-journal       (when SQLite needs it)
  backups\catalog-<uuid>.sqlite3
  reports\migration-<id>.json
  logs\<run-id>.jsonl
  logs\<run-id>.meta.json
```

Mount the **directory**, not only the SQLite file, so transaction sidecars are durable.
The catalog tables are `connections`, `inventories`, `inventory_objects`, `mappings`,
`runs`, and `schema_migrations`. Object payloads are JSON rather than a separate SQL
row for every column/constraint. SQLite filters object records before deserialization;
it does not load every table payload for a single-table rerun. Case-insensitive scope
predicates may still scan the selected inventory's object index.

The catalog does not copy source business tables. Reports can contain sensitive
comparison evidence, custom-query output and database error text. Metadata can contain
sensitive SQL definitions/defaults. This is an unencrypted, single-user local store;
protect the host account, directory ACLs and backups. Do not expose the unauthenticated
API on a public interface. No RBAC, encryption-at-rest layer or credential vault is added.
Connection passwords must be entered again after loading a profile. Browser-only
appearance/preferences and activity state remain browser-local, not catalog records.

## Discovery and Rerun Workflow

1. Load or enter source and target profiles; enter credentials and test connections.
2. First use: use **Load schemas** on each side and select the source and target schemas
   (at least one each). **Discover & match** then reads only those schemas and only
   schema/table names, and saves **names-only** inventories plus a mapping version;
   columns, constraints, indexes and the other objects are collected when validation
   runs. Requests without a schema scope (older clients) keep the previous full
   discovery and save complete inventories. For an existing pair, open
   **Saved inventories and previous runs**, find inventories, select versions and load;
   names-only inventories are labelled as such.
3. Review schema/table mapping and source include/exclude scope. **Save mapping and
   scope** persists edits even when no validation is executed. Previously saved manual
   mapping payloads are restored on rediscovery, limited to the selected source schemas
   (a wider earlier mapping does not re-introduce unselected schemas); new/conflicting
   objects require review.
4. Choose checks and metadata mode, then run validation. Loaded history reruns do not
   execute automatically. Passwords are taken from the current forms, never history.

| Mode | Metadata behavior |
| --- | --- |
| `full` | Live discovery using existing schema mapping filters (or, when the mapping is empty, the saved `source_schemas`/`target_schemas` scope); object include/exclude filtering happens in validators. Used automatically after a names-only discovery and required when discovering newly introduced source objects. |
| `refresh` | Selects saved source objects and mapped targets first; refreshes table columns without enumerating all schemas/tables, plus constraints, indexes and schema-level objects only when a selected check uses them; writes new scoped snapshots. A mapped target table absent from the old snapshot is queried explicitly. Needs an inventory with full metadata. |
| `reuse` | Loads saved metadata with no live metadata refresh; connectivity and selected data checks remain live. Report warns that schema changes since discovery are not detected. Needs an inventory with full metadata. |

Structural sequence/view/routine/trigger/partition adapter methods remain schema-wide
metadata reads followed by filtering. Oracle constraint-column collection is scoped to
the table being read (plus the constraints its foreign keys reference) rather than the
whole owner. This is **not** a guarantee of one exact-object SQL query for every check.
Refresh skips constraints, indexes and schema-level objects when only checks that do not
use them (schema, row count, null count, aggregate, custom query) are selected.

Inventory IDs are checked against connection type, platform, host, port, database,
service, username, authentication method and TLS setting. Credentials are excluded
from identity. Driver-specific options are not part of this identity contract.
Names-only snapshots, and snapshots lacking complete column/structural metadata such as
some Quick full runs, cannot be reused for scoped runs: run in `full` mode, which collects
the metadata live inside the selected schemas. Refreshed snapshots
contain only the selected scope, not an implicit replacement of the original full inventory.

Scope uses source names, case-insensitively, before target mapping. Empty includes
mean all objects in the selected inventory; the UI prevents running an explicitly
empty selection. Exclusions win. Unknown includes, an empty effective scope, stale
identity or inaccessible selected tables fail instead of silently starting full discovery.
Deleted tables can yield a discovery ERROR rather than a table-comparison finding.
New source objects and new non-table target objects require full rediscovery.
Quoted identifiers containing dots and ambiguous case-folded names require particular
care: the existing name-based scope convention is not an identifier parser.

**Rerun failed objects** derives source schema/table names from FAIL/ERROR results.
It refuses to broaden to all objects if no source names can be inferred. Column failures
select their parent table. Target-only errors may need manual scope selection. Review
the generated scope; it is not a root-cause or dependency inference engine.
Referential-integrity checks honor exclusions and selected mapped tables, but may read
referenced parents. Arbitrary custom SQL is rejected for scoped reruns because object
scope cannot constrain arbitrary query text; use a separately reviewed full run.

## Restart and Upgrade

```powershell
.\docker\desktop.ps1 -Action Stop
.\docker\desktop.ps1 -Action Start
.\docker\desktop.ps1 -Action Status
.\docker\desktop.ps1 -Action Upgrade
```

Stop removes the container, not the host data. Upgrade stops the application, creates
a catalog backup with the existing image, then builds the new local image and starts
it using the same mount. Supply `-Image registry/name:version` to pull an existing image
instead of building. Before switching image references, use **Backup** while the old
image is running. Keep custom host path and port arguments consistent across actions.
If build/pull/start fails, the host data remains in place; the app may remain stopped.

Schema version 2 adds incremental check results and stage states. Startup backs up
and transactionally upgrades version 1 without dropping existing data. Unknown newer
versions and nonempty unversioned databases cause startup failure without resetting
data. Future schema changes must ship explicit transactional migrations and
preservation tests. Downgrades are not automatically supported; use a compatible
backup in a separate directory when returning to an older application version.

Container recreation is not a backup. Deleting the host directory destroys the data.
Use separate backups and monitor disk space; inventories/mapping history currently
have no automatic retention or compaction. Log retention remains disabled by default.

## Backup and Restore

```powershell
.\docker\desktop.ps1 -Action Backup
```

The UI's **Back up catalog** action and `/api/catalog/backup` use the same SQLite
online backup API. This produces a consistent catalog copy, not a combined report/log
backup. For a complete point-in-time backup, stop the app and copy the entire host
directory to a protected separate location.

To restore: stop all writers, preserve the current directory under another name,
restore the full directory (or a catalog backup as `catalog.sqlite3` into a clean
directory with matching reports/logs), then start with the same path. Never replace
a live SQLite file or mix old transaction journals with a restored database. A catalog
alone does not recreate the separate JSON report downloads or per-run log files.

## Import Existing Local Data

No automatic move from Desktop or the repository is performed. Stop old writers first:

```powershell
$data = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'MigrationValidator'
.\.venv\Scripts\python.exe -m app.cli migrate-storage --destination "$data" `
  --source-reports reports --legacy-db reports/run-logs.sqlite3
```

Use your actual old report directory. Omit `--legacy-db` when it does not exist; add
`--source-logs '<old-data>\logs'` for file-backed logs. Original files are retained,
identical copies are accepted, and conflicting files/run IDs are rejected. Supported
report JSON is indexed in the catalog. Older incompatible report files are copied
unchanged but not indexed; imported reports have no invented inventory or connection
provenance, so they cannot offer automatic inventory-backed reruns.

In the browser that holds old profiles, use **Import browser connections** on the old
origin/port after updating the app. Browser localStorage is origin-specific; another
port cannot read those profiles. Import strips credential fields and retains originals.

For non-Docker development, set `MV_CATALOG_PATH`, `MV_REPORT_DIR`, and `MV_RUN_LOG_DIR`
explicitly to the same host directory layout. Existing `.env` report/log overrides are
not silently changed. The Docker service does not load the repository's `.env` secrets.

## Verification and Remaining Limits

Offline verification: **265 backend tests passed; 204 opt-in live database tests
skipped; 20 frontend tests passed**. Ruff, TypeScript and the production frontend
build passed. Browser checks at 1440px desktop and 390px mobile verified inventory
loading, default refresh mode, the reuse warning, empty-selection blocking and no
horizontal overflow. Database responses were mocked for that UI check; no live
database validation was performed. Browser mocks were removed afterward.

Automated tests cover initialization/reopen, backups, version rejection without data
loss, credential-field exclusion, inventory identity/scope checks, API persistence,
mapping overrides, actual refreshed snapshot provenance, newly created target tables,
metadata reuse, and legacy import compatibility. Frontend tests cover metadata-only
profile import, stable IDs, retained browser copies and surfaced persistence errors.

Docker verification on 2026-09-13 passed on Windows ARM64 with Linux containers:

- Complete `migration-validator:local` build using the Microsoft npm and Python mirrors.
   This resolves the earlier build failure caused by blocked public package downloads.
- Web runtime and Oracle/PostgreSQL driver imports; `pip check` reports no broken requirements.
- Production Compose startup with `--wait`, healthy API, frontend rendering and saved-profile API.
- Container-served JavaScript/CSS returned HTTP 200; browser reload captured no page errors,
  with no horizontal overflow at 1440px desktop and 390px mobile widths.
- SQLite created in a fresh, isolated Windows LocalAppData bind mount.
- Exact preservation of the saved profile, inventories, inventory objects, mapping,
   schema migration record and finished synthetic run after Compose `down`/`up`.
- Exact preservation of those records after replacement with a separately built image
   carrying a different image label; the application and catalog schema remained unchanged.
- Recovery of an in-progress synthetic run to `interrupted` on restart.
- Online backup, backup inventory/mapping contents, catalog and backup integrity checks,
   catalog schema version 1, non-root UID 10001, read-only root and writable data bind.

These lifecycle checks used synthetic metadata and run records, not live databases.
They test same-schema image replacement through Compose, not a future schema migration
or the desktop launcher's complete Upgrade command. npm reported four dependency audit
findings during the build (three moderate, one high); dependency remediation remains
separate work. No TLS verification or organization security controls were disabled.

The default image installs Oracle and PostgreSQL drivers. MySQL and SQL Server/Azure SQL
need their additional Python/system drivers; they are not made available merely by UI
selection. Live database certification, billion-row performance, streaming checksums,
parallel execution, cross-database consistent snapshots, resumable jobs and multi-user
catalog access are outside this change. History/inventory lists currently return whole
lists; large catalogs need pagination/retention work before claiming enterprise scale.