"""Object-level comparison: constraints, indexes and sequences.

Cross-database object names rarely match (Oracle upper-cases and auto-names
constraint/index objects differently from PostgreSQL), so matching is done by
*structural signature* — the normalized set of participating columns plus the
object kind — rather than by name. All results are capability-aware: an object a
target legitimately cannot represent is reported ``NOT_SUPPORTED``/``SKIPPED``
rather than ``FAIL``.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from app.core.enums import (
    DatabaseType,
    Severity,
    ValidationCategory,
    ValidationStatus,
)
from app.mapping.mapping_resolver import MappingResolver
from app.models.capabilities import DatabaseCapabilities
from app.models.constraint import ConstraintModel, ConstraintType
from app.models.database import DatabaseModel
from app.models.index import IndexModel
from app.models.result import ValidationResult
from app.models.routine import RoutineModel, RoutineType
from app.models.schema import SchemaModel
from app.models.sequence import SequenceModel
from app.models.table import TableModel
from app.models.trigger import TriggerModel
from app.models.view import ViewModel

_NOT_NULL_CHECK = re.compile(r'^\s*"?\w+"?\s+is\s+not\s+null\s*$', re.IGNORECASE)


class ObjectComparator:
    """Compares constraints, indexes and sequences between two databases."""

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
        self._caps = target_capabilities
        self._result_factory = result_factory

    # -- constraints -------------------------------------------------------

    def compare_constraints(
        self, source: DatabaseModel, target: DatabaseModel
    ) -> list[ValidationResult]:
        results = self._result_factory()
        for src_schema, src_table, tgt_table in self._matched_tables(source, target):
            if tgt_table is None:
                continue
            target_sigs = {
                self._constraint_sig(c, target_side=True) for c in tgt_table.constraints
            }
            for con in src_table.constraints:
                if self._is_not_null_check(con):
                    continue  # nullability is covered by column comparison
                if not self._constraint_supported(con):
                    results.append(
                        self._constraint_result(
                            src_schema, src_table, con, ValidationStatus.NOT_SUPPORTED,
                            Severity.INFO, "not supported by target database",
                        )
                    )
                    continue
                sig = self._constraint_sig(con, target_side=False)
                if sig in target_sigs:
                    results.append(
                        self._constraint_result(
                            src_schema, src_table, con, ValidationStatus.PASS, Severity.INFO
                        )
                    )
                else:
                    status, severity = self._missing_constraint_severity(con)
                    results.append(
                        self._constraint_result(
                            src_schema, src_table, con, status, severity,
                            "constraint missing in target",
                        )
                    )
        return results

    # -- indexes -----------------------------------------------------------

    def compare_indexes(
        self, source: DatabaseModel, target: DatabaseModel
    ) -> list[ValidationResult]:
        results = self._result_factory()
        for src_schema, src_table, tgt_table in self._matched_tables(source, target):
            if tgt_table is None:
                continue
            target_sigs = {self._index_sig(i, target_side=True) for i in tgt_table.indexes}
            for idx in src_table.indexes:
                sig = self._index_sig(idx, target_side=False)
                fqn = f"{src_schema.name}.{src_table.name}"
                if sig in target_sigs:
                    results.append(
                        self._index_result(fqn, idx, ValidationStatus.PASS, Severity.INFO)
                    )
                else:
                    status = ValidationStatus.FAIL
                    severity = Severity.HIGH if idx.unique else Severity.LOW
                    results.append(
                        self._index_result(
                            fqn, idx, status, severity, "index missing in target"
                        )
                    )
        return results

    # -- sequences ---------------------------------------------------------

    def compare_sequences(
        self, source: DatabaseModel, target: DatabaseModel
    ) -> list[ValidationResult]:
        results = self._result_factory()
        if not self._caps.sequences and not self._caps.identity_columns:
            return results
        for src_schema in source.schemas:
            if self._mapping.is_excluded_schema(src_schema.name):
                continue
            tgt_schema = self._resolve_target_schema(src_schema, target)
            target_names = (
                {s.name.casefold() for s in tgt_schema.sequences} if tgt_schema else set()
            )
            for seq in src_schema.sequences:
                if self._mapping.is_excluded_table(src_schema.name, seq.name):
                    continue
                fqn = f"{src_schema.name}.{seq.name}"
                if seq.name.casefold() in target_names:
                    results.append(self._sequence_result(fqn, seq, ValidationStatus.PASS))
                else:
                    results.append(
                        self._sequence_result(
                            fqn, seq, ValidationStatus.FAIL,
                            "sequence missing in target",
                        )
                    )
        return results

    # -- views -------------------------------------------------------------

    def compare_views(
        self, source: DatabaseModel, target: DatabaseModel
    ) -> list[ValidationResult]:
        results = self._result_factory()
        for src_schema in source.schemas:
            if self._mapping.is_excluded_schema(src_schema.name):
                continue
            tgt_schema = self._resolve_target_schema(src_schema, target)
            target_names = {v.name.casefold() for v in tgt_schema.views} if tgt_schema else set()
            for view in src_schema.views:
                if self._mapping.is_excluded_table(src_schema.name, view.name):
                    continue
                fqn = f"{src_schema.name}.{view.name}"
                supported = self._caps.materialized_views if view.materialized else self._caps.views
                if not supported:
                    results.append(
                        self._view_result(fqn, view, ValidationStatus.NOT_SUPPORTED,
                                           Severity.INFO, "not supported by target database")
                    )
                elif view.name.casefold() in target_names:
                    results.append(
                        self._view_result(fqn, view, ValidationStatus.PASS, Severity.INFO)
                    )
                else:
                    results.append(
                        self._view_result(fqn, view, ValidationStatus.FAIL, Severity.HIGH,
                                          "view missing in target")
                    )
        return results

    # -- routines ----------------------------------------------------------

    def compare_routines(
        self, source: DatabaseModel, target: DatabaseModel
    ) -> list[ValidationResult]:
        results = self._result_factory()
        for src_schema in source.schemas:
            if self._mapping.is_excluded_schema(src_schema.name):
                continue
            tgt_schema = self._resolve_target_schema(src_schema, target)
            target_sigs = (
                {(r.routine_type, r.name.casefold()) for r in tgt_schema.routines}
                if tgt_schema
                else set()
            )
            for routine in src_schema.routines:
                if self._mapping.is_excluded_table(src_schema.name, routine.name):
                    continue
                fqn = f"{src_schema.name}.{routine.name}"
                if not self._routine_supported(routine):
                    results.append(
                        self._routine_result(fqn, routine, ValidationStatus.NOT_SUPPORTED,
                                             Severity.INFO, "not supported by target database")
                    )
                elif (routine.routine_type, routine.name.casefold()) in target_sigs:
                    results.append(
                        self._routine_result(fqn, routine, ValidationStatus.PASS, Severity.INFO)
                    )
                else:
                    results.append(
                        self._routine_result(fqn, routine, ValidationStatus.FAIL,
                                            Severity.MEDIUM, "routine missing in target")
                    )
        return results

    # -- triggers ----------------------------------------------------------

    def compare_triggers(
        self, source: DatabaseModel, target: DatabaseModel
    ) -> list[ValidationResult]:
        results = self._result_factory()
        for src_schema, src_table, tgt_table in self._matched_tables(source, target):
            if tgt_table is None:
                continue
            fqn = f"{src_schema.name}.{src_table.name}"
            target_names = {t.name.casefold() for t in tgt_table.triggers}
            for trigger in src_table.triggers:
                if not self._caps.triggers:
                    results.append(
                        self._trigger_result(fqn, trigger, ValidationStatus.NOT_SUPPORTED,
                                             Severity.INFO, "not supported by target database")
                    )
                elif trigger.name.casefold() in target_names:
                    results.append(
                        self._trigger_result(fqn, trigger, ValidationStatus.PASS, Severity.INFO)
                    )
                else:
                    results.append(
                        self._trigger_result(fqn, trigger, ValidationStatus.FAIL,
                                            Severity.MEDIUM, "trigger missing in target")
                    )
        return results

    # -- partitions --------------------------------------------------------

    def compare_partitions(
        self, source: DatabaseModel, target: DatabaseModel
    ) -> list[ValidationResult]:
        results = self._result_factory()
        for src_schema, src_table, tgt_table in self._matched_tables(source, target):
            if not src_table.partitions:
                continue
            fqn = f"{src_schema.name}.{src_table.name}"
            if not self._caps.partitions:
                results.append(
                    self._partition_result(fqn, src_table, ValidationStatus.NOT_SUPPORTED,
                                          Severity.INFO, "partitioning not supported by target")
                )
            elif tgt_table is not None and tgt_table.partitions:
                results.append(
                    self._partition_result(fqn, src_table, ValidationStatus.PASS, Severity.INFO)
                )
            else:
                results.append(
                    self._partition_result(fqn, src_table, ValidationStatus.FAIL,
                                          Severity.MEDIUM, "table is not partitioned in target")
                )
        return results

    # -- table matching ----------------------------------------------------

    def _matched_tables(
        self, source: DatabaseModel, target: DatabaseModel
    ) -> list[tuple[SchemaModel, TableModel, TableModel | None]]:
        pairs: list[tuple[SchemaModel, TableModel, TableModel | None]] = []
        for src_schema in source.schemas:
            if self._mapping.is_excluded_schema(src_schema.name):
                continue
            tgt_schema = self._resolve_target_schema(src_schema, target)
            tgt_index = (
                {t.name.casefold(): t for t in tgt_schema.tables} if tgt_schema else {}
            )
            for src_table in src_schema.tables:
                if self._mapping.is_excluded_table(src_schema.name, src_table.name):
                    continue
                _, tgt_name = self._mapping.resolve_table(src_schema.name, src_table.name)
                pairs.append((src_schema, src_table, tgt_index.get(tgt_name.casefold())))
        return pairs

    def _resolve_target_schema(
        self, src_schema: SchemaModel, target: DatabaseModel
    ) -> SchemaModel | None:
        target_name = self._mapping.resolve_schema(src_schema.name).casefold()
        return next((s for s in target.schemas if s.name.casefold() == target_name), None)

    # -- signatures --------------------------------------------------------

    def _constraint_sig(self, con: ConstraintModel, *, target_side: bool) -> tuple:
        cols = self._normalize_cols(con.columns)
        if con.constraint_type is ConstraintType.FOREIGN_KEY and con.references is not None:
            ref_table = con.references.ref_table.casefold()
            ref_cols = tuple(sorted(c.casefold() for c in con.references.ref_columns))
            return (con.constraint_type.value, cols, ref_table, ref_cols)
        return (con.constraint_type.value, cols)

    def _index_sig(self, idx: IndexModel, *, target_side: bool) -> tuple:
        cols = tuple(c.name.casefold() for c in idx.columns)
        return (cols, idx.unique)

    @staticmethod
    def _normalize_cols(columns: list[str]) -> tuple[str, ...]:
        # Sort so column order does not affect constraint identity (it does for indexes).
        return tuple(sorted(c.casefold() for c in columns))

    # -- capability + severity ---------------------------------------------

    def _constraint_supported(self, con: ConstraintModel) -> bool:
        if con.constraint_type is ConstraintType.FOREIGN_KEY:
            return self._caps.foreign_keys
        if con.constraint_type is ConstraintType.CHECK:
            return self._caps.check_constraints
        if con.constraint_type is ConstraintType.UNIQUE:
            return self._caps.unique_constraints
        return True

    @staticmethod
    def _missing_constraint_severity(con: ConstraintModel) -> tuple[ValidationStatus, Severity]:
        if con.constraint_type is ConstraintType.PRIMARY_KEY:
            return ValidationStatus.FAIL, Severity.CRITICAL
        if con.constraint_type in (ConstraintType.FOREIGN_KEY, ConstraintType.UNIQUE):
            return ValidationStatus.FAIL, Severity.HIGH
        return ValidationStatus.FAIL, Severity.LOW

    @staticmethod
    def _is_not_null_check(con: ConstraintModel) -> bool:
        return (
            con.constraint_type is ConstraintType.CHECK
            and con.check_expression is not None
            and bool(_NOT_NULL_CHECK.match(con.check_expression))
        )

    def _routine_supported(self, routine: RoutineModel) -> bool:
        if routine.routine_type is RoutineType.PROCEDURE:
            return self._caps.procedures
        return self._caps.functions

    # -- result builders ---------------------------------------------------

    def _constraint_result(
        self,
        schema: SchemaModel,
        table: TableModel,
        con: ConstraintModel,
        status: ValidationStatus,
        severity: Severity,
        message: str | None = None,
    ) -> ValidationResult:
        fqn = f"{schema.name}.{table.name}"
        cols = ",".join(con.columns)
        return ValidationResult(
            check_id=f"constraint:{fqn}.{con.name}",
            category=ValidationCategory.CONSTRAINT,
            object_type=con.constraint_type.value,
            source_object=f"{fqn} ({con.constraint_type.value} {cols})",
            status=status,
            severity=severity,
            differences=[message] if message and status is not ValidationStatus.PASS else [],
            message=message if status is ValidationStatus.NOT_SUPPORTED else None,
        )

    def _index_result(
        self,
        table_fqn: str,
        idx: IndexModel,
        status: ValidationStatus,
        severity: Severity,
        message: str | None = None,
    ) -> ValidationResult:
        cols = ",".join(c.name for c in idx.columns)
        kind = "UNIQUE INDEX" if idx.unique else "INDEX"
        return ValidationResult(
            check_id=f"index:{table_fqn}.{idx.name}",
            category=ValidationCategory.INDEX,
            object_type="INDEX",
            source_object=f"{table_fqn} ({kind} {cols})",
            status=status,
            severity=severity,
            differences=[message] if message and status is not ValidationStatus.PASS else [],
        )

    def _sequence_result(
        self,
        fqn: str,
        seq: SequenceModel,
        status: ValidationStatus,
        message: str | None = None,
    ) -> ValidationResult:
        return ValidationResult(
            check_id=f"sequence:{fqn}",
            category=ValidationCategory.SEQUENCE,
            object_type="SEQUENCE",
            source_object=fqn,
            status=status,
            severity=Severity.INFO if status is ValidationStatus.PASS else Severity.LOW,
            differences=[message] if message and status is not ValidationStatus.PASS else [],
        )

    def _view_result(
        self,
        fqn: str,
        view: ViewModel,
        status: ValidationStatus,
        severity: Severity,
        message: str | None = None,
    ) -> ValidationResult:
        kind = "MATERIALIZED VIEW" if view.materialized else "VIEW"
        return ValidationResult(
            check_id=f"view:{fqn}",
            category=ValidationCategory.VIEW,
            object_type=kind,
            source_object=f"{fqn} ({kind})",
            status=status,
            severity=severity,
            differences=[message] if message and status is not ValidationStatus.PASS else [],
            message=message if status is ValidationStatus.NOT_SUPPORTED else None,
        )

    def _routine_result(
        self,
        fqn: str,
        routine: RoutineModel,
        status: ValidationStatus,
        severity: Severity,
        message: str | None = None,
    ) -> ValidationResult:
        return ValidationResult(
            check_id=f"routine:{fqn}",
            category=ValidationCategory.ROUTINE,
            object_type=routine.routine_type.value,
            source_object=f"{fqn} ({routine.routine_type.value})",
            status=status,
            severity=severity,
            differences=[message] if message and status is not ValidationStatus.PASS else [],
            message=message if status is ValidationStatus.NOT_SUPPORTED else None,
        )

    def _trigger_result(
        self,
        table_fqn: str,
        trigger: TriggerModel,
        status: ValidationStatus,
        severity: Severity,
        message: str | None = None,
    ) -> ValidationResult:
        events = "/".join(trigger.events) if trigger.events else ""
        label = f"{trigger.timing or ''} {events}".strip()
        source_object = (
            f"{table_fqn}.{trigger.name} ({label})" if label else f"{table_fqn}.{trigger.name}"
        )
        return ValidationResult(
            check_id=f"trigger:{table_fqn}.{trigger.name}",
            category=ValidationCategory.TRIGGER,
            object_type="TRIGGER",
            source_object=source_object,
            status=status,
            severity=severity,
            differences=[message] if message and status is not ValidationStatus.PASS else [],
            message=message if status is ValidationStatus.NOT_SUPPORTED else None,
        )

    def _partition_result(
        self,
        table_fqn: str,
        table: TableModel,
        status: ValidationStatus,
        severity: Severity,
        message: str | None = None,
    ) -> ValidationResult:
        strategy = next((p.strategy for p in table.partitions if p.strategy), None)
        count = len(table.partitions)
        label = f"{strategy} · {count} partitions" if strategy else f"{count} partitions"
        return ValidationResult(
            check_id=f"partition:{table_fqn}",
            category=ValidationCategory.PARTITION,
            object_type="PARTITION",
            source_object=f"{table_fqn} ({label})",
            status=status,
            severity=severity,
            differences=[message] if message and status is not ValidationStatus.PASS else [],
            message=message if status is ValidationStatus.NOT_SUPPORTED else None,
        )
