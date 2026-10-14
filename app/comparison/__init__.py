"""Comparison engine.

Operates purely on canonical models. Contains no database-specific logic; adding a
new database never requires changes here.
"""

from app.comparison.schema_comparator import SchemaComparator

__all__ = ["SchemaComparator"]
