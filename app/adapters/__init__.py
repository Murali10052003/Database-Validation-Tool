"""Database adapters.

Each adapter translates a specific database's native metadata and data access into
the canonical models. The factory resolves a :class:`~app.core.enums.DatabaseType`
to a concrete adapter without the core engine ever branching on database type.
"""

from app.adapters.base import DatabaseAdapter
from app.adapters.factory import AdapterFactory, adapter_factory

__all__ = ["AdapterFactory", "DatabaseAdapter", "adapter_factory"]
