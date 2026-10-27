# Database Migration Validation Platform

## About

A database migration comparison tool with a React web interface, HTTP API and
Python CLI. It compares source and target metadata and data, then produces
JSON, HTML and CSV reports with persistent per-run logs. It does not migrate data,
repair target databases or certify application behavior automatically.

The core validation engine contains **no** database-specific SQL. Every piece of
database-specific behaviour lives inside an adapter, so new databases are added by
writing an adapter and registering it — the engine never changes.

## Key Contributors

- **Owners**:
  - Ram Yerabotu ([ramyerrabotu@microsoft.com](mailto:ramyerrabotu@microsoft.com))
- **Reviewers**:
  - RK Iyer ([raiy@microsoft.com](mailto:raiy@microsoft.com))
- **Contributors**:
  - MuraliKrishnan N ([murn@microsoft.com](mailto:murn@microsoft.com))

## Table of Contents

- [About](#about)
- [Key Contributors](#key-contributors)
- [Capabilities and Support](#capabilities-and-support)
- [Application Features](#application-features)
- [Deployment](#deployment)
  - [Prerequisites](#prerequisites)
  - [Option 1: Run a Pre-Built Image](#option-1-run-a-pre-built-image)
  - [Option 2: Build the Image from the Dockerfile](#option-2-build-the-image-from-the-dockerfile)
  - [First Connection in Docker](#first-connection-in-docker)
  - [Persistence and Data Storage](#persistence-and-data-storage)
  - [Update to a New Version](#update-to-a-new-version)
  - [Status, Logs, and Troubleshooting](#status-logs-and-troubleshooting)
- [Local Installation Without Docker](#local-installation-without-docker)
  - [Native Installation Prerequisites](#native-installation-prerequisites)
  - [Windows Installation](#windows-installation)
  - [Linux Installation](#linux-installation)
  - [Native Startup, Connections, and Maintenance](#native-startup-connections-and-maintenance)
- [Correctness Hardening](#correctness-hardening)
- [Architecture](#architecture)
- [Microsoft Entra ID Authentication](#microsoft-entra-id-authentication)
- [Web UI](#web-ui)
- [Implementation Workflow](#implementation-workflow)
- [Extending to a New Database](#extending-to-a-new-database)
- [Documentation](#documentation)

## Capabilities and Support

Implemented capabilities are not the same as live-certified datatype support.
Oracle and PostgreSQL datatype certification targets, fixtures, unsupported cases
and execution instructions are documented in [Datatype coverage](documentation/datatype-coverage.md).
The initial test matrix targets Oracle 19c/21c and PostgreSQL 16/17; live
certification is **pending**, not implied by passing unit tests.

| Engine | Adapter identifier | Scope |
| --- | --- | --- |
| Oracle | `oracle` | Implemented adapter; Oracle-to-PostgreSQL datatype test path |
| PostgreSQL, local or managed | `azure_postgresql` | Shared PostgreSQL adapter; usable on either side through config/API |
| MySQL | `mysql` | Implemented adapter; outside the current datatype certification matrix |
| SQL Server | `sqlserver` | Implemented adapter; outside the current datatype certification matrix |
| Azure SQL | `azure_sql` | Implemented adapter; outside the current datatype certification matrix |
| Azure Database for MySQL | `azure_mysql` | MySQL adapter on Azure (TLS always on, password or Entra ID); source or target; outside the current datatype certification matrix |

The PostgreSQL adapter identifier is historical: use `azure_postgresql` with
`platform: self_managed` for a non-Azure PostgreSQL database. UI engine choices may
be narrower than the config/API adapter registry. Use the supplied YAML examples
for PostgreSQL-to-PostgreSQL datatype tests. In the UI, **MySQL** and **Azure MySQL**
are available as sources, and only **Azure MySQL** as a target (MySQL → Azure MySQL and
Azure MySQL → Azure MySQL); see `config/examples/mysql-to-azure-mysql.yaml`. "Azure SQL"
is Azure SQL Database (the SQL Server engine on Azure).

SQL Server and Azure SQL are currently hidden from the web UI database dropdowns
pending testing. Their config/API adapters remain available.

## Application Features

- Connect to Oracle, PostgreSQL, MySQL, Azure MySQL, SQL Server, and Azure SQL databases.
- Test source and target connections before starting a validation.
- Sign in to Azure PostgreSQL or Azure MySQL with Microsoft Entra ID using browser
  authentication or opt-in local developer credentials.
- Discover schemas, tables, columns, indexes, constraints, sequences, views, routines,
  triggers, and partitions.
- Automatically match source and target schemas and tables, with optional manual mapping.
- Limit validation to selected objects or exclude specific schemas, tables, and columns.
- Compare database structure, object definitions, row counts, NULL counts, numeric
  aggregates, checksums, and referential integrity.
- Detect datatype compatibility, identifier-length issues, and unsupported features.
- Run custom source and target query assertions with comparison operators and tolerances.
- Choose Quick, Standard, or Full validation profiles according to the required depth.
- Run validations in the background and inspect saved progress and per-check run logs.
- Filter validation results and download reports in JSON, HTML, or CSV format.
- Save profiles, mappings, run history, reports, and logs in persistent storage.
- Use the React web interface, HTTP API, or command-line interface.

Live connections require the matching driver extra (`oracle`, `postgresql`, `mysql`,
`sqlserver`); the SQL Server / Azure SQL adapters use the Microsoft ODBC Driver 18 via
`pyodbc`.

Oracle NULL-count scans use `COUNT(CASE WHEN column IS NOT NULL THEN 1 END)`,
which supports BLOB/CLOB NULL checks without aggregating LOB values. Row-count-only
scans still use `COUNT(*)`. When row and NULL counts are selected together, they
share a profile query; an invalid NULL-count expression can therefore report errors
for both checks. If an older build reports `ORA-22849` on a LOB table, rebuild or
update the application before rerunning the combined checks.

Checksum validation compares at most `validation.data.chunk_size` ordered rows per
table on each side (default **100**, minimum **1**). Larger tables are not skipped:
the validator hashes their first rows in primary-key order, or comparable-column
order when no primary key exists. One extra row is fetched only to detect the cap
and is not hashed. A matching capped comparison is `PASS` for the checked prefix,
with the finding "Matches within first 100-row cap; remaining rows not checked"
(using the configured cap). A mismatch is `FAIL` and also identifies capped coverage.
Matching complete tables within the cap are `PASS`.
Rows beyond the cap are not verified, so keep row-count and NULL-count checks enabled
for broader coverage. Cross-database ordering/collation differences can affect which
rows enter a prefix, especially without a shared numeric primary key.

Oracle CLOB/NCLOB and BLOB locators are read into text/bytes before query results
leave the adapter, so checksums compare contents rather than driver handles.
Read failures remain execution errors. The row cap does not limit individual LOB
sizes: large values, including the lookahead row, can consume substantial memory.

## Deployment

The Migration Validator ships as a single-user, localhost-only Docker desktop
application. Alternatively, install directly on Windows or Linux using
[Local Installation Without Docker](#local-installation-without-docker).
There are two Docker deployment options:

1. **Run a pre-built image** — two architecture-specific images are already built and
   included under `Images/`. Load the archive that matches your CPU and start it.
2. **Build the image from the Dockerfile** — compile the current source into a fresh
   image, then run it (or export it for distribution).

The Docker instructions below are for Windows; run the commands in PowerShell. No local Python or Node.js
installation is needed to run a supplied image.

### Prerequisites

- Docker Desktop running Linux containers, with Docker Compose v2 supporting `--wait`.
- Network/VPN/firewall access from Docker to both databases and Microsoft sign-in.
- An image matching your CPU architecture. The `v2.0` ARM64 build targets
  **linux/arm64**; Intel/AMD PCs need **linux/amd64**. Check your processor type in
  Windows Settings > System > About > System type.

Install [Docker Desktop for Windows](https://docs.docker.com/desktop/setup/install/windows-install/),
following your organization's installation policy and Docker's setup prompts. Restart
Windows if requested. Open Docker Desktop, wait until the engine is running with Linux
containers, then verify Docker is ready:

```powershell
docker version
docker compose version
```

The first command must show both Client and Server information. If either command
fails, resolve the error before continuing.

The image includes Oracle and PostgreSQL drivers. MySQL and SQL Server/Azure SQL
require additional Python/system drivers; selecting an engine does not install them.

### Option 1: Run a Pre-Built Image

Two tested images are provided under `Images/`, one per CPU architecture:

| Architecture | Folder | Image archive | Image tag |
| --- | --- | --- | --- |
| ARM64 (`linux/arm64`) | `Images/Migration-Validator-v2.0_ARM64` | `migration-validator-v2.0-arm64.tar` | `migration-validator:v2.0` |
| AMD64 (`linux/amd64`) | `Images/Migration-Validator-v2.0_AMD64` | `migration-validator-v2.0-amd64.tar` | `migration-validator:v2.0-amd64` |

Each folder also ships the matching `docker-compose.yml`.

#### 1. Prepare the Files

Create `C:\MigrationValidator` and copy the `docker-compose.yml` and the `.tar`
archive for your architecture from the matching `Images/` folder into it:

```text
C:\MigrationValidator\
    docker-compose.yml
    migration-validator-v2.0-arm64.tar
```

Use the ARM64 TAR for an ARM-based PC and the AMD64 TAR for an Intel/AMD PC. The
commands below expect the Compose file to be named `docker-compose.yml`.

#### 2. Load the Image (First Installation Only)

For the ARM64 release:

```powershell
Set-Location C:\MigrationValidator
docker load --input .\migration-validator-v2.0-arm64.tar
if ($LASTEXITCODE -ne 0) { throw "Image loading failed. Do not continue." }
$env:MV_IMAGE = "migration-validator:v2.0"
```

For the AMD64 release, use this block instead:

```powershell
Set-Location C:\MigrationValidator
docker load --input .\migration-validator-v2.0-amd64.tar
if ($LASTEXITCODE -ne 0) { throw "Image loading failed. Do not continue." }
$env:MV_IMAGE = "migration-validator:v2.0-amd64"
```

**Important:** Use the exact tag printed after `Loaded image:` as `MV_IMAGE`. The TAR
filename does not determine its image tag. The ARM64 release uses
`migration-validator:v2.0`, not `migration-validator:v2.0-arm64`.

#### 3. Start the Application

```powershell
$env:MV_PORT = "8000"
$env:MV_HOST_DATA_DIR = "$env:LOCALAPPDATA\MigrationValidator"
docker image inspect $env:MV_IMAGE --format '{{.Os}}/{{.Architecture}}'
if ($LASTEXITCODE -ne 0) { throw "Image tag not found. Check MV_IMAGE." }
New-Item -ItemType Directory -Force -Path $env:MV_HOST_DATA_DIR -ErrorAction Stop | Out-Null
docker compose -p migration-validator-desktop -f .\docker-compose.yml up -d --no-build --pull never --wait
if ($LASTEXITCODE -ne 0) { throw "Startup failed. Check the container logs." }
```

This starts the loaded image without building or downloading another image. Open
**http://localhost:8000** after the command succeeds. If port 8000 is already in use,
set `$env:MV_PORT = "8001"`, repeat the Compose startup command, and open
**http://localhost:8001** instead.

Saved profiles, history, reports, and logs are stored in
`%LOCALAPPDATA%\MigrationValidator`. Keep this folder; it is separate from the TAR.

### Option 2: Build the Image from the Dockerfile

Run from the repository root. The multi-stage build compiles the current React UI and
packages it with Python; no separate Vite server is used in Docker.

```powershell
docker build --progress plain -f docker/Dockerfile -t migration-validator:v2.0 .
$env:MV_IMAGE = "migration-validator:v2.0"
$env:MV_PORT = "8000"
$env:MV_HOST_DATA_DIR = "$env:LOCALAPPDATA\MigrationValidator"
docker image inspect $env:MV_IMAGE --format '{{.Os}}/{{.Architecture}}'
if ($LASTEXITCODE -ne 0) { throw "Image tag not found. Check MV_IMAGE." }
New-Item -ItemType Directory -Force -Path $env:MV_HOST_DATA_DIR -ErrorAction Stop | Out-Null
docker compose -p migration-validator-desktop -f docker/docker-compose.yml up -d --no-build --wait
```

Open **http://localhost:8000**. If local development occupies port 8000, set
`$env:MV_PORT = "8001"` before starting and open **http://localhost:8001** instead.
Use the same Compose project, port, image and data directory on subsequent commands.

Builds default to Microsoft package feeds (`packagefeedproxy.microsoft.io/npm/` and
`packagefeedproxy.microsoft.io/pypi/simple/`); Docker base images come from Docker Hub.
`NPM_REGISTRY` and `PIP_INDEX_URL` build arguments allow approved alternatives, though
the npm lockfile also contains resolved feed URLs. Do not disable TLS verification or
put credentials in build arguments.

For Intel/AMD recipients, build and test an AMD64 image separately (requires a builder
capable of that platform):

```powershell
docker buildx build --platform linux/amd64 --load -f docker/Dockerfile -t migration-validator:v2.0-amd64 .
```

#### Distribute a Built Image

On the publisher's machine, export the tested image. These example commands use the
ARM64 tag; substitute the AMD64 tag/archive for Intel/AMD recipients.

```powershell
docker save -o migration-validator-v2.0-arm64.tar migration-validator:v2.0
docker save -o migration-validator-v2.0-amd64.tar migration-validator:v2.0-amd64
```

Supply the archive, this README, and `docker/docker-compose.yml`. The recipient places
the Compose file beside the archive as `docker-compose.yml` and follows
[Option 1](#option-1-run-a-pre-built-image) to load and start it. `--no-build` is
required for archive installs: the supplied Compose file also has a source-build
configuration, but recipients do not need the source tree. Never send your development
catalog, passwords, tokens, `.env`, or credential caches.

### First Connection in Docker

1. Open the application at the chosen localhost port.
2. Enter source and target database details. For a database on the Windows host,
   use `host.docker.internal`, not `localhost`. For a remote database use its reachable
   DNS hostname. Docker networking and database firewall access must both work.
3. For Azure PostgreSQL Entra authentication, choose **Browser sign-in**, enter client
   and tenant IDs, and register the displayed callback as a **Single-page application**
   redirect URI. At port 8000 it is `http://localhost:8000/static/auth-callback.html`.
   Register the exact hostname, port and path you use; a Vite callback is different.
4. Test source and target separately, load and select the source/target schemas, then
   **Discover & match**, review scope/mappings,
   choose checks and run validation. Review individual results, not only run completion.

Leave local developer authentication disabled. Its UI option is currently visible
but rejected by the Docker backend. Do not mount Windows credential caches to enable
it. Optional `MV_ENTRA_CLIENT_ID`/`MV_ENTRA_TENANT_ID` deployment defaults apply only
when both website fields are empty; changing these defaults requires container
recreation and page reload. User-entered IDs need neither a rebuild nor a restart.

### Persistence and Data Storage

Compose mounts `%LOCALAPPDATA%\MigrationValidator` at `/app/data`, with SQLite at
`/app/data/catalog.sqlite3` and reports/logs in neighboring folders. On first startup
the database is initialized; image replacement does not recreate existing data.
Unknown catalog versions fail closed. Existing local development data is not imported
automatically. To use a different host folder, set this before starting Compose:

```powershell
$env:MV_HOST_DATA_DIR = "D:\MigrationValidator"
```

Use a local, non-synchronized directory. Never let local Python and Docker write to the
same catalog at the same time. For Linux hosts, explicitly set `MV_HOST_DATA_DIR` and
grant container UID 10001 write access. Reports can contain sensitive data; protect the
host directory and backups. The UI's **Back up catalog** copies SQLite only, not the
separate reports/logs. The complete implementation, import/restore procedures, scoped
rerun behavior, security limits and verification status are in
[Desktop persistence and reruns](documentation/desktop-persistence-and-reruns.md).

### Update to a New Version

Obtain the new TAR, its exact image tag, and matching Compose file from your provider.
Use the release matching your CPU architecture. Place the new TAR in
`C:\MigrationValidator`, keep the current Compose file until after the backup below,
start Docker Desktop, and wait for all validations to finish.

**A. Stop the current application.** Set the installed image tag, original port, and
data folder (this example uses an ARM64 v1.0 installation being updated to v2.0):

```powershell
Set-Location C:\MigrationValidator
$env:MV_IMAGE = "migration-validator:v1.0"
$env:MV_PORT = "8000"
$env:MV_HOST_DATA_DIR = "$env:LOCALAPPDATA\MigrationValidator"
docker compose -p migration-validator-desktop -f .\docker-compose.yml stop
if ($LASTEXITCODE -ne 0) { throw "Stop failed. Do not continue." }
```

For an existing AMD64 v1.0 install, use `migration-validator:v1.0-amd64`. If you
previously chose a different port or data folder, use those original values.

**B. Back up saved data.** Keep the app stopped while backing up the entire folder:

```powershell
if (-not (Test-Path -LiteralPath (Join-Path $env:MV_HOST_DATA_DIR "catalog.sqlite3") -PathType Leaf)) {
    throw "Existing catalog not found. Verify the original data folder."
}
$backup = "$env:MV_HOST_DATA_DIR-backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
Copy-Item -LiteralPath $env:MV_HOST_DATA_DIR -Destination $backup -Recurse -ErrorAction Stop
Copy-Item -LiteralPath .\docker-compose.yml -Destination (Join-Path $backup "previous-compose.yml") -ErrorAction Stop
Write-Host "Backup saved to: $backup"
```

This preserves the catalog, reports, logs, and previous Compose file. Ensure no other
application or container writes to this data folder during the backup.

**C. Load the new image.** Replace the Compose file with the new supplied file, keeping
the name `docker-compose.yml`. This example is an ARM64 v2.0 release; replace the TAR
filename and tag with the exact values supplied by your provider:

```powershell
docker load --input .\migration-validator-v2.0-arm64.tar
if ($LASTEXITCODE -ne 0) { throw "Image loading failed. Do not continue." }
$env:MV_IMAGE = "migration-validator:v2.0"
docker image inspect $env:MV_IMAGE --format '{{.Os}}/{{.Architecture}}'
if ($LASTEXITCODE -ne 0) { throw "New image tag not found. Check MV_IMAGE." }
```

Use the tag printed after `Loaded image:`. For an AMD64 release, use its AMD64 TAR and
supplied tag, for example `migration-validator:v2.0-amd64`. Confirm the displayed
platform matches your computer: `linux/arm64` or `linux/amd64`.

**D. Start the new version.** Keep the same data folder, port, and Compose project:

```powershell
docker compose -p migration-validator-desktop -f .\docker-compose.yml up -d --no-build --pull never --force-recreate --wait
if ($LASTEXITCODE -ne 0) { throw "Update startup failed. Check the container logs." }
docker compose -p migration-validator-desktop -f .\docker-compose.yml ps
Invoke-RestMethod "http://localhost:$env:MV_PORT/api/health" -ErrorAction Stop
```

Loading a TAR alone does not update a running container; the command above replaces it
with the new image. Refresh the browser, confirm previous runs and profiles are
present, test both database connections, and run a small validation.

**If the update fails:** stop the application and contact your provider with the error
and image tag. Do not delete the saved-data folder. An update may change the catalog
format, so do not simply start the old image against updated data. Rollback requires
the old image, its matching Compose file, and restoration of the pre-update data backup
while the application is stopped. Restoring that backup discards changes made after it
was taken.

### Status, Logs, and Troubleshooting

Check whether the application is running and healthy, view recent output, or stop it —
none of these commands delete the host data:

```powershell
docker compose -p migration-validator-desktop -f .\docker-compose.yml ps
docker compose -p migration-validator-desktop -f .\docker-compose.yml logs --tail 100
docker compose -p migration-validator-desktop -f .\docker-compose.yml down
```

`down` stops and removes the application container and its Compose network. It does not
delete the image or the saved-data folder. Wait for all validations to finish before
stopping; stopping Docker or shutting down the computer interrupts active validations,
which do not automatically resume. If the image is not found, run `docker image ls` and
check that `MV_IMAGE` matches a loaded tag.

From a source checkout, the desktop launcher is an alternative build/start workflow:

```powershell
.\docker\desktop.ps1
```

Use `-Port 8001` if needed, and `-Action Backup`, `-Action Stop`, `-Action Start`, or
`-Action Upgrade` for lifecycle operations. Keep the same `-HostDataDir` override
across actions when using a custom path. This launcher is not required by archive users.

## Local Installation Without Docker

Run the Python backend and built React UI directly on a Windows workstation,
Linux machine, or jumpbox. Docker is not required. These instructions describe
a single-user installation from source, not a managed PaaS deployment.

### Native Installation Prerequisites

- Obtain a trusted source checkout or source ZIP containing `pyproject.toml`,
  `app/`, and `config/type_mappings/`. Extract it to a local directory.
- Install Python 3.12 (the Docker runtime version). The project declares Python
  3.12+; newer interpreter/driver combinations need testing in your environment.
- Install Node.js 22 with npm to build the frontend. Node.js is not needed at
  runtime after the build; a separate Vite development server is not required.
- Allow access to the approved Python/npm package feeds and both databases.
  The npm lockfile contains Microsoft package-feed URLs; restricted networks may
  need an approved mirror/lockfile supplied by the provider. Do not disable TLS.
- Use accounts with SELECT and metadata visibility for the selected database scope.
- For SQL Server/Azure SQL, install Microsoft ODBC Driver 18 for SQL Server
  separately. On Linux, also install the distribution's unixODBC runtime; builds
  without a compatible `pyodbc` wheel may need compiler and development packages.

SQLite is accessed through Python's standard-library `sqlite3` module, not a
`pip install sqlite3` package. Official Windows Python installers include it;
Linux installations need Python with SQLite support. The verification commands
below check that support. If importing `sqlite3` fails, use your distribution's
Python/SQLite packages or a Python build compiled with SQLite support. Installing
the SQLite command-line utility alone does not repair a missing Python extension.
No separate database server or manually created catalog is needed: the app creates
its catalog and schema on first startup.

### Windows Installation

Use PowerShell. Replace the example source location with your extracted repository
folder. Create and activate a virtual environment so subsequent `python` and `pip`
commands use the isolated installation. The execution-policy change applies only
to the current PowerShell process.

```powershell
Set-Location C:\MigrationValidator
python --version
node --version
npm.cmd --version

python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -e ".[web,entra,oracle,postgresql]"
python -m pip check
python -c "import sqlite3; print(sqlite3.sqlite_version)"

npm.cmd --prefix app/web/frontend ci
npm.cmd --prefix app/web/frontend run build
```

Stop if any command fails. Confirm `python --version` reports Python 3.12 before
creating the environment. If it resolves to another version, use the absolute path
to the Python 3.12 executable in the `python -m venv .venv` command.

Configure a separate, persistent native data directory and start the application:

```powershell
$dataDir = Join-Path $env:LOCALAPPDATA "MigrationValidator-Native"
New-Item -ItemType Directory -Force -Path $dataDir, "$dataDir\reports", "$dataDir\logs" | Out-Null
$env:MV_CATALOG_PATH = Join-Path $dataDir "catalog.sqlite3"
$env:MV_REPORT_DIR = Join-Path $dataDir "reports"
$env:MV_RUN_LOG_DIR = Join-Path $dataDir "logs"
$env:MV_TYPE_MAPPINGS_DIR = Join-Path $PWD.Path "config\type_mappings"
$env:MV_WEB_HOST = "127.0.0.1"
$env:MV_WEB_PORT = "8000"
migration-validator-web
```

Open **http://127.0.0.1:8000**. In another PowerShell terminal, verify startup:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

### Linux Installation

Install Python 3.12 with venv support and Node.js 22/npm using the distribution's
approved installation method. Use Bash and replace the source directory below.
Run installation and startup as a non-root user.

```bash
cd "$HOME/migration-validator"
python3.12 --version
node --version
npm --version

python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[web,oracle,postgresql,entra]"
.venv/bin/python -m pip check
.venv/bin/python -c "import sqlite3; print(sqlite3.sqlite_version)"

npm --prefix app/web/frontend ci
npm --prefix app/web/frontend run build
```

Stop if any command fails. Configure storage owned by the application user:

```bash
export MV_CATALOG_PATH="$HOME/.local/share/MigrationValidator-Native/catalog.sqlite3"
export MV_REPORT_DIR="$HOME/.local/share/MigrationValidator-Native/reports"
export MV_RUN_LOG_DIR="$HOME/.local/share/MigrationValidator-Native/logs"
export MV_TYPE_MAPPINGS_DIR="$PWD/config/type_mappings"
mkdir -p "$(dirname "$MV_CATALOG_PATH")" "$MV_REPORT_DIR" "$MV_RUN_LOG_DIR"
chmod 700 "$(dirname "$MV_CATALOG_PATH")" "$MV_REPORT_DIR" "$MV_RUN_LOG_DIR"
export MV_WEB_HOST=127.0.0.1
export MV_WEB_PORT=8000
.venv/bin/migration-validator-web
```

Open **http://127.0.0.1:8000** on that machine. From another terminal with curl:

```bash
curl --fail http://127.0.0.1:8000/api/health
```

### Native Startup, Connections, and Maintenance

`migration-validator-web` is the command installed by the `[project.scripts]`
entry in `pyproject.toml`. It calls `app.web.server.main`, which starts Uvicorn
with the FastAPI app and serves the built UI. Installing only Uvicorn or only
`requirements.txt` is insufficient. With the virtual environment activated, the
equivalent direct command is:

```text
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`MV_WEB_HOST`/`MV_WEB_PORT` apply to the launcher; direct Uvicorn uses its command
arguments. Change the port if 8000 is occupied. These examples keep access local.
For a remote jumpbox, use an approved SSH tunnel or an authenticated HTTPS reverse
proxy. Do not expose port 8000 publicly: API/report endpoints have no built-in user
authentication, and reports can contain sensitive database values. Database Entra
sign-in is not authentication for access to this application.

- The default installation above includes Oracle and PostgreSQL drivers. To add
  MySQL, run the same virtual-environment Python with
  `-m pip install -e ".[mysql]"`; for SQL Server/Azure SQL use `".[sqlserver]"`
  and install ODBC Driver 18. An `all-drivers` extra is also available.
- Test source and target connections in the UI, discover/match objects, then run
  a small validation. For a database on the same machine use `localhost`, not
  Docker's `host.docker.internal`; for remote databases use reachable DNS names.
- For PostgreSQL Entra browser sign-in, follow
  [Microsoft Entra ID Authentication](#microsoft-entra-id-authentication) and register
  the exact callback shown in the UI. At the example URL it is
  `http://127.0.0.1:8000/static/auth-callback.html`.
- Environment variables above are terminal-session settings. On every restart,
  return to the source directory and reapply the storage and host/port settings.
  Alternatively, configure them in an approved service manager or local `.env`
  file. The backend reads `.env` from its working directory; do not distribute
  development `.env` files or credentials.
- Use one web-server process per catalog, without multiple workers or `--reload`.
  Keep storage local and non-synchronized. Never share a writable catalog between
  native Python and Docker, or between different installations.
- Wait for validations to finish, then press Ctrl+C to stop. Closing the server
  terminal interrupts active runs; they do not automatically resume. Unattended
  server operation requires an approved service manager, such as systemd on Linux.
- Before upgrades, stop the app and back up the entire native data folder.
  Update source, reinstall dependencies, rebuild the frontend, and restart with
  the same paths. Catalog upgrades may prevent use by older releases; rollback
  requires the previous code and the pre-upgrade data backup.

## Correctness Hardening

Completed checks are now saved incrementally to the catalog. Open **Logs > Run logs
> Saved check results** to inspect partial results after an interruption. This does
not provide automatic resume, retries, or row-range checkpoints. See the
[simple interruption guide](documentation/desktop-persistence-and-reruns.md#saving-progress-when-validation-stops).
Catalog version 1 is backed up and upgraded to version 2 on first use of this code.
Stop other writers first; older Docker images cannot use the upgraded catalog.
The previously built/exported image does not include this change until rebuilt.

The web UI now submits validation as a background job and polls its run ID. After
acceptance, closing the browser does not stop validation while the backend remains
running. Reopen **Logs > Run logs** to view progress and the final report. One
background job is accepted at a time. Backend restarts interrupt jobs; there is no
automatic resume, retry, row grouping, or checksum behavior change. Run a single
web-server process per catalog. See
[background validation](documentation/desktop-persistence-and-reruns.md#background-validation-in-simple-terms)
for credentials, shutdown behavior, and API details.

The correctness hardening changes make scalar comparison exact, replace ambiguous
checksum serialization, preserve numeric declarations, and prevent unsupported
types or incomplete runs from receiving an unqualified PASS. See
[comparison policies and remaining limits](documentation/correctness.md).
Existing saved reports are not recalculated; rerun validation to apply these changes.

**Data checks on large tables.** Row counts, NULL counts and numeric aggregates are
measured with **one scan per table per side** instead of one scan per check and per
numeric column: a single `SELECT COUNT(*), COUNT(col)…, MIN/MAX/SUM/COUNT(num)… FROM t`
built only from the checks you selected (so Row counts alone is still a plain `COUNT(*)`).
Columns that are NOT NULL on both sides are not scanned for NULLs, and very wide tables
are split into several statements (Oracle allows 1,000 expressions per SELECT). Tables
are profiled concurrently on separate connections (`validation.data.parallel_workers`,
default 4, so up to that many connections per database; set `1` to keep a single
connection) and the source and target of a table are scanned at the same time.
Structural metadata is loaded only when a selected check needs it (aggregates do, because
they skip key columns), no longer because of the profile name.

Every data query has a time limit (`validation.data.timeout_seconds`, default 300 s, `0`
disables it), enforced by the database driver so the query is actually stopped (Oracle
`call_timeout`, PostgreSQL `statement_timeout`, SQL Server query timeout, MySQL
`max_execution_time`). This covers the profile scans, checksum fetches and orphan counts.
When the single scan times out it degrades in steps and always says what is exact:

1. **Exact, by key range.** If the table has a single numeric primary key, the scan is
   retried over `validation.data.fallback_chunks` key ranges (default 32, `0` disables),
   each with its own time limit, and the pieces are added up. The result is exact and can
   PASS.
2. **Exact row count on its own**, then, with
   `validation.data.row_count_strategy: exact_then_estimate` (the default), the database's
   statistics estimate: row counts from Oracle `NUM_ROWS`, PostgreSQL `reltuples`, SQL
   Server `sys.partitions` and MySQL `TABLE_ROWS`; NULL counts from Oracle `NUM_NULLS` and
   PostgreSQL `null_frac`. An estimate is reported as **WARNING**, never PASS: equal
   estimates do not prove the tables match. The result shows which side was estimated and
   the report coverage mode is `statistics_estimate`. Aggregates have no reliable estimate,
   so they are reported as an **ERROR** that says the query timed out.
3. With no statistics (for example before `ANALYZE`), or with `row_count_strategy: exact`,
   the check is an **ERROR** that says so.

`validation.data.max_table_rows_for_column_checks` (default `0`, no limit) skips the
NULL-count and aggregate scans of tables whose statistics estimate is above that many rows;
they are reported **SKIPPED** with the reason, while row counts still run. If one column makes
the combined scan fail (for example a `SUM` overflow), the parts are re-run separately so
that column alone is reported as an ERROR. Min/max statistics are deliberately not used as
an estimate (histograms are not true extremes), and sampling is not used because samples
from two databases are not comparable.

The datatype coverage phase adds test fixtures and assertions only; it does not
change production comparison behavior. Every candidate type has positive,
changed-value and incompatible-declaration scenarios. Unsupported arrays/enums/
time-with-time-zone must remain explicit, not receive a false PASS.

The reporting layer adds explicit incomplete-check indicators, measured data coverage,
and persistent run logs. See [reports and run logs](documentation/reports-and-logs.md)
for status semantics, storage/retention settings, API endpoints, and security limits.

## Architecture

- **Adapters** produce canonical models from a live database, and are the only place
  database-specific SQL lives.
- **Normalization** collapses database-specific types, identifiers and defaults
  into database-independent logical forms.
- **Comparison / validators** operate purely on canonical models and normalized
  values — they never touch a database directly except through the adapter interface.
- **Discovery** builds canonical models the engine and validators consume.
- **Reporting** aggregates `ValidationResult`s into a `ValidationReport`.

## Microsoft Entra ID Authentication

For an Azure PostgreSQL or Azure MySQL connection, select **Microsoft Entra ID** and
enter the database role (PostgreSQL) or Entra database user (MySQL) name as the
username, which can differ from the sign-in account. Azure MySQL needs an Entra
administrator configured on the server and an Entra user created in the database; the
access token is sent as the password over TLS (`mysql_clear_password`).

- **Browser sign-in (Docker and local):** enter **Application (client) ID** and
  **Directory (tenant) ID**, register the displayed **SPA redirect URI**, and click
  the source or target connection-test button. The Microsoft popup runs in the
  user's browser. Use the database resource tenant, including for guest access.
  The application needs Azure OSSRDBMS Database delegated `user_impersonation`
  permission and consent where required; the user also needs database permissions.
  No client secret is required. IDs stay in the current form session, not saved
  profiles. Source and target may use different registrations.
- **Local developer credentials (Windows backend only for this desktop setup):**
  set `$env:MV_ALLOW_LOCAL_ENTRA = "true"` in the terminal before starting Uvicorn.
  This uses the backend process's `DefaultAzureCredential` chain. A supported
  credential source must be signed in; Windows sign-in alone is not sufficient.
  Keep this opt-in disabled for distributed containers. Docker does not inherit
  Windows Azure CLI or VS Code credentials.

Browser mode never falls back to local credentials. Tokens remain in browser memory
and are supplied to the backend only for database operations. Reloading requires
testing/signing in again; a long operation that needs another connection after token
expiry may need restarting. Browser Entra support for Azure SQL/SQL Server is not
implemented (Azure PostgreSQL and Azure MySQL only). In CLI YAML, `auth_method: entra`
retains the default credential chain.

### Azure App Registration Setup (Browser Sign-In)

Browser sign-in uses the MSAL.js SPA (authorization-code-with-PKCE) flow, so it needs
a **public-client** app registration with a **Single-page application** redirect URI.
Do this once; a single registration serves both source and target.

1. **Create the registration.** Azure Portal > **Microsoft Entra ID** >
   **App registrations** > **New registration**. Name it (for example
   `DB Migration Validator`). For **Supported account types**, choose *single tenant*
   for same-tenant users, or *multitenant* if guests or other tenants sign in. Leave
   the redirect URI blank and click **Register**. Copy the **Application (client) ID**
   and **Directory (tenant) ID** from the **Overview** page — these are the two values
   you type into the connection form.
2. **Add the SPA redirect URI.** Registration > **Authentication** >
   **Add a platform** > **Single-page application** (not *Web*). Enter the exact URI
   the form shows in its read-only **SPA redirect URI** field:

   | How you run it | Redirect URI to register |
   | --- | --- |
   | Docker at `http://localhost:8000` | `http://localhost:8000/static/auth-callback.html` |
   | Vite dev server (e.g. `http://localhost:3000`) | `http://localhost:3000/auth-callback.html` |
   | Any host beyond loopback | `https://<your-host>/static/auth-callback.html` (HTTPS) |

   The scheme, host, port (`localhost` vs `127.0.0.1`), and path must match exactly.
   Do not add a client secret.
3. **Add the API permission.** Registration > **API permissions** >
   **Add a permission** > **APIs my organization uses** > search
   **Azure OSSRDBMS Database** > **Delegated permissions** > check
   **user_impersonation** > **Add permissions**.
4. **Grant consent.** If your organization requires it, click
   **Grant admin consent for &lt;tenant&gt;**. Guests or other tenants usually need
   admin consent (or a multitenant registration); otherwise each user consents at
   first sign-in.
5. **Give the identity database permissions.** Sign-in alone grants no database
   access. On the Azure Database for PostgreSQL flexible server, enable
   **Microsoft Entra authentication** and set an **Entra admin**, then connect as that
   admin and create the role for the sign-in identity:

   ```sql
   -- a user
   SELECT * FROM pgaadauth_create_principal('user@contoso.com', false, false);
   -- or a group
   SELECT * FROM pgaadauth_create_principal('DBA Group', false, true);
   ```

   Grant the schema/table privileges validation needs (read is sufficient). In the
   connection form, the **Username** must be that PostgreSQL role name, which can
   differ from the signed-in account (for example a group name).

Then, in the connection form, select **Microsoft Entra ID** > **Browser sign-in**,
paste the client and tenant IDs, confirm the displayed SPA redirect URI matches, and
click **Test source connection** or **Test target connection**. Source and target may
use different registrations. See
[desktop persistence and reruns](documentation/desktop-persistence-and-reruns.md) for
tenant/guest rules and the optional `MV_ENTRA_CLIENT_ID`/`MV_ENTRA_TENANT_ID`
deployment defaults.

## Web UI

The frontend is React 18 + TypeScript + Vite, backed by FastAPI. Navigation contains
Dashboard, Run validation, Reports and Logs; there is no separate Settings page.
The connection fields adapt to the selected engine. Workflow:

1. **Connect** — choose source/target engines, enter details, **Test connection**.
2. **Choose schemas, then Discover & match** — after both connections pass testing,
   use **Load schemas** on each side and select the source and target schemas to
   discover (at least one on each side). For long schema lists, use the search box,
   **Select all shown / Invert / Clear**, or a wildcard pattern or list such as
   `HR*, SALES`; the **Selected** pane lists the current choices with a remove button.
   Engine-owned system schemas (for example Oracle `SYS` or PostgreSQL `pg_catalog`)
   are hidden until **Show system schemas** is ticked, and the target side offers the
   schemas whose names match your source selection. Only the selected schemas are read: the
   catalog query itself is restricted to them, and discovery collects schema and table
   names only, so Discover & match no longer reads columns, constraints, indexes or
   other objects. Schemas and tables are **auto-matched** (exact then
   case-insensitive); unmatched/ambiguous items are shown for review. Manual
   schema/table mapping is an optional override, never required. Source and target
   selections are independent (for example `MIGRATION_TEST` to `migration_test`), and
   changing a selection discards the current discovery result.
   While it runs, a progress bar shows the current stage (reading source, reading
   target, matching and saving), the schema being read and an overall percentage. The
   UI polls `GET /api/plan/progress/{id}` using the `progress_id` query parameter it
   sends to `POST /api/plan`; progress is held in memory only and is optional for API
   callers.
   Because this inventory holds names only, validation runs in full-discovery mode and
   collects the metadata the selected checks need, limited to the selected schemas.
   Saved inventories are labelled "names only"; **Refresh** and **Reuse** are available
   only for inventories that already contain full metadata.
   **Object scope** lists the discovered tables grouped by source schema, so large
   schemas stay manageable:
   - Summary tiles count *Matched*, *Needs review*, *Source only*, *Target only* and
     *Excluded* tables; click a tile to filter (Target only opens a list).
   - Each schema is a collapsible group with a tri-state checkbox, a status bar and
     25 rows at a time (**Show 25 more** / **Show all**). Search, status and schema
     filters narrow what is shown.
   - *Needs review* rows carry a likely target found among the unmapped target tables
     (by name similarity, shown as a percentage): **Accept** it or **Change** it.
     *Source only* rows offer a field limited to unmapped target tables. Manual
     mappings are labelled *Manual* and can be reset.
   - **Bulk actions** apply to the shown rows: include/exclude, include matched only,
     exclude source-only, accept suggestions of 90% or more, and exclude by pattern
     (`*_LOG, TMP_*`).
   - **Export CSV** / **Import CSV** let you edit the mapping in a spreadsheet
     (`target_table` and `included` columns); rows that cannot be applied are reported.
   - Unticking a table adds it to the excluded objects (excluded names always win),
     so selecting "all but a few" does not rewrite the included list. The included and
     excluded objects can still be edited as text under the table list.
3. **Options** — optional migration name, included objects, and excluded objects.
4. **Profile** — Quick / Standard / Full.
5. **Run validation** — categorized, filterable results with JSON/HTML/CSV download.

```powershell
# Terminal 1: backend
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Terminal 2: frontend
npm.cmd --prefix app/web/frontend ci
npm.cmd --prefix app/web/frontend run dev
```

Open http://localhost:5173. Vite proxies `/api` to port 8000. Use `npm` instead of
`npm.cmd` on Linux/macOS. For a single-server setup, run
`npm.cmd --prefix app/web/frontend run build`, then `migration-validator-web` and
open http://127.0.0.1:8000. The build updates the backend's static frontend assets;
rebuild after UI changes. `MV_WEB_HOST` / `MV_WEB_PORT` configure that server command.

This is a trusted-environment tool: API/report endpoints do not implement user
authentication. Use an authenticated reverse proxy and appropriate network access
controls before deployment. Reports may contain sample values and error details;
sanitized execution logs are not a replacement for report access controls.

The JSON API is available under `/api` (`GET /api/health`, `GET /api/supported`,
`POST /api/test-connection`, `POST /api/schemas` (lightweight schema-name listing for
one connection), `POST /api/discover`, `POST /api/plan` (discover +
auto-match), `POST /api/validate`, `GET /api/reports/{migration_id}`, and the same id
with a `.html` or `.csv` suffix for the rendered report).

`POST /api/plan` and the validation requests accept optional, independent
`source_schemas` and `target_schemas` lists. When either is supplied, only those
schemas are discovered, only schema/table names are collected, and the response has
`metadata_complete: false` with the discovered `source_scope`/`target_scope`. A requested
schema that is not visible returns 400, and an explicitly empty list returns 422
(it is never treated as "all schemas"). Omitting both keeps the previous behaviour:
every visible schema is discovered with full metadata. A full-mode validation whose
mapping is empty uses the same scope instead of scanning the whole database. Scope is
kept separate from the schema mapping, which still means source schema → target schema.

> On Windows the DB endpoints run each request's async work on a dedicated
> `SelectorEventLoop` inside FastAPI's threadpool, because psycopg's async
> client cannot use uvicorn's default `ProactorEventLoop`.

## Implementation Workflow

1. Install Python and frontend dependencies.
2. Configure database access and explicit schema mappings.
3. Test connections, discover objects and review mappings.
4. Run a clean baseline with Full, then run deliberate mismatch fixtures in
  isolated databases. Never mutate production data to test the validator.
5. Review individual checks and incomplete/unsupported statuses, not only totals.
6. Configure persistent host report/log storage before container deployment.
7. Run datatype certification for each required version pair and retain evidence.

Limits: object presence/signature checks do not prove view/routine/trigger behavior;
there is no shared source/target snapshot, job-resume service or automatic data
repair. A completed run can have a FAIL outcome. See
[report semantics](documentation/reports-and-logs.md) for status and storage details.

## Extending to a New Database

1. Create `app/adapters/<db>/` implementing `DatabaseAdapter` (all DB-specific SQL
   lives here).
2. Declare its `DatabaseCapabilities`.
3. Add a type-mapping YAML under `config/type_mappings/`.
4. Register a lazy loader in `app/adapters/factory.py`.

The engine, comparison and validators require no changes.

## Documentation

Detailed guides live in the [`documentation/`](documentation/) folder:

- [Architecture overview](docs/architecture-overview.md) — layers, design patterns,
  end-to-end NULL-count trace, extensibility, and a presentation script.
- [Datatype coverage](documentation/datatype-coverage.md) — certification targets,
  fixtures, unsupported cases, and setup/execution instructions.
- [Comparison policies and remaining limits](documentation/correctness.md) —
  correctness hardening and its remaining limitations.
- [Reports and run logs](documentation/reports-and-logs.md) — status
  semantics, data coverage, storage/retention settings, API endpoints, and limits.
- [Desktop persistence and reruns](documentation/desktop-persistence-and-reruns.md) —
  persistence implementation, import/restore procedures, and scoped rerun behavior.


Disclaimer: This solution/tool is provided as open-source sample code and is provided “as is” without warranties or guarantees. The customer is responsible for reviewing, testing, securing, configuring, and validating the solution for their environment and requirements before deployment. The customer remains responsible for the operation, maintenance, security, compliance, and use of the solution in their environment. This project/assets are not officially supported by Microsoft.