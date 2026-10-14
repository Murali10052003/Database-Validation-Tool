"""Normalization subsystem.

Turns database-specific representations (types, identifiers, default expressions)
into canonical forms so semantically-equal objects compare as equal regardless of
the source or target engine.
"""

from app.normalization.datatypes import NormalizedType, TypeNormalizer
from app.normalization.defaults import normalize_default_expression
from app.normalization.identifiers import NormalizedIdentifier, normalize_identifier

__all__ = [
    "NormalizedIdentifier",
    "NormalizedType",
    "TypeNormalizer",
    "normalize_default_expression",
    "normalize_identifier",
]
