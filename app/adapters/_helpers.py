"""Small internal helpers shared by adapters."""

from __future__ import annotations

import inspect
from typing import Any


async def maybe_await(value: Any) -> Any:
    """Await ``value`` if it is awaitable, otherwise return it as-is.

    Lets adapter code treat driver methods uniformly whether the driver exposes
    them as coroutines (async mode) or plain functions (sync fakes in tests).
    """
    if inspect.isawaitable(value):
        return await value
    return value


def schema_name_filter(names: list[str] | None) -> list[str] | None:
    """Normalise requested schema names for a catalog ``LOWER(name) IN (...)`` filter.

    Returns ``None`` when no filter applies, otherwise the de-duplicated lower-cased
    non-blank names (possibly empty, meaning nothing is selected).
    """
    if names is None:
        return None
    return list(dict.fromkeys(n.strip().lower() for n in names if n and n.strip()))
