"""Typed request/response models for the Admin API and the /query endpoint."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .classifier import QueryType
from .formatter import TableData
from .linker import Ambiguity
from .validator import GuardrailConfig  # re-exported for the API layer

__all__ = ["GuardrailConfig"]


class QueryStatus(str, Enum):
    SUCCESS = "success"
    UNSUPPORTED = "unsupported"
    VALIDATION_FAILED = "validation_failed"
    EXECUTION_ERROR = "execution_error"
    NEEDS_CLARIFICATION = "needs_clarification"
    ERROR = "error"


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    clarification: str | None = None
    target_dialect: str | None = Field(default=None, description="If set, the response also carries the SQL transpiled to this dialect.")

    @field_validator("target_dialect")
    @classmethod
    def _known_dialect(cls, v: str | None) -> str | None:
        from app.db.dialects import DIALECTS
        if v is not None and v not in DIALECTS:
            raise ValueError(f"target_dialect must be one of {sorted(DIALECTS)}")
        return v


class QueryResponse(BaseModel):
    status: QueryStatus
    question: str
    query_type: QueryType | None = None
    sql: str | None = None
    explanation: str | None = None
    table: TableData | None = None
    nl_summary: str | None = None
    latency_ms: float = 0.0
    row_count: int = 0
    ambiguities: list[Ambiguity] = Field(default_factory=list)
    message: str | None = Field(default=None, description="Friendly error / clarification message.")
    stage_timings_ms: dict[str, float] = Field(default_factory=dict)
    log_id: int | None = None
    transpiled_sql: str | None = Field(default=None, description="``sql`` rewritten for ``target_dialect`` (best effort; not executed).")
    target_dialect: str | None = None
    cached: bool = Field(default=False, description="True if the SQL came from the semantic cache (no LLM tokens spent on SQL).")


# ---- schema manager ----
class ColumnInfo(BaseModel):
    name: str
    type: str
    description: str = ""
    sensitive: bool = False
    is_primary_key: bool = False
    foreign_key: str | None = None


class TableInfo(BaseModel):
    name: str
    description: str = ""
    columns: list[ColumnInfo]


class ColumnUpdate(BaseModel):
    table: str
    column: str
    description: str | None = None
    sensitive: bool | None = None


class TableUpdate(BaseModel):
    table: str
    description: str


# ---- examples ----
class ExampleIn(BaseModel):
    question: str = Field(min_length=3)
    sql: str = Field(min_length=3)
    query_type: QueryType | None = None


# ---- model config ----
class ModelConfig(BaseModel):
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    dialect: str = "sqlite"
    max_tokens: int = Field(default=1024, ge=64, le=8192)


# ---- logs ----
class QueryLogEntry(BaseModel):
    id: int
    created_at: datetime
    question: str
    query_type: str | None = None
    sql: str | None = None
    status: str
    error: str | None = None
    latency_ms: float = 0.0
    row_count: int = 0
    stage_timings_ms: dict[str, float] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: str
    detail: Any | None = None


class SchemaUpdateRequest(BaseModel):
    """Batch edit of table/column descriptions and sensitive flags."""

    tables: list[TableUpdate] = Field(default_factory=list)
    columns: list[ColumnUpdate] = Field(default_factory=list)
