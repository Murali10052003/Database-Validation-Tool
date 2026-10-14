"""Loading of standalone mapping files.

The mapping section is normally part of the migration config, but a mapping may
also be supplied as its own YAML file. Both paths yield a
:class:`~app.core.config.MappingConfig`.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from app.core.config import MappingConfig
from app.core.exceptions import ConfigurationError


def load_mapping(path: str | Path) -> MappingConfig:
    """Load a :class:`MappingConfig` from a YAML file.

    The file may either be a bare mapping document or wrap it under a top-level
    ``mapping:`` key.
    """
    p = Path(path)
    if not p.is_file():
        raise ConfigurationError(f"Mapping file not found: {p}")
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Invalid YAML in mapping file {p}: {exc}") from exc
    if isinstance(data, dict) and "mapping" in data:
        data = data["mapping"]
    try:
        return MappingConfig.model_validate(data)
    except Exception as exc:
        raise ConfigurationError(f"Invalid mapping in {p}: {exc}") from exc
