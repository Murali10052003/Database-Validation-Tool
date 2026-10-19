"""Identifier normalization tests."""

from __future__ import annotations

from app.core.enums import DatabaseType
from app.normalization.identifiers import normalize_identifier


def test_oracle_unquoted_folds_upper_but_compares_case_insensitively() -> None:
    a = normalize_identifier("employees", DatabaseType.ORACLE)
    b = normalize_identifier("EMPLOYEES", DatabaseType.ORACLE)
    assert a == b
    assert a.folded == "EMPLOYEES"


def test_postgres_unquoted_folds_lower() -> None:
    a = normalize_identifier("Employees", DatabaseType.AZURE_POSTGRESQL)
    assert a.folded == "employees"


def test_oracle_vs_postgres_unquoted_match_across_engines() -> None:
    ora = normalize_identifier("EMPLOYEES", DatabaseType.ORACLE)
    pg = normalize_identifier("employees", DatabaseType.AZURE_POSTGRESQL)
    assert ora.comparison_key == pg.comparison_key


def test_quoted_identifier_is_case_sensitive() -> None:
    a = normalize_identifier("Name", DatabaseType.AZURE_POSTGRESQL, quoted=True)
    b = normalize_identifier("name", DatabaseType.AZURE_POSTGRESQL, quoted=True)
    assert a != b
