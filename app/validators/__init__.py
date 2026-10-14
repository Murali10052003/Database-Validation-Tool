"""Validators and the validation engine.

Each validator consumes a :class:`ValidationContext` and returns
:class:`ValidationResult` objects. The engine runs a profile-selected set of
validators, isolating failures so one broken check never aborts the run.
"""

from app.validators.base import ValidationContext, Validator
from app.validators.engine import ValidationEngine

__all__ = ["ValidationContext", "ValidationEngine", "Validator"]
