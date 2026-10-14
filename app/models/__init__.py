"""Canonical, database-independent models.

These Pydantic models form the common representation that every adapter maps into.
The comparison and validation engines operate exclusively on these types and never
see database-specific metadata.
"""

from app.models.capabilities import DatabaseCapabilities
from app.models.column import ColumnModel
from app.models.constraint import ConstraintModel, ForeignKeyReference
from app.models.database import (
    ConnectionResult,
    DatabaseInfo,
    DatabaseModel,
    QueryResult,
)
from app.models.index import IndexColumn, IndexModel
from app.models.partition import PartitionModel
from app.models.routine import RoutineModel
from app.models.schema import SchemaModel
from app.models.sequence import SequenceModel
from app.models.table import TableModel
from app.models.trigger import TriggerModel
from app.models.view import ViewModel

__all__ = [
    "ColumnModel",
    "ConnectionResult",
    "ConstraintModel",
    "DatabaseCapabilities",
    "DatabaseInfo",
    "DatabaseModel",
    "ForeignKeyReference",
    "IndexColumn",
    "IndexModel",
    "PartitionModel",
    "QueryResult",
    "RoutineModel",
    "SchemaModel",
    "SequenceModel",
    "TableModel",
    "TriggerModel",
    "ViewModel",
]
