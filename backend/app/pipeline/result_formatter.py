"""Result Formatter: table + 1-2 sentence natural-language summary from a truncated, non-sensitive sample."""
from __future__ import annotations

import json
import logging

from app.llm.base import LLMError, LLMProvider
from app.schemas.formatter import FormatterInput, FormatterOutput, TableData

log = logging.getLogger(__name__)

SAMPLE_ROWS = 10
SAMPLE_CHARS = 2500
EMPTY_MESSAGE = "No rows matched your question. Try widening the filters or date range."

SYSTEM_PROMPT = ("You summarize SQL query results for business users in 1-2 plain sentences. "
                 "Use only numbers and names present in the data shown; never invent values. "
                 "If only a sample of rows is shown, say 'top' or 'for example' rather than implying it is everything. "
                 "No markdown, no SQL, no preamble.")


class ResultFormatter:
    def __init__(self, llm: LLMProvider, summarize: bool = True):
        self._llm = llm
        self._summarize_enabled = summarize

    def format(self, inp: FormatterInput) -> FormatterOutput:
        keep = [i for i, c in enumerate(inp.columns) if c not in set(inp.sensitive_columns)]
        columns = [inp.columns[i] for i in keep]
        rows = [[r[i] for i in keep] for r in inp.rows]
        table = TableData(columns=columns, rows=rows)
        if not rows:
            return FormatterOutput(table=table, nl_summary=EMPTY_MESSAGE)
        if not self._summarize_enabled:
            return FormatterOutput(table=table, nl_summary="")
        return FormatterOutput(table=table, nl_summary=self._summarize(inp.question, inp.sql, columns, rows))

    def _summarize(self, question: str, sql: str, columns: list[str], rows: list[list]) -> str:
        sample = [dict(zip(columns, r)) for r in rows[:SAMPLE_ROWS]]
        payload = json.dumps(sample, default=str)[:SAMPLE_CHARS]
        user = (f"Question: {question}\nSQL: {sql}\nTotal rows returned: {len(rows)} "
                f"(showing {min(len(rows), SAMPLE_ROWS)})\nData: {payload}")
        try:
            text = self._llm.complete(SYSTEM_PROMPT, user, max_tokens=200).strip()
            if text:
                return text
        except LLMError as e:
            log.warning("summary LLM failed: %s", e)
        return self._fallback(rows)

    @staticmethod
    def _fallback(rows: list[list]) -> str:
        if len(rows) == 1 and len(rows[0]) == 1:
            return f"The result is {rows[0][0]}."
        return f"The query returned {len(rows)} row{'s' if len(rows) != 1 else ''}."
