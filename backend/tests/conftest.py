"""Shared fixtures. Everything runs offline against a freshly seeded temp business DB."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Hermetic: a developer's local backend/.env (e.g. LLM_PROVIDER=claude_cli) must never change test behaviour.
# load_dotenv() does not override variables that are already set.
os.environ.update(LLM_PROVIDER="anthropic", LLM_MODEL="claude-sonnet-4-20250514", LLM_TEMPERATURE="0.0",
                  ANTHROPIC_API_KEY="", OPENAI_API_KEY="", EMBEDDING_BACKEND="default", SEMANTIC_CACHE="true")

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "data"))

from app.config import Settings  # noqa: E402
from app.db.admin import create_admin_sessionmaker  # noqa: E402
from app.db.business import create_readonly_engine  # noqa: E402


@pytest.fixture(scope="session")
def business_db_path(tmp_path_factory) -> Path:
    import seed_db
    path = tmp_path_factory.mktemp("biz") / "business.db"
    seed_db.build(path)
    return path


@pytest.fixture()
def business_engine(business_db_path):
    return create_readonly_engine(business_db_path)


@pytest.fixture()
def admin_sessions():
    return create_admin_sessionmaker(":memory:")


@pytest.fixture()
def settings() -> Settings:
    return Settings()
