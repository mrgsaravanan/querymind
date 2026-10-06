"""Typed I/O for the SQL Validator stage."""
from __future__ import annotations

from pydantic import BaseModel, Field


class GuardrailConfig(BaseModel):
    """Admin-editable guardrails (persisted in admin.db)."""

    allow_select: bool = True
    allow_insert: bool = False
    allow_update: bool = False
    allow_delete: bool = False
    allow_drop: bool = False
    allow_truncate: bool = False
    allow_alter: bool = False
    allow_create: bool = False
    max_rows: int = Field(default=100, ge=1, le=100000)
    allowed_table_prefixes: list[str] = Field(default_factory=list, description="Empty = all tables allowed.")
    allowed_schemas: list[str] = Field(default_factory=lambda: ["main"])


class ValidatorInput(BaseModel):
    sql: str
    dialect: str = "sqlite"


class ValidatorOutput(BaseModel):
    valid: bool
    sanitized_sql: str = ""
    errors: list[str] = Field(default_factory=list)
