from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.deps import Container, get_container
from app.schemas.admin import ModelConfig
from app.services.config_manager import ConfigValidationError

router = APIRouter(prefix="/config", tags=["admin: model config"])


@router.get("", response_model=ModelConfig)
def get_config(c: Container = Depends(get_container)):
    return c.config.get()


@router.put("", response_model=ModelConfig)
def put_config(cfg: ModelConfig, c: Container = Depends(get_container)):
    try:
        return c.config.update(cfg)
    except ConfigValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
