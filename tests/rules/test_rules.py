"""Migration rule-engine tests (compatibility, object rules, migration rules)."""

from __future__ import annotations

from app.core.enums import DatabaseType, LogicalType, ValidationStatus
from app.models.capabilities import DatabaseCapabilities
from app.models.column import ColumnModel
from app.models.database import DatabaseModel
from app.models.schema import SchemaModel
from app.models.sequence import SequenceModel
from app.models.table import TableModel
from app.rules.compatibility import check_type_compatibility
from app.rules.migration_rules import check_unsupported_features
from app.rules.object_rules import check_identifier_lengths


def _col(name: str, ltype: LogicalType = LogicalType.STRING, **kwargs) -> ColumnModel:
    return ColumnModel(name=name, ordinal_position=1, native_type="t", logical_type=ltype, **kwargs)


def _model(table: TableModel, **schema_kwargs) -> DatabaseModel:
    return DatabaseModel(
        database_type=DatabaseType.ORACLE,
        schemas=[SchemaModel(name="HR", tables=[table], **schema_kwargs)],
    )


def test_unknown_type_flagged() -> None:
    table = TableModel(
        schema_name="HR", name="EMP",
        columns=[_col("DATA", LogicalType.UNKNOWN), _col("NAME", LogicalType.STRING)],
    )
    results = check_type_compatibility(_model(table), DatabaseType.AZURE_POSTGRESQL)
    assert len(results) == 1
    assert results[0].status == ValidationStatus.WARNING
    assert "DATA" in results[0].source_object


def test_identifier_length_flagged_for_postgres() -> None:
    long_name = "a" * 70  # exceeds PostgreSQL's 63-char limit
    table = TableModel(schema_name="HR", name=long_name, columns=[_col("ok")])
    results = check_identifier_lengths(_model(table), DatabaseType.AZURE_POSTGRESQL)
    assert any(r.status == ValidationStatus.WARNING for r in results)
    assert any("truncates at 63" in d for r in results for d in r.differences)


def test_short_identifiers_not_flagged() -> None:
    table = TableModel(schema_name="HR", name="EMP", columns=[_col("id")])
    results = check_identifier_lengths(_model(table), DatabaseType.AZURE_POSTGRESQL)
    assert results == []


def test_sequences_unsupported_flagged() -> None:
    table = TableModel(schema_name="HR", name="EMP", columns=[_col("id")])
    model = _model(table, sequences=[SequenceModel(name="EMP_SEQ")])
    caps = DatabaseCapabilities(sequences=False)
    results = check_unsupported_features(model, caps)
    assert any("sequences" in d for r in results for d in r.differences)


def test_identity_unsupported_flagged() -> None:
    table = TableModel(
        schema_name="HR", name="EMP", columns=[_col("id", LogicalType.INTEGER, is_identity=True)]
    )
    caps = DatabaseCapabilities(identity_columns=False)
    results = check_unsupported_features(_model(table), caps)
    assert any("identity" in d for r in results for d in r.differences)
