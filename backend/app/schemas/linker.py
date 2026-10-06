"""Typed I/O for the Schema Linker stage."""
from __future__ import annotations

from pydantic import BaseModel, Field

from .classifier import ClassifierOutput


class ColumnRef(BaseModel):
    table: str
    column: str
    type: str = ""
    description: str = ""

    @property
    def qualified(self) -> str:
        return f"{self.table}.{self.column}"


class Ambiguity(BaseModel):
    term: str = Field(description="The phrase in the question that is ambiguous, e.g. 'revenue'.")
    candidates: list[str] = Field(description="Qualified candidate columns, e.g. ['orders.total_amount', 'order_items.line_total'].")
    reason: str = ""


class LinkerInput(BaseModel):
    question: str
    classification: ClassifierOutput | None = None


class LinkerOutput(BaseModel):
    resolved_tables: list[str] = Field(default_factory=list)
    resolved_columns: list[ColumnRef] = Field(default_factory=list)
    ambiguities: list[Ambiguity] = Field(default_factory=list)
