"""Validator base class and shared execution context."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from app.adapters.base import DatabaseAdapter
from app.core.config import MigrationConfig
from app.core.enums import DatabaseType, ValidationCategory
from app.mapping.mapping_resolver import MappingResolver
from app.models.capabilities import DatabaseCapabilities
from app.models.database import DatabaseModel
from app.models.result import ValidationResult


class ResultPersistenceError(RuntimeError):
    pass


class ResultBuffer(list[ValidationResult]):
    def __init__(self, record: Callable[[ValidationResult], None]):
        super().__init__()
        self.record = record

    def append(self, result: ValidationResult) -> None:
        self.record(result)
        super().append(result)

    def extend(self, results: Iterable[ValidationResult]) -> None:
        if isinstance(results, ResultBuffer) and results.record == self.record:
            super().extend(results)
            return
        for result in results:
            self.append(result)


@dataclass
class ValidationContext:
    """Everything a validator needs to do its job.

    ``source_model`` / ``target_model`` are populated by the engine's discovery
    step before structural/data validators run.
    """

    source_adapter: DatabaseAdapter
    target_adapter: DatabaseAdapter
    mapping: MappingResolver
    config: MigrationConfig
    source_type: DatabaseType
    target_type: DatabaseType
    target_capabilities: DatabaseCapabilities
    source_model: DatabaseModel | None = None
    target_model: DatabaseModel | None = None
    result_sink: Callable[[str, ValidationResult], None] | None = None
    stage_sink: Callable[[str, str], None] | None = None
    current_stage: str = ""
    stage_results: dict[tuple, ValidationResult] = field(default_factory=dict)
    # Set by the engine to the validators it will run; ``None`` (validators used on their
    # own) keeps the direct per-query path instead of the shared single-scan profile.
    selected_checks: frozenset[str] | None = None
    profiles: dict | None = None
    profile_runner: Any = None

    async def close_profiling(self) -> None:
        """Cancel unfinished table profiles and close the extra worker connections."""
        runner, self.profile_runner = self.profile_runner, None
        self.profiles = None
        if runner is not None:
            await runner.close()

    def record_result(self, result: ValidationResult) -> None:
        if result.category == ValidationCategory.COLUMN and result.classification is None:
            result.classification = "column_attributes"
        if result.category == ValidationCategory.CONNECTIVITY:
            result.classification = "execution"
        if result.category in {ValidationCategory.VIEW, ValidationCategory.ROUTINE,
                               ValidationCategory.TRIGGER, ValidationCategory.PARTITION,
                               ValidationCategory.SEQUENCE}:
            result.validation_scope = (
                "Metadata presence/signature only; "
                "definition and behavior equivalence not validated"
            )
        if self.result_sink is not None:
            try:
                self.result_sink(self.current_stage, result)
            except Exception as exc:
                raise ResultPersistenceError("Could not persist validation result") from exc
        key = (result.check_id, result.category, result.source_object, result.target_object)
        self.stage_results[key] = result

    def record_stage(self, stage: str, status: str) -> None:
        if status == "running":
            self.current_stage = stage
            self.stage_results = {}
        if self.stage_sink is not None:
            try:
                self.stage_sink(stage, status)
            except Exception as exc:
                raise ResultPersistenceError("Could not persist validation stage") from exc

    def result_buffer(self) -> ResultBuffer:
        return ResultBuffer(self.record_result)


class Validator(ABC):
    """A single unit of validation."""

    name: str = "validator"
    category: ValidationCategory

    @abstractmethod
    async def validate(self, ctx: ValidationContext) -> list[ValidationResult]:
        """Run the validation and return its results."""
