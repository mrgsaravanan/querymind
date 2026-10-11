"""Typed models for the CSV table importer."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .admin import TableInfo

ColumnType = Literal["INTEGER", "REAL", "TEXT", "DATE", "DATETIME"]


class PreviewColumn(BaseModel):
    original_name: str
    name: str = Field(description="Suggested safe SQL identifier.")
    type: ColumnType
    sample_values: list[str] = Field(default_factory=list)
    null_count: int = 0
    suggested_description: str = ""
    suggested_sensitive: bool = False
    sensitive_reason: str | None = None


class PreviewResponse(BaseModel):
    filename: str
    suggested_table_name: str
    suggested_table_description: str = ""
    delimiter: str
    encoding: str
    row_count: int
    columns: list[PreviewColumn]
    sample_rows: list[list[str | None]]
    warnings: list[str] = Field(default_factory=list)
    name_conflict: bool = False
    can_replace: bool = False


class ImportColumn(BaseModel):
    original_name: str
    name: str
    type: ColumnType
    description: str = Field(default="", max_length=500)
    sensitive: bool = False


class ImportConfig(BaseModel):
    table_name: str
    description: str = Field(default="", max_length=500)
    mode: Literal["create", "replace"] = "create"
    columns: list[ImportColumn] = Field(min_length=1)


class ImportResult(BaseModel):
    table: TableInfo
    rows_imported: int
    replaced: bool = False


class ImportedTableInfo(BaseModel):
    table_name: str
    source_filename: str
    row_count: int
    created_at: datetime
