"""Typed I/O for the SQL Generator stage."""
from __future__ import annotations

from pydantic import BaseModel, Field

from .classifier import QueryType
from .linker import LinkerOutput
from .retriever import Example


class GeneratorInput(BaseModel):
    question: str
    query_type: QueryType | None = None
    linked: LinkerOutput = Field(default_factory=LinkerOutput)
    examples: list[Example] = Field(default_factory=list)
    dialect: str = "sqlite"
    previous_sql: str | None = None
    previous_error: str | None = None
    clarification: str | None = Field(default=None, description="User-chosen resolution for an ambiguity, e.g. 'revenue = orders.total_amount'.")


class GeneratorOutput(BaseModel):
    sql: str
    explanation: str = ""
