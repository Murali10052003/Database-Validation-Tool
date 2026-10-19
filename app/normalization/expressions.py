"""Expression normalization primitives.

Maps semantically-equivalent SQL expressions (mainly built-in functions used in
column defaults) to a canonical token, so ``SYSDATE`` (Oracle), ``GETDATE()``
(SQL Server) and ``CURRENT_TIMESTAMP`` (PostgreSQL) are treated as equal.
"""

from __future__ import annotations

import re

# Canonical tokens.
CURRENT_DATETIME = "CURRENT_DATETIME"
CURRENT_DATE = "CURRENT_DATE"
CURRENT_TIME = "CURRENT_TIME"
CURRENT_USER = "CURRENT_USER"
NEW_UUID = "NEW_UUID"

# Native expression -> canonical token. Keys are upper-cased and stripped of a
# trailing empty argument list before lookup.
_SYNONYMS: dict[str, str] = {
    "SYSDATE": CURRENT_DATETIME,
    "SYSTIMESTAMP": CURRENT_DATETIME,
    "NOW": CURRENT_DATETIME,
    "GETDATE": CURRENT_DATETIME,
    "GETUTCDATE": CURRENT_DATETIME,
    "CURRENT_TIMESTAMP": CURRENT_DATETIME,
    "LOCALTIMESTAMP": CURRENT_DATETIME,
    "TRANSACTION_TIMESTAMP": CURRENT_DATETIME,
    "STATEMENT_TIMESTAMP": CURRENT_DATETIME,
    "CURRENT_DATE": CURRENT_DATE,
    "CURDATE": CURRENT_DATE,
    "SYSDATETIME": CURRENT_DATETIME,
    "CURRENT_TIME": CURRENT_TIME,
    "CURTIME": CURRENT_TIME,
    "CURRENT_USER": CURRENT_USER,
    "USER": CURRENT_USER,
    "SESSION_USER": CURRENT_USER,
    "SYS_GUID": NEW_UUID,
    "NEWID": NEW_UUID,
    "GEN_RANDOM_UUID": NEW_UUID,
    "UUID": NEW_UUID,
    "UUID_GENERATE_V4": NEW_UUID,
}

# Trailing type casts such as ``::text`` (PostgreSQL) or ``::timestamp without time zone``.
_PG_CAST = re.compile(r"::[a-zA-Z0-9_ \[\]]+$")
_EMPTY_CALL = re.compile(r"\(\s*\)$")


def normalize_expression(expr: str) -> str:
    """Normalize a single SQL expression token to a canonical form."""
    text = expr.strip()
    # Drop a trailing PostgreSQL cast.
    text = _PG_CAST.sub("", text).strip()
    # Strip an enclosing pair of parentheses: ``(GETDATE())`` -> ``GETDATE()``.
    while text.startswith("(") and text.endswith(")") and _balanced(text[1:-1]):
        text = text[1:-1].strip()
    upper = text.upper()
    # Reduce ``FUNC()`` to ``FUNC`` for lookup.
    lookup = _EMPTY_CALL.sub("", upper).strip()
    if lookup in _SYNONYMS:
        return _SYNONYMS[lookup]
    return upper


def _balanced(text: str) -> bool:
    """True when parentheses in ``text`` are balanced (never dips below zero)."""
    depth = 0
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0
