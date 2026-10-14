"""Which mapped columns the NULL-count and aggregate checks cover.

Shared by the validators and the profiler so the single scan always measures exactly
what the checks later compare.
"""

from __future__ import annotations

from app.comparison.data_comparator import NUMERIC_TYPES
from app.models.column import ColumnModel
from app.models.constraint import ConstraintType
from app.models.table import TableModel
from app.validators._target_lookup import TargetLookup
from app.validators.base import ValidationContext


def null_count_columns(
    ctx: ValidationContext,
    schema: str,
    table: TableModel,
    lookup: TargetLookup,
    tgt_model: TableModel,
) -> list[tuple[str, str, bool]]:
    """``(source_column, target_column, provably_zero)`` for every compared column.

    A column that is NOT NULL on both sides cannot contain NULLs, so its count is known
    to be 0 on both sides without scanning the table.
    """
    target_columns = {column.name: column for column in tgt_model.columns}
    columns: list[tuple[str, str, bool]] = []
    for col in table.columns:
        if ctx.mapping.is_excluded_column(schema, table.name, col.name):
            continue
        tgt_name = lookup.column(schema, table.name, col.name, tgt_model)
        if tgt_name is None:
            continue
        target = target_columns.get(tgt_name)
        columns.append((
            col.name, tgt_name,
            not col.nullable and target is not None and not target.nullable,
        ))
    return columns


def aggregate_columns(
    ctx: ValidationContext,
    schema: str,
    table: TableModel,
    lookup: TargetLookup,
    tgt_model: TableModel,
) -> list[tuple[ColumnModel, str]]:
    """``(source_column, target_column_name)`` for each numeric, non-key, mapped column."""
    key_columns = {
        column.casefold()
        for constraint in table.constraints
        if constraint.constraint_type
        in (ConstraintType.PRIMARY_KEY, ConstraintType.FOREIGN_KEY)
        for column in constraint.columns
    }
    columns: list[tuple[ColumnModel, str]] = []
    for col in table.columns:
        if col.logical_type not in NUMERIC_TYPES:
            continue
        if col.name.casefold() in key_columns or col.is_identity:
            continue
        if ctx.mapping.is_excluded_column(schema, table.name, col.name):
            continue
        tgt_col = lookup.column(schema, table.name, col.name, tgt_model)
        if tgt_col is None:
            continue
        columns.append((col, tgt_col))
    return columns
