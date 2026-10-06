from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.deps import Container, get_container
from app.schemas.admin import SchemaUpdateRequest, TableInfo
from app.services.schema_manager import SchemaNotFoundError

router = APIRouter(prefix="/schema", tags=["admin: schema"])


@router.get("", response_model=list[TableInfo])
def get_schema(c: Container = Depends(get_container)):
    return c.schema.list_tables()


@router.put("", response_model=list[TableInfo])
def update_schema(req: SchemaUpdateRequest, c: Container = Depends(get_container)):
    """Update table/column descriptions and toggle the sensitive flag. All-or-nothing on unknown targets."""
    try:
        for t in req.tables:
            c.schema.get_table(t.table)
        for col in req.columns:
            if col.column not in {x.name for x in c.schema.get_table(col.table).columns}:
                raise SchemaNotFoundError(f"Unknown column {col.table}.{col.column}")
        for t in req.tables:
            c.schema.update_table(t)
        for col in req.columns:
            c.schema.update_column(col)
    except SchemaNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return c.schema.list_tables()
