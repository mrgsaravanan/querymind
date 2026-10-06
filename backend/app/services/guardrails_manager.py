"""Guardrails Manager: persisted, hot-reloaded guardrail config."""
from __future__ import annotations

from sqlalchemy.orm import sessionmaker

from app.db.admin import KeyValue
from app.schemas.validator import GuardrailConfig

KEY = "guardrails"


class GuardrailsManager:
    def __init__(self, admin_sessions: sessionmaker, default_max_rows: int = 100):
        self._sessions = admin_sessions
        self._default = GuardrailConfig(max_rows=default_max_rows)

    def get(self) -> GuardrailConfig:
        """Read on every call so admin changes apply to the next request without a restart."""
        with self._sessions() as s:
            row = s.get(KeyValue, KEY)
            return GuardrailConfig.model_validate_json(row.value) if row else self._default.model_copy()

    def update(self, cfg: GuardrailConfig) -> GuardrailConfig:
        with self._sessions() as s:
            s.merge(KeyValue(key=KEY, value=cfg.model_dump_json()))
            s.commit()
        return cfg
