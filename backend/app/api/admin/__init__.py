"""Admin API: mounted under /admin by app.main."""
from fastapi import APIRouter

from . import config, examples, guardrails, logs, schema, tables

router = APIRouter()
for _m in (schema, tables, examples, logs, guardrails, config):
    router.include_router(_m.router)
