"""Bounded checksum validation.

Computes a deterministic digest of every row (key-ordered, value-canonicalized) on
each side up to the configured row cap and compares the two. Hashing happens in
Python over canonicalized values, so the check is engine-agnostic, unlike native
``ORA_HASH``/``hashtext`` which
differ across databases. Larger tables receive prefix-only coverage, not a
whole-table equality claim.
"""

from __future__ import annotations

import hashlib
import json

from app.comparison.data_comparator import canonical_scalar
from app.core.enums import LogicalType, Severity, ValidationCategory, ValidationStatus
from app.models.constraint import ConstraintType
from app.models.result import CheckCoverage, ValidationResult
from app.models.table import TableModel
from app.validators._target_lookup import TargetLookup
from app.validators.base import ValidationContext, Validator


class ChecksumValidator(Validator):
    """Compares ordered row digests up to the configured cap on each side."""

    name = "checksum"
    category = ValidationCategory.CHECKSUM

    async def validate(self, ctx: ValidationContext) -> list[ValidationResult]:
        if ctx.source_model is None:
            return []
        max_rows = ctx.config.validation.data.chunk_size
        lookup = TargetLookup(ctx.mapping, ctx.target_model)
        results = ctx.result_buffer()
        for schema in ctx.source_model.schemas:
            if ctx.mapping.is_excluded_schema(schema.name):
                continue
            for table in schema.tables:
                if ctx.mapping.is_excluded_table(schema.name, table.name):
                    continue
                result = await self._compare_table(ctx, schema.name, table, lookup, max_rows)
                if result.coverage is None:
                    result.coverage = CheckCoverage(mode="checksum", limit=max_rows)
                results.append(result)
        return results

    async def _compare_table(
        self,
        ctx: ValidationContext,
        schema: str,
        table: TableModel,
        lookup: TargetLookup,
        max_rows: int,
    ) -> ValidationResult:
        src_fqn = f"{schema}.{table.name}"
        check_id = f"checksum:{src_fqn}"
        target = lookup.table(schema, table.name)
        if target is None:
            return _result(check_id, src_fqn, src_fqn, ValidationStatus.SKIPPED,
                           Severity.INFO, message="target table not found")
        target_schema, target_table, tgt_model = target
        tgt_fqn = f"{target_schema}.{target_table}"

        src_columns: list[str] = []
        tgt_columns: list[str] = []
        target_types = {column.name: column.logical_type for column in tgt_model.columns}
        for col in table.columns:
            if ctx.mapping.is_excluded_column(schema, table.name, col.name):
                continue
            tgt_name = lookup.column(schema, table.name, col.name, tgt_model)
            if tgt_name is None:
                continue
            if LogicalType.UNKNOWN in {col.logical_type, target_types[tgt_name]}:
                return _result(
                    check_id, src_fqn, tgt_fqn, ValidationStatus.NOT_SUPPORTED, Severity.MEDIUM,
                    message=f"incomplete checksum coverage: unsupported datatype for {col.name}",
                )
            src_columns.append(col.name)
            tgt_columns.append(tgt_name)
        if not src_columns:
            return _result(check_id, src_fqn, tgt_fqn, ValidationStatus.SKIPPED,
                           Severity.INFO, message="no comparable columns")
        src_keys = _key_columns(table, src_columns)
        tgt_keys = [lookup.column(schema, table.name, k, tgt_model) or k for k in src_keys]

        coverage = CheckCoverage(
            mode="checksum", limit=max_rows, source_columns=src_columns,
            target_columns=tgt_columns, source_order=src_keys, target_order=tgt_keys,
            omitted_source_columns=[
                col.name for col in table.columns if col.name not in src_columns
            ],
            checksum_format="migration-validator:typed-json:v1",
        )
        timeout = ctx.config.validation.data.timeout_seconds
        try:
            # One lookahead row detects partial coverage; it is never hashed.
            src_rows = await ctx.source_adapter.run_bounded(
                timeout,
                lambda: ctx.source_adapter.fetch_rows(
                    schema, table.name, src_columns, src_keys, max_rows + 1
                ),
                f"Checksum fetch of {src_fqn}",
            )
            coverage.source_rows_fetched = len(src_rows)
            coverage.source_complete = len(src_rows) <= max_rows
            coverage.capped = not coverage.source_complete
            tgt_rows = await ctx.target_adapter.run_bounded(
                timeout,
                lambda: ctx.target_adapter.fetch_rows(
                    target_schema, target_table, tgt_columns, tgt_keys, max_rows + 1
                ),
                f"Checksum fetch of {tgt_fqn}",
            )
            coverage.target_rows_fetched = len(tgt_rows)
            coverage.target_complete = len(tgt_rows) <= max_rows
            coverage.capped = not coverage.source_complete or not coverage.target_complete
        except Exception as exc:
            return _result(check_id, src_fqn, tgt_fqn, ValidationStatus.ERROR,
                           Severity.HIGH, error=str(exc), coverage=coverage)

        src_rows = src_rows[:max_rows]
        tgt_rows = tgt_rows[:max_rows]
        scope = (
            f"Checksum of the first {max_rows} ordered rows per side only; "
            "rows beyond the cap were not compared"
            if coverage.capped else "Checksum of all fetched rows on both sides"
        )
        try:
            src_digest = _digest(src_rows)
            coverage.source_rows_hashed = len(src_rows)
            tgt_digest = _digest(tgt_rows)
            coverage.target_rows_hashed = len(tgt_rows)
        except TypeError as exc:
            return _result(check_id, src_fqn, tgt_fqn, ValidationStatus.NOT_SUPPORTED,
                           Severity.MEDIUM, message=f"incomplete checksum coverage: {exc}",
                           coverage=coverage)
        matched = src_digest == tgt_digest
        return _result(
            check_id, src_fqn, tgt_fqn,
            ValidationStatus.PASS if matched else ValidationStatus.FAIL,
            Severity.INFO if matched else Severity.HIGH,
            source_value=src_digest[:12],
            target_value=tgt_digest[:12],
            coverage=coverage,
            validation_scope=scope,
            message=(
                f"{'Matches' if matched else 'Mismatch'} within first {max_rows}-row cap; "
                "remaining rows not checked"
                if coverage.capped else None
            ),
            differences=(
                [] if matched else [
                    f"row digest mismatch over {len(src_rows)} source rows"
                    + (
                        f"; first {max_rows}-row cap; remaining rows not checked"
                        if coverage.capped else ""
                    )
                ]
            ),
        )


def _digest(rows: list[tuple]) -> str:
    hasher = hashlib.sha256()
    hasher.update(b"migration-validator:typed-json:v1\x00")
    for row in rows:
        canonical = json.dumps(
            [canonical_scalar(value) for value in row],
            ensure_ascii=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        hasher.update(len(canonical).to_bytes(8, "big"))
        hasher.update(canonical)
    return hasher.hexdigest()


def _key_columns(table: TableModel, fallback: list[str]) -> list[str]:
    for con in table.constraints:
        if con.constraint_type is ConstraintType.PRIMARY_KEY and con.columns:
            return list(con.columns)
    return fallback


def _result(
    check_id: str,
    src_fqn: str,
    tgt_fqn: str,
    status: ValidationStatus,
    severity: Severity,
    **kwargs: object,
) -> ValidationResult:
    return ValidationResult(
        check_id=check_id,
        category=ValidationCategory.CHECKSUM,
        object_type="TABLE",
        source_object=src_fqn,
        target_object=tgt_fqn,
        status=status,
        severity=severity,
        **kwargs,
    )
