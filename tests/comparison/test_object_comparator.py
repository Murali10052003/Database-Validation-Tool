"""Object-level comparison (constraints, indexes, sequences)."""

from __future__ import annotations

from app.comparison.object_comparator import ObjectComparator
from app.core.config import MappingConfig
from app.core.enums import DatabaseType, ValidationStatus
from app.mapping.mapping_resolver import MappingResolver
from app.models.capabilities import DatabaseCapabilities
from app.models.constraint import ConstraintModel, ConstraintType, ForeignKeyReference
from app.models.database import DatabaseModel
from app.models.index import IndexColumn, IndexModel
from app.models.partition import PartitionModel
from app.models.routine import RoutineModel, RoutineType
from app.models.schema import SchemaModel
from app.models.sequence import SequenceModel
from app.models.table import TableModel
from app.models.trigger import TriggerModel
from app.models.view import ViewModel

CAPS = DatabaseCapabilities(
    foreign_keys=True, check_constraints=True, unique_constraints=True,
    sequences=True, identity_columns=True,
    views=True, materialized_views=True, procedures=True, functions=True,
    triggers=True, partitions=True,
)


def _comparator() -> ObjectComparator:
    return ObjectComparator(
        mapping=MappingResolver(MappingConfig(schemas={"HR": "hr"})),
        source_type=DatabaseType.ORACLE,
        target_type=DatabaseType.AZURE_POSTGRESQL,
        target_capabilities=CAPS,
    )


def _pk(name: str, cols: list[str]) -> ConstraintModel:
    return ConstraintModel(name=name, constraint_type=ConstraintType.PRIMARY_KEY, columns=cols)


def _model(db: DatabaseType, schema: str, table: TableModel, sequences=None) -> DatabaseModel:
    return DatabaseModel(
        database_type=db,
        schemas=[SchemaModel(name=schema, tables=[table], sequences=sequences or [])],
    )


def test_matching_primary_key_passes_despite_different_names() -> None:
    src_table = TableModel(schema_name="HR", name="EMP", constraints=[_pk("PK_EMP", ["ID"])])
    tgt_table = TableModel(schema_name="hr", name="emp", constraints=[_pk("emp_pkey", ["id"])])
    results = _comparator().compare_constraints(
        _model(DatabaseType.ORACLE, "HR", src_table),
        _model(DatabaseType.AZURE_POSTGRESQL, "hr", tgt_table),
    )
    assert [r.status for r in results] == [ValidationStatus.PASS]


def test_missing_primary_key_fails_critical() -> None:
    src_table = TableModel(schema_name="HR", name="EMP", constraints=[_pk("PK_EMP", ["ID"])])
    tgt_table = TableModel(schema_name="hr", name="emp", constraints=[])
    results = _comparator().compare_constraints(
        _model(DatabaseType.ORACLE, "HR", src_table),
        _model(DatabaseType.AZURE_POSTGRESQL, "hr", tgt_table),
    )
    assert results[0].status == ValidationStatus.FAIL


def test_not_null_check_constraints_are_ignored() -> None:
    nn = ConstraintModel(
        name="SYS_C1", constraint_type=ConstraintType.CHECK,
        columns=["NAME"], check_expression='"NAME" IS NOT NULL',
    )
    src_table = TableModel(schema_name="HR", name="EMP", constraints=[nn])
    tgt_table = TableModel(schema_name="hr", name="emp", constraints=[])
    results = _comparator().compare_constraints(
        _model(DatabaseType.ORACLE, "HR", src_table),
        _model(DatabaseType.AZURE_POSTGRESQL, "hr", tgt_table),
    )
    assert results == []


def test_foreign_key_matches_on_reference_signature() -> None:
    fk = ConstraintModel(
        name="FK_DEPT", constraint_type=ConstraintType.FOREIGN_KEY, columns=["DEPT_ID"],
        references=ForeignKeyReference(ref_table="DEPT", ref_columns=["ID"]),
    )
    fk_t = ConstraintModel(
        name="emp_dept_fk", constraint_type=ConstraintType.FOREIGN_KEY, columns=["dept_id"],
        references=ForeignKeyReference(ref_table="dept", ref_columns=["id"]),
    )
    src = TableModel(schema_name="HR", name="EMP", constraints=[fk])
    tgt = TableModel(schema_name="hr", name="emp", constraints=[fk_t])
    results = _comparator().compare_constraints(
        _model(DatabaseType.ORACLE, "HR", src),
        _model(DatabaseType.AZURE_POSTGRESQL, "hr", tgt),
    )
    assert results[0].status == ValidationStatus.PASS


def test_missing_nonunique_index_fails_present_index_passes() -> None:
    src = TableModel(
        schema_name="HR", name="EMP",
        indexes=[
            IndexModel(name="UX_EMAIL", columns=[IndexColumn(name="EMAIL")], unique=True),
            IndexModel(name="IX_NAME", columns=[IndexColumn(name="NAME")], unique=False),
        ],
    )
    tgt = TableModel(
        schema_name="hr", name="emp",
        indexes=[IndexModel(name="emp_email_key", columns=[IndexColumn(name="email")], unique=True)],
    )
    results = _comparator().compare_indexes(
        _model(DatabaseType.ORACLE, "HR", src),
        _model(DatabaseType.AZURE_POSTGRESQL, "hr", tgt),
    )
    by_status = {r.status for r in results}
    assert ValidationStatus.PASS in by_status  # unique email index matched
    assert ValidationStatus.FAIL in by_status


def test_unmatched_sequence_fails() -> None:
    src = _model(
        DatabaseType.ORACLE, "HR",
        TableModel(schema_name="HR", name="EMP"),
        sequences=[SequenceModel(name="EMP_SEQ")],
    )
    tgt = _model(
        DatabaseType.AZURE_POSTGRESQL, "hr",
        TableModel(schema_name="hr", name="emp"),
        sequences=[],
    )
    results = _comparator().compare_sequences(src, tgt)
    assert results[0].status == ValidationStatus.FAIL
    assert results[0].differences == ["sequence missing in target"]


def _schema_model(db: DatabaseType, schema: str, **kwargs) -> DatabaseModel:
    return DatabaseModel(database_type=db, schemas=[SchemaModel(name=schema, **kwargs)])


def test_view_present_passes_missing_fails() -> None:
    src = _schema_model(
        DatabaseType.ORACLE, "HR",
        views=[ViewModel(name="V_EMP"), ViewModel(name="V_GONE")],
    )
    tgt = _schema_model(DatabaseType.AZURE_POSTGRESQL, "hr", views=[ViewModel(name="v_emp")])
    results = _comparator().compare_views(src, tgt)
    by_status = {r.source_object.split()[0]: r.status for r in results}
    assert by_status["HR.V_EMP"] == ValidationStatus.PASS
    assert by_status["HR.V_GONE"] == ValidationStatus.FAIL


def test_missing_routine_fails() -> None:
    src = _schema_model(
        DatabaseType.ORACLE, "HR",
        routines=[RoutineModel(name="CALC", routine_type=RoutineType.PROCEDURE)],
    )
    tgt = _schema_model(DatabaseType.AZURE_POSTGRESQL, "hr", routines=[])
    results = _comparator().compare_routines(src, tgt)
    assert results[0].status == ValidationStatus.FAIL


def test_include_list_filters_standalone_objects() -> None:
    source = _schema_model(
        DatabaseType.ORACLE, "HR",
        sequences=[SequenceModel(name="EMP_SEQ"), SequenceModel(name="OTHER_SEQ")],
        views=[ViewModel(name="V_EMP"), ViewModel(name="V_OTHER")],
        routines=[
            RoutineModel(name="CALC", routine_type=RoutineType.PROCEDURE),
            RoutineModel(name="OTHER", routine_type=RoutineType.PROCEDURE),
        ],
    )
    target = _schema_model(DatabaseType.AZURE_POSTGRESQL, "hr")
    comparator = ObjectComparator(
        mapping=MappingResolver(MappingConfig(
            schemas={"HR": "hr"},
            included_objects=["HR.EMP_SEQ", "HR.V_EMP", "HR.CALC"],
            excluded_objects=["HR.CALC"],
        )),
        source_type=DatabaseType.ORACLE,
        target_type=DatabaseType.AZURE_POSTGRESQL,
        target_capabilities=CAPS,
    )
    assert len(comparator.compare_sequences(source, target)) == 1
    assert len(comparator.compare_views(source, target)) == 1
    assert comparator.compare_routines(source, target) == []


def test_table_only_include_does_not_validate_standalone_objects() -> None:
    source = _schema_model(
        DatabaseType.ORACLE, "HR",
        sequences=[SequenceModel(name="EMP_SEQ")],
        views=[ViewModel(name="V_EMP")],
        routines=[RoutineModel(name="CALC", routine_type=RoutineType.PROCEDURE)],
    )
    target = _schema_model(DatabaseType.AZURE_POSTGRESQL, "hr")
    comparator = ObjectComparator(
        mapping=MappingResolver(MappingConfig(included_objects=["HR.EMP"])),
        source_type=DatabaseType.ORACLE,
        target_type=DatabaseType.AZURE_POSTGRESQL,
        target_capabilities=CAPS,
    )
    assert comparator.compare_sequences(source, target) == []
    assert comparator.compare_views(source, target) == []
    assert comparator.compare_routines(source, target) == []


def test_trigger_matched_passes_missing_fails() -> None:
    src_table = TableModel(
        schema_name="HR", name="EMP",
        triggers=[
            TriggerModel(name="TRG_AUDIT", table="EMP", timing="BEFORE", events=["INSERT"]),
            TriggerModel(name="TRG_GONE", table="EMP", timing="AFTER", events=["UPDATE"]),
        ],
    )
    tgt_table = TableModel(
        schema_name="hr", name="emp",
        triggers=[TriggerModel(name="trg_audit", table="emp", timing="BEFORE", events=["INSERT"])],
    )
    results = _comparator().compare_triggers(
        _model(DatabaseType.ORACLE, "HR", src_table),
        _model(DatabaseType.AZURE_POSTGRESQL, "hr", tgt_table),
    )
    statuses = {r.status for r in results}
    assert ValidationStatus.PASS in statuses
    assert ValidationStatus.FAIL in statuses


def test_partitioned_source_without_target_partitions_fails() -> None:
    src_table = TableModel(
        schema_name="HR", name="SALES",
        partitions=[PartitionModel(name="P2023", table="SALES", strategy="RANGE")],
    )
    tgt_table = TableModel(schema_name="hr", name="sales", partitions=[])
    results = _comparator().compare_partitions(
        _model(DatabaseType.ORACLE, "HR", src_table),
        _model(DatabaseType.AZURE_POSTGRESQL, "hr", tgt_table),
    )
    assert results[0].status == ValidationStatus.FAIL


def test_missing_check_constraint_fails() -> None:
    constraint = ConstraintModel(
        name="CK_QUANTITY", constraint_type=ConstraintType.CHECK,
        columns=["QUANTITY"], check_expression="QUANTITY > 0",
    )
    source = TableModel(schema_name="HR", name="EMP", constraints=[constraint])
    target = TableModel(schema_name="hr", name="emp", constraints=[])
    results = _comparator().compare_constraints(
        _model(DatabaseType.ORACLE, "HR", source),
        _model(DatabaseType.AZURE_POSTGRESQL, "hr", target),
    )
    assert results[0].status == ValidationStatus.FAIL
    assert results[0].differences == ["constraint missing in target"]


def test_view_not_supported_when_capability_absent() -> None:
    comparator = ObjectComparator(
        mapping=MappingResolver(MappingConfig(schemas={"HR": "hr"})),
        source_type=DatabaseType.ORACLE,
        target_type=DatabaseType.AZURE_POSTGRESQL,
        target_capabilities=DatabaseCapabilities(views=False, materialized_views=False),
    )
    src = _schema_model(DatabaseType.ORACLE, "HR", views=[ViewModel(name="V_EMP")])
    tgt = _schema_model(DatabaseType.AZURE_POSTGRESQL, "hr", views=[])
    results = comparator.compare_views(src, tgt)
    assert results[0].status == ValidationStatus.NOT_SUPPORTED
