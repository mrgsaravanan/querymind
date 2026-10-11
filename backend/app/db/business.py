"""Read-only access to the business database."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine


def create_readonly_engine(db_path: Path | str, dialect: str = "sqlite", url: str | None = None) -> Engine:
    """Build a read-only engine for the business DB.

    SQLite: opened with ``mode=ro`` so the *database layer* rejects writes even if
    the validator is bypassed. Postgres/MySQL: pass ``url`` for a read-only role.
    """
    if dialect == "sqlite":
        uri = f"file:{Path(db_path).resolve()}?mode=ro&uri=true"
        return create_engine(f"sqlite+pysqlite:///{uri}", connect_args={"uri": True}, future=True)
    if not url:
        raise ValueError(f"A connection url (read-only role) is required for dialect {dialect!r}")
    return create_engine(url, future=True)


def create_write_engine(db_path: Path | str) -> Engine:
    """Read-WRITE SQLite engine. Used ONLY by the admin CSV importer; the query path never touches it."""
    return create_engine(f"sqlite+pysqlite:///{Path(db_path).resolve()}", connect_args={"timeout": 15}, future=True)
