"""Typed I/O for the Examples Retriever stage."""
from __future__ import annotations

from pydantic import BaseModel, Field

from .classifier import QueryType


class Example(BaseModel):
    question: str
    sql: str


class ExampleRecord(Example):
    """A stored example including its admin metadata."""

    id: int | None = None
    query_type: QueryType | None = None


class RetrieverInput(BaseModel):
    question: str
    top_k: int = Field(default=4, ge=3, le=5)
    query_type: QueryType | None = None


class RetrieverOutput(BaseModel):
    examples: list[Example] = Field(default_factory=list)


class ExampleSearchHit(ExampleRecord):
    score: float = 0.0
