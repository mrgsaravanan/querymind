from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.deps import Container, get_container
from app.pipeline.sql_validator import SQLValidator
from app.schemas.admin import ExampleIn
from app.schemas.classifier import QueryType
from app.schemas.retriever import ExampleRecord, ExampleSearchHit
from app.schemas.validator import ValidatorInput
from app.services.examples_manager import ExampleNotFoundError

router = APIRouter(prefix="/examples", tags=["admin: examples"])


def _require_valid_sql(c: Container, sql: str) -> None:
    """A few-shot example with unsafe or broken SQL would teach the model bad habits; reject it up front."""
    v = SQLValidator(c.schema.list_tables, c.schema.sensitive_columns, c.guardrails.get)
    out = v.validate(ValidatorInput(sql=sql, dialect=c.config.get().dialect))
    if not out.valid:
        raise HTTPException(status_code=422, detail={"message": "Example SQL failed validation", "errors": out.errors})


@router.get("", response_model=list[ExampleRecord])
def list_examples(c: Container = Depends(get_container)):
    return c.examples.list()


@router.get("/search", response_model=list[ExampleSearchHit])
def search_examples(q: str = Query(min_length=1), k: int = Query(5, ge=1, le=20), query_type: QueryType | None = None,
                    c: Container = Depends(get_container)):
    return c.examples.search(q, k=k, query_type=query_type)


@router.post("/reindex")
def reindex(c: Container = Depends(get_container)):
    return {"indexed": c.examples.reindex()}


@router.get("/{example_id}", response_model=ExampleRecord)
def get_example(example_id: int, c: Container = Depends(get_container)):
    try:
        return c.examples.get(example_id)
    except ExampleNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("", response_model=ExampleRecord, status_code=201)
def create_example(data: ExampleIn, c: Container = Depends(get_container)):
    _require_valid_sql(c, data.sql)
    return c.examples.create(data)


@router.put("/{example_id}", response_model=ExampleRecord)
def update_example(example_id: int, data: ExampleIn, c: Container = Depends(get_container)):
    _require_valid_sql(c, data.sql)
    try:
        return c.examples.update(example_id, data)
    except ExampleNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/{example_id}", status_code=204)
def delete_example(example_id: int, c: Container = Depends(get_container)):
    try:
        c.examples.delete(example_id)
    except ExampleNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return Response(status_code=204)
