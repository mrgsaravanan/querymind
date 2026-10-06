"""Environment-driven configuration and defaults.

Runtime-editable settings (model, guardrails) live in ``admin.db`` and are managed
by the services layer; this module only holds bootstrap values and defaults.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(BACKEND_DIR.parent / ".env")


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    """Immutable bootstrap settings. Build via :func:`get_settings` (no module-level singleton)."""

    business_db_path: Path = field(default_factory=lambda: Path(_env("BUSINESS_DB_PATH", str(BACKEND_DIR / "data" / "business.db"))))
    admin_db_path: Path = field(default_factory=lambda: Path(_env("ADMIN_DB_PATH", str(BACKEND_DIR / "data" / "admin.db"))))
    chroma_path: Path = field(default_factory=lambda: Path(_env("CHROMA_PATH", str(BACKEND_DIR / "data" / "chroma"))))
    examples_seed_path: Path = field(default_factory=lambda: BACKEND_DIR / "data" / "examples_seed.json")
    cors_origins: tuple[str, ...] = field(default_factory=lambda: tuple(_env("CORS_ORIGINS", "http://localhost:3000").split(",")))

    # LLM defaults (overridable at runtime from the Model Config panel)
    default_provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "anthropic"))
    default_model: str = field(default_factory=lambda: _env("LLM_MODEL", "claude-sonnet-4-20250514"))
    default_temperature: float = field(default_factory=lambda: float(_env("LLM_TEMPERATURE", "0.0")))
    default_max_tokens: int = field(default_factory=lambda: int(_env("LLM_MAX_TOKENS", "1024")))
    default_dialect: str = field(default_factory=lambda: _env("SQL_DIALECT", "sqlite"))

    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY", ""))
    openai_api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY", ""))
    claude_cli_path: str = field(default_factory=lambda: _env("CLAUDE_CLI_PATH", "claude"))
    claude_cli_timeout: float = field(default_factory=lambda: float(_env("CLAUDE_CLI_TIMEOUT", "120")))
    ollama_base_url: str = field(default_factory=lambda: _env("OLLAMA_BASE_URL", "http://localhost:11434"))

    # Guardrail defaults
    default_max_rows: int = 100
    query_timeout_seconds: float = field(default_factory=lambda: float(_env("QUERY_TIMEOUT_SECONDS", "10")))

    # Reference "today" for relative dates in prompts (the demo dataset is anchored to this date)
    reference_date: str = field(default_factory=lambda: _env("REFERENCE_DATE", "2025-12-31"))

    # Retrieval
    retriever_top_k: int = 4
    semantic_cache_enabled: bool = field(default_factory=lambda: _env("SEMANTIC_CACHE", "true").lower() in ("1", "true", "yes"))
    semantic_cache_threshold: float = field(default_factory=lambda: float(_env("SEMANTIC_CACHE_THRESHOLD", "0.95")))
    embedding_backend: str = field(default_factory=lambda: _env("EMBEDDING_BACKEND", "default"))


def get_settings() -> Settings:
    """Return a fresh Settings built from the current environment."""
    return Settings()
