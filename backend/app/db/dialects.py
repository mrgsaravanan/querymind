"""Single abstraction over SQL dialect differences. Adding a dialect = adding one entry here."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DialectInfo:
    name: str            # config / admin UI name
    sqlglot_name: str    # name understood by sqlglot
    prompt_hint: str     # dialect-specific guidance injected into the generator prompt


DIALECTS: dict[str, DialectInfo] = {
    "sqlite": DialectInfo("sqlite", "sqlite",
        "SQLite: dates are ISO text. Use date(), strftime(), julianday() (e.g. julianday(b) - julianday(a) for day differences), "
        "'||' for concatenation, no DATEDIFF/DATE_TRUNC/INTERVAL/ILIKE. Window functions and CTEs are supported."),
    "postgresql": DialectInfo("postgresql", "postgres",
        "PostgreSQL: use DATE_TRUNC, EXTRACT, INTERVAL arithmetic, ILIKE, '::' casts."),
    "mysql": DialectInfo("mysql", "mysql",
        "MySQL: use DATE_FORMAT, DATEDIFF, DATE_SUB/INTERVAL, backtick-quoted identifiers."),
}


def get_dialect(name: str) -> DialectInfo:
    try:
        return DIALECTS[name]
    except KeyError:
        raise ValueError(f"Unsupported dialect {name!r}; expected one of {sorted(DIALECTS)}") from None
