"""Application container: builds every service once, with dependencies injected (no module-level globals)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from fastapi import Request
from sqlalchemy.orm import sessionmaker

from app.config import Settings, get_settings
from app.db.admin import create_admin_sessionmaker
from app.db.business import create_readonly_engine, create_write_engine
from app.llm import create_llm
from app.pipeline.orchestrator import LLMFactory, QueryOrchestrator
from app.services.config_manager import ConfigManager
from app.services.embeddings import create_embedding_function
from app.services.examples_manager import ExamplesManager
from app.services.guardrails_manager import GuardrailsManager
from app.services.log_service import LogService
from app.services.schema_manager import SchemaManager
from app.services.semantic_cache import SemanticCache
from app.services.table_importer import TableImporter
from app.services.vector_store import ExampleVectorStore

log = logging.getLogger(__name__)
NOTES_PATH = Path(__file__).resolve().parent.parent / "data" / "domain_notes.md"


@dataclass
class Container:
    settings: Settings
    admin_sessions: sessionmaker
    business_engine: object
    schema: SchemaManager
    guardrails: GuardrailsManager
    config: ConfigManager
    logs: LogService
    vector_store: ExampleVectorStore
    examples: ExamplesManager
    orchestrator: QueryOrchestrator
    table_importer: TableImporter | None = None


def build_container(settings: Settings | None = None, llm_factory: LLMFactory | None = None,
                    notes_path: Path = NOTES_PATH, summarize: bool = True) -> Container:
    st = settings or get_settings()
    sessions = create_admin_sessionmaker(st.admin_db_path)
    engine = create_readonly_engine(st.business_db_path)
    store = ExampleVectorStore(st.chroma_path, create_embedding_function(st.embedding_backend))
    schema = SchemaManager(engine, sessions)
    guardrails = GuardrailsManager(sessions, st.default_max_rows)
    config = ConfigManager(sessions, st)
    logs = LogService(sessions)
    examples = ExamplesManager(sessions, store)
    try:
        schema.seed_defaults()
    except Exception:  # noqa: BLE001 - e.g. business DB not seeded yet; /health will report it
        log.exception("could not introspect business DB at startup (run `make seed`)")
    if not examples.list() and st.examples_seed_path.exists():
        log.info("seeding %d example(s)", examples.seed_from_file(st.examples_seed_path))
    elif not examples.in_sync():
        log.warning("example index out of sync with admin.db; reindexing")
        examples.reindex()
    cache = SemanticCache(st.chroma_path, create_embedding_function(st.embedding_backend), st.semantic_cache_threshold) \
        if st.semantic_cache_enabled else None
    orchestrator = QueryOrchestrator(
        schema_manager=schema, guardrails=guardrails, config=config, logs=logs, vector_store=store,
        readonly_engine=engine, llm_factory=llm_factory or (lambda cfg: create_llm(cfg, st)), settings=st,
        domain_notes=notes_path.read_text() if notes_path.exists() else "", summarize=summarize, cache=cache)
    importer = TableImporter(create_write_engine(st.business_db_path), sessions, schema, max_rows=st.import_max_rows) \
        if st.allow_table_import else None
    return Container(st, sessions, engine, schema, guardrails, config, logs, store, examples, orchestrator, importer)


def get_container(request: Request) -> Container:
    return request.app.state.container
