"""Default-value expression normalization.

Wraps :mod:`app.normalization.expressions` and additionally normalizes literal
defaults (strings, numbers, booleans, NULL) so semantically-equal defaults do not
show up as differences.
"""

from __future__ import annotations

import re

from app.normalization.expressions import normalize_expression

_NUMERIC = re.compile(r"^[+-]?\d+(\.\d+)?$")
_STRING_LITERAL = re.compile(r"^'(?P<body>.*)'$", re.DOTALL)
# Trailing PostgreSQL type cast such as ``::bpchar`` or ``::character varying``.
_PG_CAST = re.compile(r"::[A-Za-z0-9_ \[\]\"]+$")
_TRUE = {"TRUE", "'T'", "'Y'", "'1'"}
_FALSE = {"FALSE", "'F'", "'N'", "'0'"}


def normalize_default_expression(expr: str | None) -> str | None:
    """Return a canonical representation of a column default, or ``None``.

    Examples::

        SYSDATE                -> CURRENT_DATETIME
        GETDATE()              -> CURRENT_DATETIME
        'ACTIVE'               -> STR:ACTIVE
        ('ACTIVE')             -> STR:ACTIVE
        0                      -> NUM:0
        NULL                   -> None
    """
    if expr is None:
        return None
    text = expr.strip()
    if not text:
        return None
    # Peel one layer of wrapping parentheses around a literal, e.g. SQL Server ('x').
    stripped = text
    while stripped.startswith("(") and stripped.endswith(")"):
        inner = stripped[1:-1].strip()
        if not inner:
            break
        stripped = inner

    # Drop a trailing PostgreSQL cast (e.g. 'Y'::bpchar) so the boolean and string
    # literal checks below match the bare value, as they do on the source side.
    stripped = _PG_CAST.sub("", stripped).strip()

    upper = stripped.upper()
    if upper == "NULL":
        return None
    if upper in _TRUE:
        return "BOOL:TRUE"
    if upper in _FALSE:
        return "BOOL:FALSE"

    literal = _STRING_LITERAL.match(stripped)
    if literal:
        # Collapse doubled single-quotes inside SQL string literals.
        body = literal.group("body").replace("''", "'")
        return f"STR:{body}"

    if _NUMERIC.match(stripped):
        return f"NUM:{_canonical_number(stripped)}"

    return normalize_expression(stripped)


def _canonical_number(value: str) -> str:
    """Canonicalize a numeric literal (drop trailing zeros / leading plus)."""
    value = value.lstrip("+")
    if "." in value:
        value = value.rstrip("0").rstrip(".")
    if value in ("", "-"):
        value = "0"
    return value
