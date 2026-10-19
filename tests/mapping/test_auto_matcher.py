"""Automatic schema/table matching (build_plan)."""

from __future__ import annotations

from app.core.enums import DatabaseType
from app.mapping.auto_matcher import build_plan
from app.models.database import DatabaseModel
from app.models.schema import SchemaModel
from app.models.table import TableModel


def _t(schema: str, name: str) -> TableModel:
    return TableModel(schema_name=schema, name=name)


def _source() -> DatabaseModel:
    return DatabaseModel(
        database_type=DatabaseType.ORACLE,
        schemas=[
            SchemaModel(name="HR", tables=[_t("HR", "EMP"), _t("HR", "DEPT")]),
            SchemaModel(name="SALES", tables=[_t("SALES", "ORDERS")]),
        ],
    )


def _target() -> DatabaseModel:
    return DatabaseModel(
        database_type=DatabaseType.AZURE_POSTGRESQL,
        schemas=[
            SchemaModel(name="hr", tables=[_t("hr", "emp"), _t("hr", "dept"), _t("hr", "audit")]),
            SchemaModel(name="analytics", tables=[_t("analytics", "facts")]),
        ],
    )


def test_case_insensitive_schema_and_table_matching() -> None:
    plan = build_plan(_source(), _target())
    matches = {m.source: m for m in plan.schema_matches}
    assert "HR" in matches
    assert matches["HR"].target == "hr"
    assert matches["HR"].match_type == "case_insensitive"
    matched_tables = {t.source: t.target for t in matches["HR"].matched_tables}
    assert matched_tables == {"EMP": "emp", "DEPT": "dept"}
    assert matches["HR"].unmatched_target_tables == ["audit"]


def test_unmatched_source_and_target_schemas() -> None:
    plan = build_plan(_source(), _target())
    assert plan.unmatched_source_schemas == ["SALES"]
    assert plan.unmatched_target_schemas == ["analytics"]


def test_suggested_mapping_only_includes_matches() -> None:
    plan = build_plan(_source(), _target())
    assert plan.suggested_mapping == {"HR": "hr"}


def test_object_counts() -> None:
    plan = build_plan(_source(), _target())
    assert plan.source.schemas == 2
    assert plan.source.tables == 3
    assert plan.target.tables == 4


def test_exact_match_preferred() -> None:
    src = DatabaseModel(database_type=DatabaseType.MYSQL, schemas=[SchemaModel(name="app")])
    tgt = DatabaseModel(
        database_type=DatabaseType.AZURE_POSTGRESQL,
        schemas=[SchemaModel(name="app"), SchemaModel(name="APP")],
    )
    plan = build_plan(src, tgt)
    assert plan.schema_matches[0].match_type == "exact"
    assert plan.schema_matches[0].target == "app"


def test_ambiguous_schema_reported() -> None:
    src = DatabaseModel(database_type=DatabaseType.MYSQL, schemas=[SchemaModel(name="sales")])
    tgt = DatabaseModel(
        database_type=DatabaseType.AZURE_POSTGRESQL,
        schemas=[SchemaModel(name="Sales"), SchemaModel(name="SALES")],
    )
    plan = build_plan(src, tgt)
    assert plan.schema_matches == []
    assert len(plan.ambiguous_schemas) == 1
    assert plan.ambiguous_schemas[0].source == "sales"
    assert set(plan.ambiguous_schemas[0].candidates) == {"Sales", "SALES"}


def test_saved_plan_keeps_unmapped_targets_blank_and_match_labels():
    from app.api.routes import apply_plan_mapping

    source, target = _source(), _target()
    plan = build_plan(source, target)
    apply_plan_mapping(plan, source, target, {"schemas": {"HR": "hr"}})
    matches = {match.source: match for match in plan.schema_matches}
    assert matches["HR"].match_type == "case_insensitive"
    assert matches["SALES"].target == ""
    assert matches["SALES"].match_type == "unmatched"
    assert plan.unmatched_target_schemas == ["analytics"]


def test_saved_plan_blank_skips_and_manual_target_is_explicit():
    from app.api.routes import apply_plan_mapping

    source, target = _source(), _target()
    plan = build_plan(source, target)
    apply_plan_mapping(plan, source, target, {"schemas": {"HR": "  ", "SALES": "analytics"}})
    matches = {match.source: match for match in plan.schema_matches}
    assert matches["HR"].target == ""
    assert matches["SALES"].target == "analytics"
    assert matches["SALES"].match_type == "explicit"
    assert plan.unmatched_target_schemas == ["hr"]
