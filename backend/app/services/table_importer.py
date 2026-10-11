"""CSV table importer: analyse a CSV (types, names, likely-PII columns) and load it into the business database.

Security model
- Stateless: the file is parsed in memory on every call; nothing is written to disk except the final table.
- All identifiers are validated against a strict pattern and must parse as plain columns in BOTH SQLite and sqlglot
  (the app runs generated SQL through both), so they are safe to interpolate (double-quoted) into DDL.
- All values go through parameterised ``executemany``; nothing from the file is ever interpolated into SQL.
- Uses its own read-write engine. The query path keeps its ``mode=ro`` connection, so questions still cannot write.
- Only tables created by this importer (tracked in ``imported_tables``) can be replaced or dropped, never seeded tables.
"""
from __future__ import annotations

import csv
import io
import logging
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path

import sqlglot
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker
from sqlglot import exp

from app.db.admin import ImportedTable
from app.schemas.tables import (ColumnType, ImportColumn, ImportConfig, ImportedTableInfo, ImportResult, PreviewColumn,
                                PreviewResponse)
from app.services.schema_manager import SchemaManager

log = logging.getLogger(__name__)

MAX_COLS = 100
MAX_CELL_CHARS = 10_000
IDENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_INT_RE = re.compile(r"^-?(0|[1-9]\d{0,17})$")
_REAL_RE = re.compile(r"^-?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")
_LEADING_ZERO_RE = re.compile(r"^-?0\d+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")
_NON_ISO_DATE_RE = re.compile(r"^\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?[\d][\d\s().-]{7,}$")
_SSN_RE = re.compile(r"^\d{3}-\d{2}-\d{4}$")
_SENSITIVE_NAME_RE = re.compile(
    r"(e_?mail|phone|mobile|telephone|\bssn\b|aadhaar|aadhar|passport|passw(or)?d|secret|token|api_?key|credit_?card|"
    r"card_?(no|num)|iban|\bdob\b|birth|address)", re.I)


class ImportValidationError(ValueError):
    """The CSV or the import configuration is invalid (maps to HTTP 422)."""

    def __init__(self, message: str, details: list[str] | None = None):
        super().__init__(message)
        self.details = details or []


class ImportConflictError(RuntimeError):
    """The target table already exists and may not be replaced (maps to HTTP 409)."""


class ImportNotFoundError(LookupError):
    pass


# ----------------------------------------------------------------------------------------------- parsing
class CsvData:
    def __init__(self, header: list[str], rows: list[list[str | None]], delimiter: str, encoding: str, warnings: list[str]):
        self.header, self.rows, self.delimiter, self.encoding, self.warnings = header, rows, delimiter, encoding, warnings


def detect_delimiter(text_data: str) -> str:
    """Pick the delimiter that splits the first rows into the same number (>1) of fields most consistently.
    (csv.Sniffer is unreliable on small files.) Ties and single-column files fall back to a comma."""
    lines = [ln for ln in text_data.splitlines()[:12] if ln.strip()]
    best, best_score = ",", (0, 0)
    for d in (",", ";", "\t", "|"):
        counts = [len(r) for r in csv.reader(lines, delimiter=d)]
        if not counts or counts[0] < 2:
            continue
        score = (sum(1 for c in counts if c == counts[0]), counts[0])
        if score > best_score:
            best, best_score = d, score
    return best


def parse_csv(data: bytes, max_rows: int) -> CsvData:
    if not data.strip():
        raise ImportValidationError("The file is empty.")
    warnings: list[str] = []
    try:
        text_data, encoding = data.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        text_data, encoding = data.decode("cp1252", errors="replace"), "cp1252"
        warnings.append("The file is not UTF-8; it was read as Windows-1252, so some characters may look different.")
    delimiter = detect_delimiter(text_data)
    reader = csv.reader(io.StringIO(text_data, newline=""), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        raise ImportValidationError("The file has no header row.") from None
    while header and header[-1].strip() == "":
        header.pop()
    if not header:
        raise ImportValidationError("The header row is empty.")
    if len(header) > MAX_COLS:
        raise ImportValidationError(f"Too many columns ({len(header)}); the limit is {MAX_COLS}.")
    rows: list[list[str | None]] = []
    problems: list[str] = []
    for line_no, raw in enumerate(reader, start=2):
        if not any(c.strip() for c in raw):
            continue  # blank line
        while len(raw) > len(header) and raw[-1].strip() == "":
            raw.pop()
        if len(raw) > len(header):
            problems.append(f"line {line_no} has {len(raw)} fields but the header has {len(header)}")
            if len(problems) >= 5:
                break
            continue
        row: list[str | None] = []
        for c in raw + [""] * (len(header) - len(raw)):
            c = c.strip()
            if len(c) > MAX_CELL_CHARS:
                problems.append(f"line {line_no} has a cell longer than {MAX_CELL_CHARS} characters")
                c = c[:MAX_CELL_CHARS]
            row.append(c if c != "" else None)
        rows.append(row)
        if len(rows) > max_rows:
            raise ImportValidationError(f"Too many rows; the limit is {max_rows:,}.")
    if problems:
        raise ImportValidationError("The CSV is malformed.", problems)
    if not rows:
        raise ImportValidationError("The file has a header but no data rows.")
    return CsvData(header, rows, delimiter, encoding, warnings)


# ----------------------------------------------------------------------------------------------- inference
def _is_iso_datetime(v: str) -> bool:
    if not _DATETIME_RE.match(v):
        return False
    try:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _is_iso_date(v: str) -> bool:
    if not _DATE_RE.match(v):
        return False
    try:
        date.fromisoformat(v)
        return True
    except ValueError:
        return False


def infer_type(values: list[str | None]) -> ColumnType:
    vs = [v for v in values if v is not None]
    if not vs:
        return "TEXT"
    if all(_INT_RE.match(v) for v in vs):
        return "INTEGER"
    # REAL needs a decimal point/exponent (or a valid int). Leading zeros (zip codes, padded ids) and huge digit
    # strings (account numbers that would lose precision as floats) stay TEXT.
    if all(_REAL_RE.match(v) and not _LEADING_ZERO_RE.match(v) and (_INT_RE.match(v) or re.search(r"[.eE]", v)) for v in vs):
        return "REAL"
    if all(_is_iso_date(v) for v in vs):
        return "DATE"
    if all(_is_iso_datetime(v) for v in vs):
        return "DATETIME"
    return "TEXT"


def coerce(value: str | None, type_: ColumnType):
    """Convert a CSV cell to the Python value stored in SQLite. Raises ValueError with a short reason."""
    if value is None:
        return None
    if type_ == "INTEGER":
        if not _INT_RE.match(value):
            raise ValueError("not a whole number")
        return int(value)
    if type_ == "REAL":
        if not _REAL_RE.match(value):
            raise ValueError("not a number")
        return float(value)
    if type_ == "DATE":
        if not _is_iso_date(value):
            raise ValueError("not an ISO date (YYYY-MM-DD)")
    if type_ == "DATETIME":
        if not _is_iso_datetime(value):
            raise ValueError("not an ISO date-time (YYYY-MM-DD HH:MM[:SS])")
    return value


def _safe_in_both_parsers(name: str) -> bool:
    """True if ``name`` works unquoted as a column name in SQLite *and* in sqlglot (reserved words fail one or both)."""
    try:
        con = sqlite3.connect(":memory:")
        con.execute(f"CREATE TABLE _p ({name} TEXT)")
        con.execute(f"SELECT {name}, _p.{name} FROM _p WHERE {name} IS NOT NULL ORDER BY {name}").fetchall()
        con.close()
        t = sqlglot.parse_one(f"SELECT {name} FROM _p WHERE {name} IS NOT NULL ORDER BY {name}", read="sqlite")
        cols = list(t.find_all(exp.Column))
    except Exception:  # noqa: BLE001 - any failure means "not safe"
        return False
    return len(cols) == 3 and all(c.name == name and not c.table for c in cols)


def sanitize_identifier(raw: str, taken: set[str], fallback: str) -> str:
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", raw.strip())   # CamelCase -> camel_case
    s = re.sub(r"[^0-9a-zA-Z]+", "_", s).strip("_").lower()
    s = s or fallback
    if s[0].isdigit():
        s = "c_" + s
    if s.startswith("sqlite_"):
        s = "x_" + s
    s = s[:60]
    base = s if _safe_in_both_parsers(s) else f"{s}_col"
    s, i = base, 2
    while s in taken:
        s, i = f"{base}_{i}", i + 1
    return s


def validate_identifier(name: str, what: str) -> None:
    if not IDENT_RE.match(name):
        raise ImportValidationError(f"{what} '{name}' is invalid: use lowercase letters, digits and underscores, starting with a letter (max 63).")
    if name.startswith("sqlite_") or not _safe_in_both_parsers(name):
        raise ImportValidationError(f"{what} '{name}' is a reserved word or cannot be used safely; choose another name.")


def humanize(name: str) -> str:
    s = re.sub(r"[_\s]+", " ", name).strip()
    return (s[:1].upper() + s[1:]) if s else s


def suggest_sensitive(original: str, name: str, type_: ColumnType, values: list[str | None]) -> str | None:
    """Return a human-readable reason if the column looks like PII, else None. A suggestion only; the admin decides."""
    if _SENSITIVE_NAME_RE.search(original) or _SENSITIVE_NAME_RE.search(name):
        return "the column name suggests personal or secret data"
    sample = [v for v in values if v is not None][:200]
    if len(sample) < 3:
        return None
    share = lambda pred: sum(1 for v in sample if pred(v)) / len(sample)  # noqa: E731
    if share(lambda v: bool(_EMAIL_RE.match(v))) >= 0.6:
        return "values look like email addresses"
    if share(lambda v: bool(_SSN_RE.match(v))) >= 0.6:
        return "values look like national ID numbers"
    if type_ == "TEXT" and share(lambda v: bool(_PHONE_RE.match(v)) and sum(c.isdigit() for c in v) >= 8 and bool(re.search(r"[+\s().-]", v))) >= 0.6:
        return "values look like phone numbers"
    return None


# ----------------------------------------------------------------------------------------------- service
class TableImporter:
    def __init__(self, write_engine: Engine, admin_sessions: sessionmaker, schema: SchemaManager, *, max_rows: int = 100_000):
        self._engine, self._sessions, self._schema, self._max_rows = write_engine, admin_sessions, schema, max_rows

    # -- helpers
    def _existing_tables(self) -> set[str]:
        return {t.name for t in self._schema.list_tables()}

    def _imported_names(self) -> set[str]:
        with self._sessions() as s:
            return {r.table_name for r in s.query(ImportedTable)}

    # -- step 1: analyse
    def preview(self, filename: str, data: bytes) -> PreviewResponse:
        csv_data = parse_csv(data, self._max_rows)
        existing = self._existing_tables()
        stem = Path(filename or "table").stem
        table_name = sanitize_identifier(stem, set(), "imported_table")
        taken_cols: set[str] = set()
        columns: list[PreviewColumn] = []
        warnings = list(csv_data.warnings)
        for i, original in enumerate(csv_data.header):
            values = [r[i] for r in csv_data.rows]
            name = sanitize_identifier(original, taken_cols, f"column_{i + 1}")
            taken_cols.add(name)
            type_ = infer_type(values)
            reason = suggest_sensitive(original, name, type_, values)
            non_null = [v for v in values if v is not None]
            if type_ == "TEXT" and non_null and sum(bool(_NON_ISO_DATE_RE.match(v)) for v in non_null) / len(non_null) >= 0.8:
                warnings.append(f"Column '{original}' looks like dates in a non-ISO format. Date questions (last month, per quarter) "
                                "only work with YYYY-MM-DD; reformat it in your spreadsheet and re-upload.")
            desc = humanize(name) + ("" if type_ == "TEXT" else f" ({type_.lower()})") + "."
            columns.append(PreviewColumn(original_name=original, name=name, type=type_, sample_values=list(dict.fromkeys(non_null))[:4],
                                         null_count=len(values) - len(non_null), suggested_description=desc,
                                         suggested_sensitive=reason is not None, sensitive_reason=reason))
        if any(c.original_name != c.name for c in columns):
            warnings.append("Some column names were rewritten into safe SQL names (lowercase, underscores). You can edit them below.")
        conflict = table_name in existing
        return PreviewResponse(filename=filename, suggested_table_name=table_name,
                               suggested_table_description=humanize(re.sub(r"[_\s]+", " ", stem)) + " (imported from CSV).",
                               delimiter="\\t" if csv_data.delimiter == "\t" else csv_data.delimiter, encoding=csv_data.encoding,
                               row_count=len(csv_data.rows), columns=columns,
                               sample_rows=[r for r in csv_data.rows[:5]], warnings=warnings,
                               name_conflict=conflict, can_replace=conflict and table_name in self._imported_names())

    # -- step 2: import
    def import_table(self, filename: str, data: bytes, cfg: ImportConfig) -> ImportResult:
        csv_data = parse_csv(data, self._max_rows)
        self._validate_config(cfg, csv_data)
        existing, imported = self._existing_tables(), self._imported_names()
        replacing = cfg.table_name in existing
        if replacing and (cfg.mode != "replace" or cfg.table_name not in imported):
            why = ("it is part of the original database and cannot be replaced" if cfg.table_name not in imported
                   else "choose 'replace' to overwrite it")
            raise ImportConflictError(f"Table '{cfg.table_name}' already exists: {why}.")
        if cfg.mode == "replace" and not replacing:
            raise ImportValidationError(f"Cannot replace '{cfg.table_name}': no such imported table.")

        index = {h: i for i, h in enumerate(csv_data.header)}
        order = [index[c.original_name] for c in cfg.columns]
        records, errors = [], []
        for n, row in enumerate(csv_data.rows, start=2):
            rec = []
            for c, src in zip(cfg.columns, order):
                try:
                    rec.append(coerce(row[src], c.type))
                except ValueError as e:
                    if len(errors) < 5:
                        errors.append(f"line {n}, column '{c.original_name}': '{row[src]}' is {e} (type {c.type}); change the type to TEXT or fix the data")
            records.append(tuple(rec))
        if errors:
            raise ImportValidationError("Some values do not match the chosen column types.", errors)

        cols_sql = ", ".join(f'"{c.name}" {c.type}' for c in cfg.columns)
        placeholders = ", ".join("?" for _ in cfg.columns)
        insert_sql = f'INSERT INTO "{cfg.table_name}" ({", ".join(chr(34) + c.name + chr(34) for c in cfg.columns)}) VALUES ({placeholders})'
        with self._engine.begin() as conn:  # one transaction: all or nothing
            if replacing:
                conn.exec_driver_sql(f'DROP TABLE "{cfg.table_name}"')
            conn.exec_driver_sql(f'CREATE TABLE "{cfg.table_name}" ({cols_sql})')
            for i in range(0, len(records), 1000):
                conn.exec_driver_sql(insert_sql, records[i : i + 1000])

        try:
            if replacing:
                self._schema.delete_table_metadata(cfg.table_name)  # drop stale column notes from the old version
            self._schema.save_table_metadata(cfg.table_name, cfg.description, [(c.name, c.description, c.sensitive) for c in cfg.columns])
            with self._sessions() as s:
                s.merge(ImportedTable(table_name=cfg.table_name, source_filename=filename or "", row_count=len(records)))
                s.commit()
        except Exception:  # noqa: BLE001 - keep data and metadata consistent
            log.exception("metadata save failed; rolling back table %s", cfg.table_name)
            with self._engine.begin() as conn:
                conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{cfg.table_name}"')
            raise
        log.info("imported %s (%d rows) from %s", cfg.table_name, len(records), filename)
        return ImportResult(table=self._schema.get_table(cfg.table_name), rows_imported=len(records), replaced=replacing)

    def _validate_config(self, cfg: ImportConfig, csv_data: CsvData) -> None:
        validate_identifier(cfg.table_name, "Table name")
        header = set(csv_data.header)
        names: set[str] = set()
        seen_src: set[str] = set()
        for c in cfg.columns:
            validate_identifier(c.name, "Column name")
            if c.name in names:
                raise ImportValidationError(f"Duplicate column name '{c.name}'.")
            names.add(c.name)
            if c.original_name not in header:
                raise ImportValidationError(f"Column '{c.original_name}' is not in the uploaded file; re-upload and preview again.")
            if c.original_name in seen_src:
                raise ImportValidationError(f"Column '{c.original_name}' is mapped twice.")
            seen_src.add(c.original_name)
        if len(csv_data.header) != len(set(csv_data.header)):
            raise ImportValidationError("The header row contains duplicate column names; rename them in the file.")

    # -- list / drop
    def list_imported(self) -> list[ImportedTableInfo]:
        with self._sessions() as s:
            return [ImportedTableInfo(table_name=r.table_name, source_filename=r.source_filename, row_count=r.row_count,
                                      created_at=r.created_at) for r in s.query(ImportedTable).order_by(ImportedTable.created_at.desc())]

    def delete(self, table_name: str) -> None:
        """Drop an imported table and its metadata. Seeded tables are protected."""
        if table_name not in self._imported_names():
            raise ImportNotFoundError(f"'{table_name}' is not an imported table (original tables cannot be deleted here).")
        validate_identifier(table_name, "Table name")
        with self._engine.begin() as conn:
            conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{table_name}"')
        self._schema.delete_table_metadata(table_name)
        with self._sessions() as s:
            s.query(ImportedTable).filter(ImportedTable.table_name == table_name).delete()
            s.commit()
