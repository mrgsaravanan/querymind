from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.deps import Container, get_container
from app.schemas.admin import QueryRequest, QueryResponse, QueryStatus
from app.services.rate_limit import RateLimitExceeded, client_ip

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponse)
def query(req: QueryRequest, request: Request, c: Container = Depends(get_container)):
    """NL question -> SQL -> result. Handled outcomes (unsupported, validation failure, ...) return 200 with a
    typed ``status``; only infrastructure failures (LLM unavailable, internal error) return 503."""
    who = client_ip(request.headers.get("x-forwarded-for"), request.client.host if request.client else None,
                    c.settings.rate_limit_proxy_hops)
    try:
        c.rate_limiter.check(who)
    except RateLimitExceeded as e:
        return JSONResponse(status_code=429, headers={"Retry-After": str(e.retry_after)},
                            content={"error": str(e), "detail": {"retry_after_seconds": e.retry_after}})
    resp = c.orchestrator.run(req)
    if resp.status is QueryStatus.ERROR:
        return JSONResponse(status_code=503, content=resp.model_dump(mode="json"))
    return resp
