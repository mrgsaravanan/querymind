"""Config Manager: persisted model/provider/dialect settings."""
from __future__ import annotations

from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db.admin import KeyValue
from app.schemas.admin import ModelConfig

KEY = "model_config"
PROVIDERS = {"anthropic", "openai", "ollama", "claude_cli"}
DIALECTS = {"sqlite", "postgresql", "mysql"}


class ConfigValidationError(ValueError):
    pass


class ConfigManager:
    def __init__(self, admin_sessions: sessionmaker, settings: Settings):
        self._sessions = admin_sessions
        self._default = ModelConfig(provider=settings.default_provider, model=settings.default_model,
                                    temperature=settings.default_temperature, dialect=settings.default_dialect,
                                    max_tokens=settings.default_max_tokens)

    def get(self) -> ModelConfig:
        with self._sessions() as s:
            row = s.get(KeyValue, KEY)
            return ModelConfig.model_validate_json(row.value) if row else self._default.model_copy()

    def update(self, cfg: ModelConfig) -> ModelConfig:
        if cfg.provider not in PROVIDERS:
            raise ConfigValidationError(f"provider must be one of {sorted(PROVIDERS)}")
        if cfg.dialect not in DIALECTS:
            raise ConfigValidationError(f"dialect must be one of {sorted(DIALECTS)}")
        if not cfg.model.strip():
            raise ConfigValidationError("model must not be empty")
        with self._sessions() as s:
            s.merge(KeyValue(key=KEY, value=cfg.model_dump_json()))
            s.commit()
        return cfg
