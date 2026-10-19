"""Single-scan table profiling shared by the row-count, NULL-count and aggregate checks.

Instead of one full scan per check (and one per numeric column), each table is scanned
once per side for exactly the measurements the *selected* checks need. Tables are
profiled concurrently on separate connections (``validation.data.parallel_workers``) and
the source and target of a table are scanned at the same time.

When the single scan exceeds ``timeout_seconds`` the profile degrades in steps, always
labelling what it could not measure exactly:

1. retry over primary-key ranges (exact; each range has its own time limit);
2. exact row count on its own, then the database statistics estimate (WARNING, never PASS);
3. NULL counts from statistics (WARNING); aggregates have no estimate and are reported
   as timed out.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field, replace

from app.adapters._profile import (
    ProfileRequest,
    TableProfile,
    empty_profile,
    merge_profiles,
    split_key_range,
)
from app.adapters.base import DatabaseAdapter
from app.adapters.factory import adapter_factory
from app.core.config import DataValidationConfig
from app.core.enums import LogicalType
from app.core.exceptions import QueryTimeoutError
from app.core.logging import get_logger
from app.models.constraint import ConstraintType
from app.models.table import TableModel
from app.validators._columns import aggregate_columns, null_count_columns
from app.validators._target_lookup import TargetLookup
from app.validators.base import ValidationContext

logger = get_logger(__name__)

_KEY_TYPES = frozenset(
    {LogicalType.SMALLINT, LogicalType.INTEGER, LogicalType.BIGINT, LogicalType.DECIMAL}
)
_NO_STATISTICS = (
    "no database statistics are available to estimate it (gather statistics, for example ANALYZE)"
)


@dataclass
class ProfileOutcome:
    """What was measured for one side of one table, and how."""

    row_count: int | None = None
    row_count_estimated: bool = False
    row_count_error: Exception | None = None
    null_counts: dict[str, int] = field(default_factory=dict)
    null_estimated: set[str] = field(default_factory=set)
    null_error: Exception | None = None
    aggregates: dict[str, dict] = field(default_factory=dict)
    aggregate_errors: dict[str, Exception] = field(default_factory=dict)
    # Set when NULL/aggregate scans were skipped because the table is above the size limit.
    skipped_reason: str | None = None
    mode: str = "single_scan"  # single_scan | chunked | fallback | isolated


@dataclass
class JobOutcome:
    source: ProfileOutcome
    target: ProfileOutcome


@dataclass
class TableJob:
    schema: str
    table: TableModel
    target_schema: str
    target_table: TableModel
    source_request: ProfileRequest
    target_request: ProfileRequest


def profile_key(schema: str, table: str) -> tuple[str, str]:
    return (schema.casefold(), table.casefold())


# -- planning -----------------------------------------------------------------------


def plan_jobs(ctx: ValidationContext) -> list[TableJob]:
    """One job per in-scope, mapped table, sized by the checks the user selected."""
    if ctx.source_model is None or ctx.target_model is None:
        return []
    selected = ctx.selected_checks or frozenset()
    lookup = TargetLookup(ctx.mapping, ctx.target_model)
    jobs: list[TableJob] = []
    for schema in ctx.source_model.schemas:
        if ctx.mapping.is_excluded_schema(schema.name):
            continue
        for table in schema.tables:
            if ctx.mapping.is_excluded_table(schema.name, table.name):
                continue
            target = lookup.table(schema.name, table.name)
            if target is None:
                continue
            target_schema, _target_name, target_model = target
            nulls = [
                (src, tgt) for src, tgt, zero in
                (null_count_columns(ctx, schema.name, table, lookup, target_model)
                 if "null_count" in selected else [])
                if not zero
            ]
            aggregates = (
                aggregate_columns(ctx, schema.name, table, lookup, target_model)
                if "aggregate" in selected else []
            )
            count = "row_count" in selected
            jobs.append(TableJob(
                schema.name, table, target_schema, target_model,
                ProfileRequest(count, tuple(s for s, _ in nulls),
                               tuple(c.name for c, _ in aggregates)),
                ProfileRequest(count, tuple(t for _, t in nulls),
                               tuple(t for _, t in aggregates)),
            ))
    return jobs


# -- running ------------------------------------------------------------------------


class ProfileRunner:
    """Runs table jobs concurrently on a bounded set of source/target connection pairs."""

    def __init__(self, ctx: ValidationContext, jobs: list[TableJob]) -> None:
        self._ctx = ctx
        self._jobs = jobs
        self._data = ctx.config.validation.data
        self._pairs: asyncio.Queue[tuple[DatabaseAdapter, DatabaseAdapter]] = asyncio.Queue()
        self._extra: list[DatabaseAdapter] = []
        self.tasks: dict[tuple[str, str], asyncio.Task[JobOutcome]] = {}

    async def start(self) -> dict[tuple[str, str], asyncio.Task[JobOutcome]]:
        self._pairs.put_nowait((self._ctx.source_adapter, self._ctx.target_adapter))
        workers = max(1, min(self._data.parallel_workers, len(self._jobs)))
        for _ in range(workers - 1):
            if not await self._add_pair():
                break
        for job in self._jobs:
            self.tasks[profile_key(job.schema, job.table.name)] = asyncio.create_task(
                self._run(job)
            )
        return self.tasks

    async def _add_pair(self) -> bool:
        source, target = self._ctx.source_adapter, self._ctx.target_adapter
        if source.config is None or target.config is None:
            return False
        created: list[DatabaseAdapter] = []
        try:
            extra_source = adapter_factory.create(source.config)
            created.append(extra_source)
            extra_target = adapter_factory.create(target.config)
            created.append(extra_target)
            await extra_source.connect()
            await extra_target.connect()
        except Exception as exc:  # e.g. the database refuses more connections
            logger.warning("profile_worker_unavailable", extra={"error": str(exc)})
            for adapter in created:
                with contextlib.suppress(Exception):
                    await adapter.close()
            return False
        self._extra.extend(created)
        self._pairs.put_nowait((extra_source, extra_target))
        return True

    async def _run(self, job: TableJob) -> JobOutcome:
        if job.source_request.empty and job.target_request.empty:
            return JobOutcome(ProfileOutcome(), ProfileOutcome())
        source_adapter, target_adapter = await self._pairs.get()
        try:
            source, target = await asyncio.gather(
                _profile_side(source_adapter, job.schema, job.table,
                              job.source_request, self._data),
                _profile_side(target_adapter, job.target_schema, job.target_table,
                              job.target_request, self._data),
            )
            return JobOutcome(source, target)
        finally:
            self._pairs.put_nowait((source_adapter, target_adapter))

    async def close(self) -> None:
        for task in self.tasks.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        for adapter in self._extra:
            with contextlib.suppress(Exception):
                await adapter.close()
        self._extra.clear()


async def ensure_profiles(
    ctx: ValidationContext,
) -> dict[tuple[str, str], asyncio.Task[JobOutcome]] | None:
    """Start profiling once per run; ``None`` when the engine did not select checks."""
    if ctx.selected_checks is None:
        return None
    if ctx.profiles is None:
        runner = ProfileRunner(ctx, plan_jobs(ctx))
        ctx.profile_runner = runner
        ctx.profiles = await runner.start()
    return ctx.profiles


async def job_outcome(ctx: ValidationContext, schema: str, table: str) -> JobOutcome | None:
    """The profile of a source table, or ``None`` to use the direct per-query path."""
    profiles = await ensure_profiles(ctx)
    if profiles is None:
        return None
    task = profiles.get(profile_key(schema, table))
    return await task if task is not None else None


# -- one side of one table ----------------------------------------------------------


async def _profile_side(
    adapter: DatabaseAdapter,
    schema: str,
    table: TableModel,
    request: ProfileRequest,
    data: DataValidationConfig,
) -> ProfileOutcome:
    outcome = ProfileOutcome()
    if request.empty:
        return outcome
    name = table.name
    limit = data.max_table_rows_for_column_checks
    if limit and (request.null_columns or request.aggregate_columns):
        estimate = await _estimate(adapter, schema, name)
        if estimate is not None and estimate > limit:
            outcome.skipped_reason = (
                f"table has about {estimate:,} rows (statistics), above the "
                f"max_table_rows_for_column_checks limit of {limit:,}"
            )
            request = replace(request, null_columns=(), aggregate_columns=())
            if request.empty:
                return outcome

    try:
        profile = await adapter.run_bounded(
            data.timeout_seconds,
            lambda: adapter.get_table_profile(schema, name, request),
            f"Profile of {schema}.{name}",
        )
    except QueryTimeoutError as timeout_error:
        await _after_timeout(adapter, schema, table, request, data, outcome, timeout_error)
    except Exception:
        await _isolate(adapter, schema, name, request, data, outcome)
    else:
        _fill(outcome, profile, request)
    return outcome


def _fill(outcome: ProfileOutcome, profile: TableProfile, request: ProfileRequest) -> None:
    if request.count:
        outcome.row_count = profile.row_count
    outcome.null_counts = {
        c: profile.null_counts[c] for c in request.null_columns if c in profile.null_counts
    }
    outcome.aggregates = {
        c: profile.aggregates[c] for c in request.aggregate_columns if c in profile.aggregates
    }


async def _estimate(adapter: DatabaseAdapter, schema: str, table: str) -> int | None:
    try:
        return await adapter.get_row_count_estimate(schema, table)
    except Exception:
        return None


async def _after_timeout(
    adapter: DatabaseAdapter,
    schema: str,
    table: TableModel,
    request: ProfileRequest,
    data: DataValidationConfig,
    outcome: ProfileOutcome,
    timeout_error: QueryTimeoutError,
) -> None:
    chunked = await _chunked(adapter, schema, table, request, data)
    if chunked is not None:
        _fill(outcome, chunked, request)
        outcome.mode = "chunked"
        return
    outcome.mode = "fallback"
    name = table.name
    estimates_allowed = data.row_count_strategy == "exact_then_estimate"

    if request.count:
        try:
            outcome.row_count = await adapter.get_row_count_with_timeout(
                schema, name, data.timeout_seconds
            )
        except QueryTimeoutError as exc:
            estimate = await _estimate(adapter, schema, name) if estimates_allowed else None
            if estimate is not None:
                outcome.row_count, outcome.row_count_estimated = estimate, True
            else:
                outcome.row_count_error = (
                    QueryTimeoutError(f"{exc}; {_NO_STATISTICS}") if estimates_allowed else exc
                )
        except Exception as exc:
            outcome.row_count_error = exc

    if request.null_columns:
        estimates: dict[str, int] = {}
        if estimates_allowed:
            with contextlib.suppress(Exception):
                estimates = await adapter.get_null_count_estimates(
                    schema, name, list(request.null_columns)
                )
        if estimates_allowed and set(request.null_columns) <= estimates.keys():
            outcome.null_counts = {c: estimates[c] for c in request.null_columns}
            outcome.null_estimated = set(request.null_columns)
        else:
            outcome.null_error = (
                QueryTimeoutError(f"{timeout_error}; {_NO_STATISTICS}")
                if estimates_allowed else timeout_error
            )

    for column in request.aggregate_columns:
        outcome.aggregate_errors[column] = timeout_error


async def _chunked(
    adapter: DatabaseAdapter,
    schema: str,
    table: TableModel,
    request: ProfileRequest,
    data: DataValidationConfig,
) -> TableProfile | None:
    """Exact profile over primary-key ranges; ``None`` when not possible or still too slow."""
    if data.fallback_chunks < 2:
        return None
    name = table.name
    try:
        key = await _integer_key(adapter, schema, table)
        if key is None:
            return None
        bounds = await adapter.run_bounded(
            data.timeout_seconds,
            lambda: adapter.get_key_range(schema, name, key),
            f"Key range of {schema}.{name}",
        )
        if bounds is None:
            return empty_profile(request)
        parts: list[TableProfile] = []
        for key_range in split_key_range(key, bounds[0], bounds[1], data.fallback_chunks):
            parts.append(await adapter.run_bounded(
                data.timeout_seconds,
                lambda key_range=key_range: adapter.get_table_profile(
                    schema, name, request, key_range
                ),
                f"Profile of {schema}.{name} by {key} range",
            ))
        return merge_profiles(parts)
    except Exception as exc:
        logger.info("profile_chunking_unavailable", extra={"table": f"{schema}.{name}",
                                                           "error": str(exc)})
        return None


async def _integer_key(adapter: DatabaseAdapter, schema: str, table: TableModel) -> str | None:
    constraints = table.constraints or await adapter.get_constraints(schema, table.name)
    primary = next(
        (c for c in constraints if c.constraint_type is ConstraintType.PRIMARY_KEY), None
    )
    if primary is None or len(primary.columns) != 1:
        return None
    columns = table.columns or await adapter.get_columns(schema, table.name)
    column = next((c for c in columns if c.name.casefold() == primary.columns[0].casefold()), None)
    if column is None or column.logical_type not in _KEY_TYPES:
        return None
    return column.name


async def _isolate(
    adapter: DatabaseAdapter,
    schema: str,
    name: str,
    request: ProfileRequest,
    data: DataValidationConfig,
    outcome: ProfileOutcome,
) -> None:
    """The combined scan failed (not a timeout): measure each part on its own so one bad
    column (for example a SUM overflow) cannot hide the others."""
    outcome.mode = "isolated"
    base = replace(request, aggregate_columns=())
    if not base.empty:
        try:
            profile = await adapter.run_bounded(
                data.timeout_seconds,
                lambda: adapter.get_table_profile(schema, name, base),
                f"Profile of {schema}.{name}",
            )
        except Exception as exc:
            if request.count:
                outcome.row_count_error = exc
            if request.null_columns:
                outcome.null_error = exc
        else:
            _fill(outcome, profile, base)
    for column in request.aggregate_columns:
        single = ProfileRequest(aggregate_columns=(column,))
        try:
            profile = await adapter.run_bounded(
                data.timeout_seconds,
                lambda single=single: adapter.get_table_profile(schema, name, single),
                f"Aggregates of {schema}.{name}.{column}",
            )
        except Exception as exc:
            outcome.aggregate_errors[column] = exc
        else:
            outcome.aggregates.update(profile.aggregates)
