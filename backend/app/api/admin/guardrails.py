from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import Container, get_container
from app.schemas.validator import GuardrailConfig

router = APIRouter(prefix="/guardrails", tags=["admin: guardrails"])


@router.get("", response_model=GuardrailConfig)
def get_guardrails(c: Container = Depends(get_container)):
    return c.guardrails.get()


@router.put("", response_model=GuardrailConfig)
def put_guardrails(cfg: GuardrailConfig, c: Container = Depends(get_container)):
    return c.guardrails.update(cfg)
