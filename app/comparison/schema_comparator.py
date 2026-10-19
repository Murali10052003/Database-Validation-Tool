"""Schema-level comparison of two canonical databases.

Compares schemas, tables and columns (type, length, precision, scale, nullability,
defaults, identity/generated flags), honouring the mapping layer and identifier
normalization. Emits :class:`ValidationResult` objects; overall roll-up is done by
the report builder.
"""

from __future__ import annotations

from collections.abc import Callable

from app.core.enums import (
    DatabaseType,
    LogicalType,
    Severity,
    ValidationCategory,
    ValidationStatus,
)
from app.mapping.mapping_resolver import MappingResolver
from app.models.capabilities import DatabaseCapabilities
from app.models.column import ColumnModel
from app.models.database import DatabaseModel
from app.models.result import ValidationResult
from app.models.schema import SchemaModel
from app.models.table import TableModel
from app.normalization.defaults import normalize_default_expression
from app.normalization.identifiers import normalize_identifier

# Logical types for which character length is meaningful.
_LENGTH_TYPES = {LogicalType.STRING, LogicalType.FIXED_STRING}
_DECIMAL_TYPE = LogicalType.DECIMAL
_INTEGER_DIGITS = {LogicalType.SMALLINT: 4, LogicalType.INTEGER: 9, LogicalType.BIGINT: 18}


class SchemaComparator:
    """Compares a source and target :class:`DatabaseModel`."""

    def __init__(
        self,
        mapping: MappingResolver,
        source_type: DatabaseType,
        target_type: DatabaseType,
        target_capabilities: DatabaseCapabilities,
        result_factory: Callable[[], list[ValidationResult]] = list,
    ) -> None:
        self._mapping = mapping
        self._source_type = source_type
        self._target_type = target_type
        self._target_caps = target_capabilities
        self._result_factory = result_factory

    def compare(self, source: DatabaseModel, target: DatabaseModel) -> list[ValidationResult]:
        """Compare two databases and return all schema-level results."""
        results = self._result_factory()
        target_schema_index = self._index_schemas(target)

        for src_schema in source.schemas:
            if self._mapping.is_excluded_schema(src_schema.name):
                results.append(self._skipped_schema(src_schema))
                continue
            target_name = self._mapping.resolve_schema(src_schema.name)
            tgt_schema = target_schema_index.get(self._ckey(target_name, self._target_type))
            if tgt_schema is None:
                results.append(self._missing_schema(src_schema, target_name))
                continue
            results.append(self._present_schema(src_schema, tgt_schema))
            results.extend(self._compare_tables(src_schema, tgt_schema))
        return results

    # -- schema level ------------------------------------------------------

    def _compare_tables(
        self, src_schema: SchemaModel, tgt_schema: SchemaModel
    ) -> list[ValidationResult]:
        results = self._result_factory()
        target_index = {
            self._ckey(t.name, self._target_type): t for t in tgt_schema.tables
        }
        for src_table in src_schema.tables:
            if self._mapping.is_excluded_table(src_schema.name, src_table.name):
                results.append(self._skipped_table(src_schema, src_table))
                continue
            _, target_table_name = self._mapping.resolve_table(src_schema.name, src_table.name)
            tgt_table = target_index.get(self._ckey(target_table_name, self._target_type))
            src_fqn = f"{src_schema.name}.{src_table.name}"
            tgt_fqn = f"{tgt_schema.name}.{target_table_name}"
            if tgt_table is None:
                results.append(
                    ValidationResult(
                        check_id=f"table:{src_fqn}",
                        category=ValidationCategory.TABLE,
                        object_type="TABLE",
                        source_object=src_fqn,
                        target_object=tgt_fqn,
                        status=ValidationStatus.FAIL,
                        severity=Severity.CRITICAL,
                        differences=["table missing in target"],
                    )
                )
                continue
            results.append(
                ValidationResult(
                    check_id=f"table:{src_fqn}",
                    category=ValidationCategory.TABLE,
                    object_type="TABLE",
                    source_object=src_fqn,
                    target_object=tgt_fqn,
                    status=ValidationStatus.PASS,
                )
            )
            results.extend(self._compare_columns(src_schema, src_table, tgt_schema, tgt_table))
        return results

    # -- column level ------------------------------------------------------

    def _compare_columns(
        self,
        src_schema: SchemaModel,
        src_table: TableModel,
        tgt_schema: SchemaModel,
        tgt_table: TableModel,
    ) -> list[ValidationResult]:
        results = self._result_factory()
        target_index = {
            self._ckey(c.name, self._target_type): c for c in tgt_table.columns
        }
        matched_targets: set[str] = set()

        for src_col in src_table.columns:
            if self._mapping.is_excluded_column(src_schema.name, src_table.name, src_col.name):
                continue
            target_col_name = self._mapping.resolve_column(
                src_schema.name, src_table.name, src_col.name
            )
            key = self._ckey(target_col_name, self._target_type)
            tgt_col = target_index.get(key)
            src_fqn = f"{src_schema.name}.{src_table.name}.{src_col.name}"
            tgt_fqn = f"{tgt_schema.name}.{tgt_table.name}.{target_col_name}"
            if tgt_col is None:
                results.append(
                    ValidationResult(
                        check_id=f"column:{src_fqn}",
                        category=ValidationCategory.COLUMN,
                        object_type="COLUMN",
                        source_object=src_fqn,
                        target_object=tgt_fqn,
                        status=ValidationStatus.FAIL,
                        severity=Severity.HIGH,
                        source_value=src_col.native_type,
                        differences=["column missing in target"],
                    )
                )
                continue
            matched_targets.add(key)
            results.append(self._compare_column_pair(src_col, tgt_col, src_fqn, tgt_fqn))

        # Extra columns present only in target are a warning, not a failure.
        for tgt_col in tgt_table.columns:
            if self._ckey(tgt_col.name, self._target_type) not in matched_targets:
                tgt_fqn = f"{tgt_schema.name}.{tgt_table.name}.{tgt_col.name}"
                results.append(
                    ValidationResult(
                        check_id=f"column-extra:{tgt_fqn}",
                        category=ValidationCategory.COLUMN,
                        object_type="COLUMN",
                        source_object=None,
                        target_object=tgt_fqn,
                        status=ValidationStatus.WARNING,
                        severity=Severity.LOW,
                        target_value=tgt_col.native_type,
                        differences=["column exists in target but not in source"],
                    )
                )
        return results

    def _compare_column_pair(
        self, src: ColumnModel, tgt: ColumnModel, src_fqn: str, tgt_fqn: str
    ) -> ValidationResult:
        differences: list[str] = []

        unknown_type = LogicalType.UNKNOWN in {src.logical_type, tgt.logical_type}
        numeric_compatible = (
            self._source_type == DatabaseType.ORACLE
            and self._target_type == DatabaseType.AZURE_POSTGRESQL
            and src.logical_type == _DECIMAL_TYPE
            and tgt.logical_type in _INTEGER_DIGITS
            and src.scale == 0
            and src.precision is not None
            and 1 <= src.precision <= _INTEGER_DIGITS[tgt.logical_type]
        )
        if not unknown_type and not numeric_compatible and src.logical_type != tgt.logical_type:
            differences.append(
                f"type mismatch: {src.native_type} ({src.logical_type.value}) "
                f"vs {tgt.native_type} ({tgt.logical_type.value})"
            )
        if src.logical_type in _LENGTH_TYPES and src.length != tgt.length:
            differences.append(f"length mismatch: {src.length} vs {tgt.length}")
        if src.logical_type == _DECIMAL_TYPE and not numeric_compatible:
            if src.precision != tgt.precision:
                differences.append(f"precision mismatch: {src.precision} vs {tgt.precision}")
            if src.scale != tgt.scale:
                differences.append(f"scale mismatch: {src.scale} vs {tgt.scale}")
        datatype_issue = unknown_type or bool(differences)
        if src.nullable != tgt.nullable:
            differences.append(
                f"nullable mismatch: {str(src.nullable).lower()} vs {str(tgt.nullable).lower()}"
            )

        src_default = normalize_default_expression(src.default_expression)
        tgt_default = normalize_default_expression(tgt.default_expression)
        if src_default != tgt_default:
            differences.append(f"default mismatch: {src_default!r} vs {tgt_default!r}")

        if src.is_identity != tgt.is_identity:
            if src.is_identity and not self._target_caps.identity_columns:
                # Target cannot represent identity: informational, not a failure.
                differences.append("identity not supported by target (informational)")
            else:
                differences.append(
                    f"identity mismatch: {src.is_identity} vs {tgt.is_identity}"
                )

        status = ValidationStatus.PASS if not differences else ValidationStatus.FAIL
        severity = Severity.INFO if not differences else Severity.HIGH
        message = None
        if unknown_type:
            message = (
                f"incomplete datatype coverage: type compatibility not validated for "
                f"{src.native_type} vs {tgt.native_type}"
            )
            if not differences:
                status = ValidationStatus.NOT_SUPPORTED
                severity = Severity.MEDIUM
        return ValidationResult(
            check_id=f"column:{src_fqn}",
            category=ValidationCategory.COLUMN,
            object_type="COLUMN",
            source_object=src_fqn,
            target_object=tgt_fqn,
            status=status,
            severity=severity,
            source_value=src.native_type,
            target_value=tgt.native_type,
            differences=differences,
            message=message,
            classification="datatype" if datatype_issue else "column_attributes",
            validation_scope="Combined column datatype and attribute comparison",
        )

    # -- helpers -----------------------------------------------------------

    def _index_schemas(self, model: DatabaseModel) -> dict[str, SchemaModel]:
        return {self._ckey(s.name, model.database_type): s for s in model.schemas}

    def _ckey(self, name: str, db_type: DatabaseType) -> str:
        """Case-insensitive comparison key for an identifier."""
        return normalize_identifier(name, db_type).comparison_key

    def _present_schema(self, src: SchemaModel, tgt: SchemaModel) -> ValidationResult:
        return ValidationResult(
            check_id=f"schema:{src.name}",
            category=ValidationCategory.SCHEMA,
            object_type="SCHEMA",
            source_object=src.name,
            target_object=tgt.name,
            status=ValidationStatus.PASS,
        )

    def _missing_schema(self, src: SchemaModel, target_name: str) -> ValidationResult:
        return ValidationResult(
            check_id=f"schema:{src.name}",
            category=ValidationCategory.SCHEMA,
            object_type="SCHEMA",
            source_object=src.name,
            target_object=target_name,
            status=ValidationStatus.FAIL,
            severity=Severity.CRITICAL,
            differences=["schema missing in target"],
        )

    def _skipped_schema(self, src: SchemaModel) -> ValidationResult:
        return ValidationResult(
            check_id=f"schema:{src.name}",
            category=ValidationCategory.SCHEMA,
            object_type="SCHEMA",
            source_object=src.name,
            status=ValidationStatus.SKIPPED,
            severity=Severity.INFO,
            message="excluded by mapping",
        )

    def _skipped_table(self, schema: SchemaModel, table: TableModel) -> ValidationResult:
        fqn = f"{schema.name}.{table.name}"
        return ValidationResult(
            check_id=f"table:{fqn}",
            category=ValidationCategory.TABLE,
            object_type="TABLE",
            source_object=fqn,
            status=ValidationStatus.SKIPPED,
            severity=Severity.INFO,
            message="excluded by mapping",
        )
