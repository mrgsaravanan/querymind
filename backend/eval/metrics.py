"""Evaluation metrics: result-set comparison (Execution Accuracy) and SQL comparison (Exact Match)."""
from __future__ import annotations

from typing import Any, Sequence

import sqlglot
from sqlglot import diff, exp
from sqlglot.diff import Keep


def normalize_value(v: Any) -> Any:
    """Types/rounding normalised so 5, 5.0 and 5.000001 compare equal; strings are trimmed."""
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    return str(v).strip()


def normalize_rows(rows: Sequence[Sequence[Any]], ordered: bool) -> list[tuple]:
    out = [tuple(normalize_value(v) for v in r) for r in rows]
    return out if ordered else sorted(out, key=lambda t: tuple((x is None, str(x)) for x in t))


def results_match(generated: Sequence[Sequence[Any]], expected: Sequence[Sequence[Any]], ordered: bool = False) -> bool:
    """Exact row match (column aliases ignored, column order significant). Row order only matters if ``ordered``."""
    return normalize_rows(generated, ordered) == normalize_rows(expected, ordered)


def _parse(sql: str, dialect: str) -> exp.Expression:
    return sqlglot.parse_one(sql.strip().rstrip(";"), read=dialect)


def normalize_sql(sql: str, dialect: str = "sqlite", injected_limit: int | None = None) -> str:
    """Canonical text: parsed and re-rendered (case, spacing, comments gone). A LIMIT equal to the
    guardrail's auto-appended ``injected_limit`` is dropped so it doesn't count against the model."""
    tree = _parse(sql, dialect)
    limit = tree.args.get("limit")
    if injected_limit is not None and limit is not None and isinstance(limit.expression, exp.Literal) \
            and limit.expression.is_int and int(limit.expression.this) == injected_limit:
        tree.set("limit", None)
    return tree.sql(dialect=dialect, normalize=True, comments=False)


def sql_exact(generated: str, expected: str, dialect: str = "sqlite", injected_limit: int | None = None) -> bool:
    try:
        return normalize_sql(generated, dialect, injected_limit) == normalize_sql(expected, dialect)
    except sqlglot.errors.SqlglotError:
        return False


def sql_semantic(generated: str, expected: str, dialect: str = "sqlite", injected_limit: int | None = None) -> bool:
    """True if ``sqlglot.diff`` finds no edits between the two ASTs (all nodes 'Keep')."""
    try:
        g = _parse(normalize_sql(generated, dialect, injected_limit), dialect)
        e = _parse(normalize_sql(expected, dialect), dialect)
        return all(isinstance(edit, Keep) for edit in diff(g, e))
    except sqlglot.errors.SqlglotError:
        return False


def sql_match(generated: str | None, expected: str, dialect: str = "sqlite", injected_limit: int | None = None) -> tuple[bool, bool]:
    """(exact_text_match, semantic_match) - semantic is True whenever exact is."""
    if not generated:
        return False, False
    exact = sql_exact(generated, expected, dialect, injected_limit)
    return exact, exact or sql_semantic(generated, expected, dialect, injected_limit)
