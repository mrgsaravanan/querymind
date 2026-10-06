"""Typed I/O for the Query Classifier stage."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class QueryType(str, Enum):
    SELECT_SIMPLE = "SELECT_SIMPLE"
    SELECT_AGGREGATE = "SELECT_AGGREGATE"
    SELECT_JOIN = "SELECT_JOIN"
    SELECT_TEMPORAL = "SELECT_TEMPORAL"
    UNSUPPORTED = "UNSUPPORTED"


class ClassifierInput(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class ClassifierOutput(BaseModel):
    query_type: QueryType
    tables_mentioned: list[str] = Field(default_factory=list)
    columns_mentioned: list[str] = Field(default_factory=list)
    reason: str | None = Field(default=None, description="Why the query was classified UNSUPPORTED, if so.")
    friendly_message: str | None = Field(default=None, description="User-facing message for UNSUPPORTED intents.")
