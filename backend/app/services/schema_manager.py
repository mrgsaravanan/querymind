"""Schema Manager: live DB introspection merged with admin-edited descriptions and sensitive flags."""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import Engine, inspect
from sqlalchemy.orm import sessionmaker

from app.db.admin import ColumnMeta, TableMeta
from app.schemas.admin import ColumnInfo, ColumnUpdate, TableInfo, TableUpdate

DEFAULTS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "schema_descriptions.json"


class SchemaNotFoundError(LookupError):
    """Raised when an update targets a table or column that does not exist."""


class SchemaManager:
    def __init__(self, business_engine: Engine, admin_sessions: sessionmaker, defaults_path: Path = DEFAULTS_PATH):
        self._engine = business_engine
        self._sessions = admin_sessions
        self._defaults_path = defaults_path

    # ---- introspection ----
    def _introspect(self) -> dict[str, list[dict]]:
        insp = inspect(self._engine)
        out: dict[str, list[dict]] = {}
        for table in sorted(insp.get_table_names()):
            if table.startswith("sqlite_"):
                continue
            pks = set(insp.get_pk_constraint(table).get("constrained_columns") or [])
            fks = {}
            for fk in insp.get_foreign_keys(table):
                for col, ref in zip(fk["constrained_columns"], fk["referred_columns"]):
                    fks[col] = f"{fk['referred_table']}.{ref}"
            out[table] = [
                {"name": c["name"], "type": str(c["type"]), "pk": c["name"] in pks, "fk": fks.get(c["name"])}
                for c in insp.get_columns(table)
            ]
        return out

    def seed_defaults(self) -> None:
        """Insert default descriptions / sensitive flags for any table or column with no metadata yet. Never overwrites edits."""
        defaults = json.loads(self._defaults_path.read_text()) if self._defaults_path.exists() else {}
        sensitive = set(defaults.get("sensitive", []))
        with self._sessions() as s:
            for table, cols in self._introspect().items():
                if s.get(TableMeta, table) is None:
                    s.add(TableMeta(table_name=table, description=defaults.get("tables", {}).get(table, "")))
                for c in cols:
                    key = f"{table}.{c['name']}"
                    if s.get(ColumnMeta, (table, c["name"])) is None:
                        s.add(ColumnMeta(table_name=table, column_name=c["name"],
                                         description=defaults.get("columns", {}).get(key, ""),
                                         sensitive=key in sensitive))
            s.commit()

    # ---- reads ----
    def list_tables(self) -> list[TableInfo]:
        with self._sessions() as s:
            tmeta = {t.table_name: t.description for t in s.query(TableMeta)}
            cmeta = {(c.table_name, c.column_name): c for c in s.query(ColumnMeta)}
        result = []
        for table, cols in self._introspect().items():
            infos = []
            for c in cols:
                m = cmeta.get((table, c["name"]))
                infos.append(ColumnInfo(name=c["name"], type=c["type"], description=m.description if m else "",
                                        sensitive=bool(m and m.sensitive), is_primary_key=c["pk"], foreign_key=c["fk"]))
            result.append(TableInfo(name=table, description=tmeta.get(table, ""), columns=infos))
        return result

    def get_table(self, name: str) -> TableInfo:
        for t in self.list_tables():
            if t.name == name:
                return t
        raise SchemaNotFoundError(f"Unknown table {name!r}")

    def sensitive_columns(self) -> set[tuple[str, str]]:
        """Set of (table, column) pairs flagged sensitive."""
        with self._sessions() as s:
            return {(c.table_name, c.column_name) for c in s.query(ColumnMeta).filter(ColumnMeta.sensitive.is_(True))}

    def non_sensitive_tables(self) -> list[TableInfo]:
        """Schema with sensitive columns removed — the only view that may reach an LLM prompt."""
        sens = self.sensitive_columns()
        return [TableInfo(name=t.name, description=t.description,
                          columns=[c for c in t.columns if (t.name, c.name) not in sens]) for t in self.list_tables()]

    # ---- writes ----
    def update_column(self, upd: ColumnUpdate) -> ColumnInfo:
        table = self.get_table(upd.table)
        if upd.column not in {c.name for c in table.columns}:
            raise SchemaNotFoundError(f"Unknown column {upd.table}.{upd.column}")
        with self._sessions() as s:
            m = s.get(ColumnMeta, (upd.table, upd.column)) or ColumnMeta(table_name=upd.table, column_name=upd.column)
            if upd.description is not None:
                m.description = upd.description
            if upd.sensitive is not None:
                m.sensitive = upd.sensitive
            s.merge(m)
            s.commit()
        return next(c for c in self.get_table(upd.table).columns if c.name == upd.column)

    def update_table(self, upd: TableUpdate) -> TableInfo:
        self.get_table(upd.table)
        with self._sessions() as s:
            s.merge(TableMeta(table_name=upd.table, description=upd.description))
            s.commit()
        return self.get_table(upd.table)

    # ---- imported-table metadata (used by the CSV importer) ----
    def save_table_metadata(self, table: str, description: str, columns: list[tuple[str, str, bool]]) -> None:
        """Upsert table + column descriptions/sensitive flags in one transaction. ``columns`` = (name, description, sensitive)."""
        with self._sessions() as s:
            s.merge(TableMeta(table_name=table, description=description))
            for name, desc, sensitive in columns:
                s.merge(ColumnMeta(table_name=table, column_name=name, description=desc, sensitive=sensitive))
            s.commit()

    def delete_table_metadata(self, table: str) -> None:
        with self._sessions() as s:
            s.query(ColumnMeta).filter(ColumnMeta.table_name == table).delete()
            s.query(TableMeta).filter(TableMeta.table_name == table).delete()
            s.commit()
