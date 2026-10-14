# Datatype Coverage and Certification

## Status and Version Policy

Fixtures and assertions define what must work before a datatype can be certified;
they do not turn a mapped datatype into a verified capability. Sample Data
validation has since been removed from new runs; these fixtures now check values
through checksums and applicable aggregates. This does not change the pending
live-certification status.

Initial certification targets:

| Path | Source versions | Target versions | Live certification |
| --- | --- | --- | --- |
| Oracle to PostgreSQL | Oracle 19c and 21c | PostgreSQL 16 and 17 | Pending |
| PostgreSQL to PostgreSQL | PostgreSQL 16 and 17 | PostgreSQL 16 and 17 | Pending |

Run each version pairing you intend to claim, including same-version PostgreSQL
baselines. The suite checks major versions and records exact server version
strings in JUnit properties. Passing on one pair does not certify the other pairs,
managed-service variants, drivers or operating systems. Other server versions are
not covered by this certification suite, even if the application can connect.

No live version is certified by the offline tests. Use the `oracle` and `postgresql`
driver extras, record their exact installed versions, OS and Python version with
each test run, and preserve the JUnit evidence. Oracle Thin mode and Unicode
fixtures require an appropriate database character set (AL32UTF8 recommended).
Use PostgreSQL UTF8 databases. Time-zone fixtures use explicit offsets; they do
not certify regional time-zone rule databases or Oracle local-time-zone behavior.

## Coverage Matrix

`candidate` means positive/value-mismatch/schema-mismatch assertions exist and
must pass live before support is claimed. `unsupported` means the suite expects
NOT_SUPPORTED for the value column and checksums, including changed data.
The machine-readable definitions are in
[cases.py](../tests/integration/datatype_fixtures/cases.py).

| Family / fixture | Oracle representation | PostgreSQL representation | Scope |
| --- | --- | --- | --- |
| smallint, integer, bigint | Not claimed here | Native integer types at signed limits | PG candidate |
| decimal, integral, scale, nulls, swap | NUMBER(p,s) | NUMERIC(p,s) | Both paths candidate |
| real, double | BINARY_FLOAT / BINARY_DOUBLE | REAL / DOUBLE PRECISION | Both paths candidate; finite exactly representable values |
| special_float | Not claimed | NaN, positive/negative infinity | PG candidate |
| unicode, national, char | VARCHAR2 CHAR semantics, NVARCHAR2, CHAR | VARCHAR, CHAR | Both paths candidate |
| text, nclob | CLOB, NCLOB | TEXT | Both paths candidate; CLOB includes a 10,000-character value |
| binary | BLOB | BYTEA | Both paths candidate |
| empty, empty_binary | Not claimed | Empty string/space, empty and 10,000-byte BYTEA | PG candidate |
| oracle_date | DATE including time of day | TIMESTAMP(0) | Both paths candidate |
| timestamp, timestamptz | TIMESTAMP(6), TIMESTAMP(6) WITH TIME ZONE | Corresponding timestamp types | Both paths candidate |
| date, time, interval | Not claimed | DATE, TIME(6), INTERVAL without months | PG candidate |
| boolean, uuid | Not claimed | BOOLEAN, UUID | PG candidate |
| json, jsonb | Not claimed | JSON, JSONB | PG candidate; nested values, key order and JSON null |
| xml | Not claimed | XML | PG candidate; literal text changes, not XML semantic equivalence |
| domain | Not claimed | NUMERIC domain | Base numeric values only; domain identity/constraints not certified |
| array, enum, timetz | Not applicable | INTEGER[], user-defined enum, TIME WITH TIME ZONE | Explicitly unsupported |

Each table has a primary-key `row_id`, one nullable `value` column and four rows.
Per-type tables isolate unsupported types from otherwise comparable data. Primary
keys provide stable ordering; numeric row IDs must not be included in aggregate
checks. These schemas complement rather than replace the three-table migration
smoke test: foreign keys, identity and sequence semantics are not datatype fixtures.

## Test Scenarios

| Target schema | Expected behavior for candidate types |
| --- | --- |
| mv_dt_good | Column metadata, row counts, null counts, checksums and applicable numeric aggregates PASS |
| mv_dt_bad | Same declarations and four rows; changed values fail checksums and applicable aggregates |
| mv_dt_shape | Values cast to VARCHAR(20000); column datatype/length comparison FAIL; row/null counts remain equal |

`dt_swap` exchanges two values between primary keys. MIN, MAX, SUM and COUNT remain
equal while checksums must FAIL. `dt_nulls` introduces one extra SQL
NULL; the suite asserts exact null counts as well as the resulting FAIL.
Other negative cases preserve null counts. Every table includes SQL NULL, and
JSON fixtures also contain JSON null and null elements inside arrays.

The suite does not assert checksum results for incompatible shape fixtures:
that scenario specifically tests metadata. Unsupported types retain their native
types in all three targets, so they cannot obtain a false PASS through casting.
Structural object warnings are not used as a substitute for per-datatype results.
Execution ERROR is not an acceptable deliberate mismatch. Failures are not xfailed
or silently converted to passes; investigate them and obtain approval before
changing core behavior in a subsequent phase.

## Setup and Execution

1. Install the project from the repository root with Python 3.12+:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -e ".[dev,oracle,postgresql]"
   ```

2. Generate SQL in a fresh directory:

   ```powershell
   python -m tests.integration.datatype_fixtures.generate --output Queries/datatype-coverage
   ```

   Generation opens no database connections and refuses to overwrite files.
   The output contains `oracle-source.sql`, `postgres-source.sql`,
   `oracle_postgres-targets.sql`, `postgres_postgres-targets.sql` and `cases.json`.
   If this directory already contains generated scripts, use those scripts or
   choose a new output directory. Generated expressions are trusted test data,
   not a general SQL templating API.

3. Provision isolated databases manually. Do not execute setup SQL on application
   databases. PostgreSQL scripts create fresh schemas and run in a transaction;
   an existing fixture schema causes failure. Use a client that stops on errors,
   such as `psql -v ON_ERROR_STOP=1 -f <script>` with a configured service/login.
   The scripts never drop existing schemas. Use different target databases for
   the two paths because both target scripts use the same three schema names.

   | Database | Setup file |
   | --- | --- |
   | Oracle source | oracle-source.sql |
   | PostgreSQL source for PG-to-PG | postgres-source.sql |
   | PostgreSQL target for Oracle-to-PG | oracle_postgres-targets.sql |
   | PostgreSQL target for PG-to-PG | postgres_postgres-targets.sql |

   In Oracle, have your DBA provision a dedicated `MV_DT_SOURCE` user in a test
   PDB, with CREATE SESSION, CREATE TABLE and sufficient quota in a test tablespace.
   No schema/user password is generated or stored in these scripts. Connect as
   that user and run the Oracle script in SQLcl/SQL*Plus script mode. Its guard
   rejects any other session user. Oracle DDL auto-commits; a failed setup may leave
   partial objects, so recreate the disposable user/database through your DBA
   before retrying. The generator does not provide automatic destructive cleanup.

4. Grant validation accounts only the metadata visibility and SELECT access
   needed for these schemas. Populate process environment variables referenced
   in the two [example configurations](../config/examples/datatype-postgres-postgres.yaml).
   Oracle configuration is [here](../config/examples/datatype-oracle-postgres.yaml).
   Use secure terminal/secret-manager input for passwords. Do not paste secrets
   into chat or commit them. YAML `${VAR}` interpolation reads the process
   environment; a root `.env` is not automatically imported into that environment.
   TLS defaults to enabled; disable it only for an intentional local test server.

5. Run one path at a time, pointing at the target database provisioned for it:

   ```powershell
   $env:MV_DATATYPE_ORACLE_CONFIG = 'config/examples/datatype-oracle-postgres.yaml'
   python -m pytest tests/integration/test_end_to_end.py -k oracle_postgres -v `
     --junitxml=datatype-oracle-results.xml -o junit_family=xunit1

   $env:MV_DATATYPE_POSTGRES_CONFIG = 'config/examples/datatype-postgres-postgres.yaml'
   python -m pytest tests/integration/test_end_to_end.py -k postgres_postgres -v `
     --junitxml=datatype-postgres-results.xml -o junit_family=xunit1
   ```

   Replace `DT_TARGET_*` environment values when switching target databases.
   The YAML mapping must remain the dedicated source schema to `mv_dt_good`.
  The runner selects good/bad/shape in memory, forces Full and a checksum cap of 100,
   rejects exclusions and table/column/type overrides, and runs the unchanged
   ValidationService. No setup, mutation, cleanup or custom SQL runs in pytest.
   Reports stay in memory; JUnit is the explicit evidence output, not the desktop
   application report store. Keep test databases idle while comparisons run.

6. Repeat for every version pairing to be certified. Review each case rather than
   relying on an overall report PASS, especially because unsupported fixtures
   intentionally emit NOT_SUPPORTED. Unset the two `MV_DATATYPE_*_CONFIG` variables
   afterward to restore fully offline default test runs.

## Explicit Limits and Uncertified Types

- PostgreSQL arrays/enums are discovered as unknown logical types. A Python list
  serializer does not by itself provide PostgreSQL array schema support.
- PostgreSQL domains may appear as their base datatype. Base-value tests do not
  prove equivalent domain names, defaults or validation rules.
- Oracle JSON (native 21c or JSON stored in CLOB), RAW, LONG, LONG RAW, BFILE,
  XMLTYPE, ROWID/UROWID, user-defined/spatial types and collections are not
  certified by these fixtures. Mapping entries alone are not evidence of support.
- Unconstrained NUMBER, negative scales, timestamp precision above six fractional
  digits, local-time-zone timestamps and year/month intervals need additional
  agreed conversion policies. Do not advertise them as certified.
- Oracle empty strings become SQL NULL. This suite does not assert equivalence
  between Oracle NULL and PostgreSQL empty text. Oracle empty LOB behavior is not
  certified by the nonempty LOB fixtures.
- LOB driver materialization and Decimal precision may expose current limitations
  in live Oracle runs. The suite intentionally does not patch adapters to hide them.
- JSON decoding may map JSON null and SQL NULL to the same Python value; SQL null
  counts remain a separate check. JSON lexical formatting, duplicate keys and exact
  high-precision JSON numeric semantics are not certified.
- Naive and timezone-aware datetimes are distinct; equal aware instants normalize
  to UTC. No shared source/target transaction snapshot or production-scale LOB
  performance is guaranteed. Fixtures are small correctness tests, not load tests.
- Any type or conversion not listed in the coverage matrix is unverified by this
  suite, including extension types such as CITEXT, spatial types and PostgreSQL MONEY.

## Acceptance Evidence

Offline checks verify fixture completeness, deterministic generation, safe defaults
and the aggregate-preserving mutation. They do not validate SQL against an actual
database parser or certify driver results. A type is certified for a specific path
and version pair only after its matching, value mismatch and shape tests pass live,
along with applicable NULL/count/aggregate assertions. Preserve failed cases as
known blockers; do not change this document's Pending status without live evidence.