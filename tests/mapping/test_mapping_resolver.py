from app.core.config import MappingConfig
from app.mapping.mapping_resolver import MappingResolver
from app.schemas.api import MappingInput


def test_empty_include_list_preserves_existing_scope():
    resolver = MappingResolver(MappingConfig(excluded_objects=["HR.AUDIT"]))
    assert not resolver.is_excluded_table("HR", "EMPLOYEES")
    assert resolver.is_excluded_table("HR", "AUDIT")


def test_include_only_named_source_objects_case_insensitively():
    resolver = MappingResolver(MappingConfig(
        included_objects=[" hr.employees ", "SALES.ORDERS"],
        schemas={"HR": "public"},
        tables={"HR.EMPLOYEES": "staff"},
    ))
    assert not resolver.is_excluded_schema("HR")
    assert not resolver.is_excluded_table("HR", "EMPLOYEES")
    assert not resolver.is_excluded_column("HR", "EMPLOYEES", "ID")
    assert not resolver.is_excluded_table("sales", "orders")
    assert resolver.is_excluded_table("HR", "AUDIT")
    assert resolver.is_excluded_schema("OTHER")
    assert resolver.is_excluded_table("public", "staff")


def test_include_schema_selects_children_but_exclusions_win():
    resolver = MappingResolver(MappingConfig(
        included_objects=["HR", "SALES.ORDERS"],
        excluded_objects=["HR.AUDIT", "HR.EMPLOYEES.SECRET", "SALES"],
    ))
    assert not resolver.is_excluded_table("HR", "EMPLOYEES")
    assert resolver.is_excluded_table("HR", "AUDIT")
    assert resolver.is_excluded_column("HR", "EMPLOYEES", "SECRET")
    assert resolver.is_excluded_table("SALES", "ORDERS")


def test_blank_include_entries_do_not_limit_scope():
    resolver = MappingResolver(MappingConfig(included_objects=["", "  "]))
    assert not resolver.is_excluded_table("HR", "EMPLOYEES")


def test_api_mapping_preserves_include_list():
    config = MappingInput(included_objects=["HR.EMPLOYEES"]).to_config()
    assert config.included_objects == ["HR.EMPLOYEES"]
    assert MappingInput().to_config().included_objects == []


def test_blank_schema_mapping_skips_schema_and_children():
    resolver = MappingResolver(MappingConfig(schemas={"HR": "  ", "SALES": "sales"}))
    assert resolver.is_excluded_schema("hr")
    assert resolver.is_excluded_table("HR", "EMPLOYEES")
    assert resolver.is_excluded_column("HR", "EMPLOYEES", "ID")
    assert not resolver.is_excluded_schema("SALES")
    assert not MappingResolver(MappingConfig()).is_excluded_schema("HR")