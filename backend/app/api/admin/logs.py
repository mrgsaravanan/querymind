from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.deps import Container, get_container
from app.schemas.admin import QueryLogEntry

router = APIRouter(prefix="/logs", tags=["admin: logs"])


@router.get("", response_model=list[QueryLogEntry])
def list_logs(status: str | None = None, q: str | None = None,
              date_from: datetime | None = Query(None, alias="from"), date_to: datetime | None = Query(None, alias="to"),
              limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0), c: Container = Depends(get_container)):
    return c.logs.list(status=status, q=q, date_from=date_from, date_to=date_to, limit=limit, offset=offset)


@router.get("/export")
def export_logs(format: str = "csv", status: str | None = None, q: str | None = None,
                date_from: datetime | None = Query(None, alias="from"), date_to: datetime | None = Query(None, alias="to"),
                c: Container = Depends(get_container)):
    if format != "csv":
        raise HTTPException(status_code=400, detail="Only format=csv is supported")
    body = c.logs.export_csv(status=status, q=q, date_from=date_from, date_to=date_to)
    return Response(content=body, media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="query_logs.csv"'})
