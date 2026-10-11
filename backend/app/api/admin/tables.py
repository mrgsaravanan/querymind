"""Admin: add tables to the business database from CSV files (preview, then import)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from app.deps import Container, get_container
from app.schemas.tables import ImportConfig, ImportedTableInfo, ImportResult, PreviewResponse
from app.services.table_importer import (ImportConflictError, ImportNotFoundError, ImportValidationError, TableImporter)

router = APIRouter(prefix="/tables", tags=["admin: tables"])


def get_importer(c: Container = Depends(get_container)) -> TableImporter:
    if c.table_importer is None:
        raise HTTPException(status_code=403, detail="Table import is disabled on this server (ALLOW_TABLE_IMPORT=false).")
    return c.table_importer


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status_code=413, detail=f"File too large; the limit is {limit // (1024 * 1024)} MB.")
    return data


def _bad(e: ImportValidationError) -> HTTPException:
    return HTTPException(status_code=422, detail={"message": str(e), "errors": e.details})


@router.post("/preview", response_model=PreviewResponse)
async def preview(file: UploadFile = File(...), c: Container = Depends(get_container), imp: TableImporter = Depends(get_importer)):
    data = await _read_limited(file, c.settings.import_max_bytes)
    try:
        return imp.preview(file.filename or "table.csv", data)
    except ImportValidationError as e:
        raise _bad(e) from e


@router.post("/import", response_model=ImportResult, status_code=201)
async def import_table(file: UploadFile = File(...), config: str = Form(...), c: Container = Depends(get_container),
                       imp: TableImporter = Depends(get_importer)):
    try:
        cfg = ImportConfig.model_validate_json(config)
    except (ValidationError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=422, detail={"message": "Invalid import configuration", "errors": [str(e).splitlines()[0]]}) from e
    data = await _read_limited(file, c.settings.import_max_bytes)
    try:
        return imp.import_table(file.filename or "table.csv", data, cfg)
    except ImportValidationError as e:
        raise _bad(e) from e
    except ImportConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.get("/imported", response_model=list[ImportedTableInfo])
def list_imported(imp: TableImporter = Depends(get_importer)):
    return imp.list_imported()


@router.delete("/{table_name}", status_code=204)
def delete_imported(table_name: str, imp: TableImporter = Depends(get_importer)):
    try:
        imp.delete(table_name)
    except ImportNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
