"""Automatic source-to-target object matching.

Matches schemas and tables between two discovered :class:`DatabaseModel`s using
exact then case-insensitive name matching, so users get a sensible mapping without
entering one by hand. Manual overrides remain optional on top of this.
"""

from __future__ import annotations

from app.models.database import DatabaseModel
from app.models.schema import SchemaModel
from app.models.table import TableModel
from app.schemas.api import (
    AmbiguousMatch,
    ObjectCounts,
    PlanResponse,
    SchemaMatch,
    TableMatch,
)


def build_plan(source: DatabaseModel, target: DatabaseModel) -> PlanResponse:
    """Discover-and-match plan for a source/target pair."""
    target_by_key: dict[str, list[SchemaModel]] = {}
    for tgt in target.schemas:
        target_by_key.setdefault(tgt.name.casefold(), []).append(tgt)

    schema_matches: list[SchemaMatch] = []
    unmatched_source: list[str] = []
    ambiguous: list[AmbiguousMatch] = []
    matched_target_names: set[str] = set()

    for src in source.schemas:
        match, match_type, candidates = _match_one(src.name, target.schemas, target_by_key)
        if match is None:
            if candidates:
                ambiguous.append(AmbiguousMatch(source=src.name, candidates=candidates))
            else:
                unmatched_source.append(src.name)
            continue
        matched_target_names.add(match.name)
        schema_matches.append(_match_tables(src, match, match_type))

    unmatched_target = [
        s.name for s in target.schemas if s.name not in matched_target_names
    ]
    suggested = {m.source: m.target for m in schema_matches}

    return PlanResponse(
        source=_counts(source),
        target=_counts(target),
        schema_matches=schema_matches,
        unmatched_source_schemas=unmatched_source,
        unmatched_target_schemas=unmatched_target,
        ambiguous_schemas=ambiguous,
        suggested_mapping=suggested,
    )


def _match_tables(
    src: SchemaModel, tgt: SchemaModel, match_type: str
) -> SchemaMatch:
    target_by_key: dict[str, list[TableModel]] = {}
    for t in tgt.tables:
        target_by_key.setdefault(t.name.casefold(), []).append(t)

    matched: list[TableMatch] = []
    unmatched_source: list[str] = []
    matched_target: set[str] = set()

    for src_table in src.tables:
        match, ttype, _candidates = _match_one(src_table.name, tgt.tables, target_by_key)
        if match is None:
            unmatched_source.append(src_table.name)
            continue
        matched_target.add(match.name)
        matched.append(
            TableMatch(source=src_table.name, target=match.name, match_type=ttype)
        )

    unmatched_target = [t.name for t in tgt.tables if t.name not in matched_target]
    return SchemaMatch(
        source=src.name,
        target=tgt.name,
        match_type=match_type,
        matched_tables=matched,
        unmatched_source_tables=unmatched_source,
        unmatched_target_tables=unmatched_target,
    )


def _match_one(name, candidates_list, by_key):
    """Return ``(match, match_type, ambiguous_candidates)`` for a source name."""
    exact = next((c for c in candidates_list if c.name == name), None)
    if exact is not None:
        return exact, "exact", []
    ci = by_key.get(name.casefold(), [])
    if len(ci) == 1:
        return ci[0], "case_insensitive", []
    if len(ci) > 1:
        return None, "ambiguous", [c.name for c in ci]
    return None, "none", []


def _counts(model: DatabaseModel) -> ObjectCounts:
    tables = [t for s in model.schemas for t in s.tables]
    return ObjectCounts(
        database_type=model.database_type,
        version=model.version,
        schemas=len(model.schemas),
        tables=len(tables),
        columns=sum(len(t.columns) for t in tables),
        indexes=sum(len(t.indexes) for t in tables),
        constraints=sum(len(t.constraints) for t in tables),
        sequences=sum(len(s.sequences) for s in model.schemas),
        views=sum(len(s.views) for s in model.schemas),
    )
