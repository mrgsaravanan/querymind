"""SQL Executor: runs validated SQL on a read-only connection with a timeout. Never leaks raw DB errors."""
from __future__ import annotations

import logging
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.schemas.executor import ExecutorInput, ExecutorOutput

log = logging.getLogger(__name__)

HARD_ROW_CAP = 10_000  # backstop in case a caller bypasses the validator's LIMIT


def _jsonable(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return "<binary>"
    return v


class SQLExecutor:
    def __init__(self, readonly_engine: Engine, default_timeout_seconds: float = 10.0):
        self._engine = readonly_engine
        self._timeout = default_timeout_seconds

    def execute(self, inp: ExecutorInput) -> ExecutorOutput:
        timeout = inp.timeout_seconds or self._timeout
        start = time.perf_counter()
        timed_out = {"flag": False}
        raw = None
        try:
            with self._engine.connect() as conn:
                raw = conn.connection.dbapi_connection
                if self._engine.dialect.name == "sqlite" and hasattr(raw, "set_progress_handler"):
                    deadline = time.monotonic() + timeout

                    def _abort() -> int:
                        if time.monotonic() > deadline:
                            timed_out["flag"] = True
                            return 1
                        return 0

                    raw.set_progress_handler(_abort, 10_000)
                result = conn.execute(text(inp.sql))
                if not result.returns_rows:
                    return ExecutorOutput(latency_ms=self._ms(start), error="The query did not return any data.")
                columns = list(result.keys())
                rows = [[_jsonable(v) for v in r] for r in result.fetchmany(HARD_ROW_CAP)]
            return ExecutorOutput(columns=columns, rows=rows, row_count=len(rows), latency_ms=self._ms(start))
        except DBAPIError as e:
            return self._error(e, start, timed_out["flag"])
        except Exception as e:  # noqa: BLE001 - nothing raw may reach the client
            return self._error(e, start, timed_out["flag"])
        finally:
            # The connection returns to the pool: a stale deadline would abort whoever reuses it later.
            if raw is not None and hasattr(raw, "set_progress_handler"):
                try:
                    raw.set_progress_handler(None, 0)
                except Exception:  # noqa: BLE001
                    log.debug("could not clear progress handler", exc_info=True)

    def _error(self, e: Exception, start: float, timed_out: bool) -> ExecutorOutput:
        detail = str(getattr(e, "orig", e))
        log.error("query execution failed: %s | %s", type(e).__name__, detail)
        low = detail.lower()
        if timed_out or "interrupted" in low:
            msg = "The query took too long and was stopped. Try narrowing the question."
        elif "readonly" in low or "read-only" in low or "read only" in low:
            msg = "This query tried to modify data, which is not allowed."
        else:
            msg = "The database could not run this query."
        return ExecutorOutput(latency_ms=self._ms(start), error=msg, detail=detail)

    @staticmethod
    def _ms(start: float) -> float:
        return round((time.perf_counter() - start) * 1000, 2)
