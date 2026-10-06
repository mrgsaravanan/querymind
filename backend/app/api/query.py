from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.deps import Container, get_container
from app.schemas.admin import QueryRequest, QueryResponse, QueryStatus

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponse)
def query(req: QueryRequest, c: Container = Depends(get_container)):
    """NL question -> SQL -> result. Handled outcomes (unsupported, validation failure, ...) return 200 with a
    typed ``status``; only infrastructure failures (LLM unavailable, internal error) return 503."""
    resp = c.orchestrator.run(req)
    if resp.status is QueryStatus.ERROR:
        return JSONResponse(status_code=503, content=resp.model_dump(mode="json"))
    return resp
