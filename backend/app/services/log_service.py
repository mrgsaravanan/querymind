"""Query log persistence, filtering and CSV export."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import sessionmaker

from app.db.admin import QueryLog
from app.schemas.admin import QueryLogEntry

CSV_FIELDS = ["id", "created_at", "question", "query_type", "sql", "status", "error", "latency_ms", "row_count"]


class LogService:
    def __init__(self, admin_sessions: sessionmaker):
        self._sessions = admin_sessions

    def add(self, *, question: str, status: str, query_type: str | None = None, sql: str | None = None,
            error: str | None = None, latency_ms: float = 0.0, row_count: int = 0,
            stage_timings: dict[str, float] | None = None) -> int:
        with self._sessions() as s:
            row = QueryLog(question=question, status=status, query_type=query_type, sql=sql, error=error,
                           latency_ms=latency_ms, row_count=row_count, stage_timings=json.dumps(stage_timings or {}))
            s.add(row)
            s.commit()
            return row.id

    def _filtered(self, status, q, date_from, date_to):
        stmt = select(QueryLog).order_by(QueryLog.id.desc())
        if status:
            stmt = stmt.where(QueryLog.status == status)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(or_(QueryLog.question.ilike(like), QueryLog.sql.ilike(like)))
        if date_from:
            stmt = stmt.where(QueryLog.created_at >= date_from)
        if date_to:
            stmt = stmt.where(QueryLog.created_at <= date_to)
        return stmt

    @staticmethod
    def _to_entry(r: QueryLog) -> QueryLogEntry:
        return QueryLogEntry(id=r.id, created_at=r.created_at, question=r.question, query_type=r.query_type, sql=r.sql,
                             status=r.status, error=r.error, latency_ms=r.latency_ms, row_count=r.row_count,
                             stage_timings_ms=json.loads(r.stage_timings or "{}"))

    def list(self, *, status: str | None = None, q: str | None = None, date_from: datetime | None = None,
             date_to: datetime | None = None, limit: int = 100, offset: int = 0) -> list[QueryLogEntry]:
        with self._sessions() as s:
            rows = s.scalars(self._filtered(status, q, date_from, date_to).limit(limit).offset(offset)).all()
            return [self._to_entry(r) for r in rows]

    def export_csv(self, **filters) -> str:
        entries = self.list(limit=100000, **filters)
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=CSV_FIELDS)
        w.writeheader()
        for e in entries:
            w.writerow({k: getattr(e, k) for k in CSV_FIELDS})
        return buf.getvalue()
