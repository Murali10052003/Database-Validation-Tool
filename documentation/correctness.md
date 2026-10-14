# Validation Correctness

This hardening pass addresses the reproduced false matches and false datatype
PASS results. It is not certification of every Oracle or PostgreSQL datatype.
No live databases are modified or queried by the regression tests.

## Value Comparison

- Integers, Decimal values, and floating-point values share an exact decimal
  representation of their Python value. Decimal context precision is not used
  to round values during comparison or hashing.
- Text remains text: `"00123"` differs from `"123"`, and `"100"` differs from
  numeric `100`. Binary data, booleans, dates, UUIDs, and strings retain type tags.
- Aware timestamps compare as UTC instants. Naive timestamps compare as local
  wall times and never implicitly acquire a timezone.
- Dictionaries with string keys compare recursively without depending on key
  insertion order. Arrays remain ordered. JSON text is not automatically parsed
  or treated as equivalent to a decoded object.
- Numeric zero and negative zero are equal. Numeric NaNs compare equal to each
  other; positive and negative infinity remain distinct. No floating-point
  tolerance is applied. The numeric-only aggregate helper still accepts numeric
  strings, but rejects invalid numeric input rather than comparing its text.
- Unknown runtime objects (such as unhandled driver LOB locators) are not
  stringified. Checksum validation reports NOT_SUPPORTED for that table
  and continues with later tables.

## Checksums

Rows are encoded as typed JSON, prefixed by their byte length, and hashed with
SHA-256. A format marker (`migration-validator:typed-json:v1`) separates this
encoding from historical digests. NULL markers, field separators, row separators,
and binary/text representations cannot create the old serialization collisions.
Numeric scale and timezone representation do not change a digest when the values
are equivalent under the policies above.

New digest values must not be compared with old-format digests. Historical report
files are left unchanged. Re-run validation to generate corrected results.

## Datatype Decisions

Normalization preserves NUMERIC/NUMBER precision and scale, including zero,
negative, and unspecified scale. PostgreSQL-to-PostgreSQL numeric declarations
are compared strictly, so `numeric(9,0)` and `numeric(10,0)` differ.

Oracle NUMBER with explicit scale zero can match a PostgreSQL integer only when
its entire declared range fits:

| PostgreSQL target | Maximum safe Oracle NUMBER precision |
| --- | --- |
| smallint | 4 |
| integer | 9 |
| bigint | 18 |

Consequently NUMBER(10,0) to integer and NUMBER(19,0) to bigint fail, even if a
particular dataset happens to fit. No implicit data-dependent exception is made.
Unknown precision or fractional/negative/unspecified scale is not certified as
integer-compatible. NUMBER and NUMERIC with identical declarations can match.

An unknown logical type on either side produces a column NOT_SUPPORTED result
with an incomplete-coverage message. A definite structural mismatch still wins
and produces FAIL. Checksums also refuse to certify an unknown
column type, even when the currently fetched Python values appear comparable.

PostgreSQL arrays and user-defined types retain their UDT names for diagnostics,
but their definitions are not yet validated. `time with time zone` / `timetz`
is explicitly UNKNOWN rather than being collapsed into ordinary `time`.

## Report Status

- Any FAIL or ERROR produces overall FAIL.
- Warnings, NOT_SUPPORTED, SKIPPED, or an empty result set produce overall WARNING.
- Only nonempty, entirely passing result sets receive overall PASS.

Intentional exclusions can therefore produce WARNING. PASS is scoped to emitted
checks and the chosen profile, not proof that every database feature was examined.
The category health presentation remains a separate UI enhancement.

## Verification and Remaining Limits

Regression coverage includes decimal precision, numeric text, timezone offsets,
typed value boundaries, special numbers, JSON key ordering, checksum framing,
unknown schema/runtime types, integer range decisions, and incomplete report
rollups. Run `pytest` and `npm --prefix app/web/frontend run typecheck`.

The live-database integration test remains skipped. Dedicated fixtures are still
required for actual driver decoding (including large Oracle NUMBER values), LOBs,
timestamp/interval precision, domains, enums, array dimensions, extension types,
JSON/JSONB storage semantics, collation, generated expressions, and concurrent
writes. Parameterized Oracle timezone/interval type names may remain UNKNOWN.
Do not expand mappings merely to remove an unsupported warning.

Sample Data validation has been removed from new runs. Checksums still have the existing
100-source-row default cap and do not stream large tables. Snapshot consistency,
settings wiring, report UI redesign, durable connections, logging, and Docker
delivery remain later phases.