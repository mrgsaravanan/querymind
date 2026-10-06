"""Typed I/O for the Result Formatter stage."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TableData(BaseModel):
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)


class FormatterInput(BaseModel):
    question: str
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    sensitive_columns: list[str] = Field(default_factory=list, description="Column names never sent to the LLM.")


class FormatterOutput(BaseModel):
    table: TableData
    nl_summary: str
