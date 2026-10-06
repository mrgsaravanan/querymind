"""Typed I/O for the SQL Executor stage."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ExecutorInput(BaseModel):
    sql: str
    timeout_seconds: float | None = None


class ExecutorOutput(BaseModel):
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    row_count: int = 0
    latency_ms: float = 0.0
    error: str | None = Field(default=None, description="Safe, user-presentable error message.")
    detail: str | None = Field(default=None, exclude=True, description="Raw DB error; internal use only (self-healing retry), never serialized.")
