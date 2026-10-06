"""Orchestrator: wires the stages, handles the validator retry and self-healing, times each stage, always logs."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date
from typing import Callable

import sqlglot
from sqlalchemy import Engine

from app.config import Settings
from app.db.dialects import get_dialect
from app.llm.base import LLMError, LLMProvider
from app.pipeline.classifier import QueryClassifier
from app.pipeline.examples_retriever import ExamplesRetriever
from app.pipeline.result_formatter import ResultFormatter
from app.pipeline.schema_linker import SchemaLinker
from app.pipeline.sql_executor import SQLExecutor
from app.pipeline.sql_generator import GenerationError, SQLGenerator
from app.pipeline.sql_validator import SQLValidator
from app.schemas.admin import ModelConfig, QueryRequest, QueryResponse, QueryStatus, TableInfo
from app.schemas.classifier import ClassifierInput, QueryType
from app.schemas.executor import ExecutorInput
from app.schemas.formatter import FormatterInput
from app.schemas.generator import GeneratorInput
from app.schemas.linker import LinkerInput
from app.schemas.retriever import RetrieverInput
from app.schemas.validator import ValidatorInput
from app.services.config_manager import ConfigManager
from app.services.guardrails_manager import GuardrailsManager
from app.services.log_service import LogService
from app.services.schema_manager import SchemaManager
from app.services.semantic_cache import SemanticCache, context_hash, rows_signature
from app.services.vector_store import ExampleVectorStore

log = logging.getLogger(__name__)

MSG_VALIDATION = "I couldn't produce a safe, valid query for that question. Try rephrasing it or being more specific."
MSG_EXECUTION = "The query couldn't be run against the database. Try rephrasing the question."
MSG_LLM = "The language model is currently unavailable or not configured. Please check the Model Config, API key or Claude login."
MSG_INTERNAL = "Something went wrong while answering that question. Please try again."

LLMFactory = Callable[[ModelConfig], LLMProvider]


class _LazyLLM:
    """Builds the provider on first use, so requests that never need the LLM (e.g. keyword-blocked destructive
    intent) still get answered when no API key is configured."""

    def __init__(self, factory: LLMFactory, cfg: ModelConfig):
        self._factory, self._cfg, self._llm = factory, cfg, None
        self.model, self.temperature, self.max_tokens = cfg.model, cfg.temperature, cfg.max_tokens

    def complete(self, system: str, user: str, *, max_tokens: int | None = None) -> str:
        if self._llm is None:
            self._llm = self._factory(self._cfg)
        return self._llm.complete(system, user, max_tokens=max_tokens)


@dataclass
class _Run:
    """Mutable per-request state."""
    question: str
    started: float
    timings: dict[str, float]
    query_type: QueryType | None = None
    sql: str | None = None


class QueryOrchestrator:
    def __init__(self, *, schema_manager: SchemaManager, guardrails: GuardrailsManager, config: ConfigManager,
                 logs: LogService, vector_store: ExampleVectorStore, readonly_engine: Engine, llm_factory: LLMFactory,
                 settings: Settings, domain_notes: str = "", self_heal: bool = True, summarize: bool = True,
                 cache: SemanticCache | None = None):
        self._schema, self._guardrails, self._config, self._logs = schema_manager, guardrails, config, logs
        self._store, self._engine, self._llm_factory = vector_store, readonly_engine, llm_factory
        self._settings, self._notes, self._self_heal = settings, domain_notes, self_heal
        self._summarize = summarize
        self._cache = cache

    # ------------------------------------------------------------------ public
    def run(self, req: QueryRequest) -> QueryResponse:
        run = _Run(question=req.question, started=time.perf_counter(), timings={})
        try:
            resp = self._run(req, run)
        except LLMError as e:
            log.error("LLM unavailable: %s", e)
            resp = self._finish(run, QueryStatus.ERROR, message=MSG_LLM, error=str(e))
        except Exception as e:  # noqa: BLE001 - a request must always produce a typed response and a log row
            log.exception("unhandled pipeline error")
            resp = self._finish(run, QueryStatus.ERROR, message=MSG_INTERNAL, error=f"{type(e).__name__}: {e}")
        return resp

    # ------------------------------------------------------------------ pipeline
    def _run(self, req: QueryRequest, run: _Run) -> QueryResponse:
        cfg = self._config.get()
        llm = _LazyLLM(self._llm_factory, cfg)

        # one consistent snapshot of schema/guardrails per request (admin edits apply on the next request)
        all_tables = self._schema.list_tables()
        sensitive = self._schema.sensitive_columns()
        safe_tables = [TableInfo(name=t.name, description=t.description,
                                 columns=[c for c in t.columns if (t.name, c.name) not in sensitive]) for t in all_tables]
        guard = self._guardrails.get()
        sensitive_names = sorted({c for _, c in sensitive})

        classifier = QueryClassifier(llm, lambda: safe_tables)
        linker = SchemaLinker(lambda: safe_tables)
        retriever = ExamplesRetriever(self._store)
        generator = SQLGenerator(llm, lambda: safe_tables, date.fromisoformat(self._settings.reference_date), self._notes)
        validator = SQLValidator(lambda: all_tables, lambda: sensitive, lambda: guard)
        executor = SQLExecutor(self._engine, self._settings.query_timeout_seconds)
        formatter = ResultFormatter(llm, summarize=self._summarize)

        ctx = None
        if self._cache is not None and not req.clarification:
            ctx = context_hash(cfg.model_dump(), guard.model_dump(), sorted(sensitive),
                               [(t.name, [c.name for c in t.columns]) for t in all_tables])
            cached = self._from_cache(req, run, ctx, cfg, linker, validator, executor, formatter,
                                      ResultFormatter(llm, summarize=False), sensitive_names)
            if cached is not None:
                return cached

        with self._timed(run, "classify"):
            cls = classifier.classify(ClassifierInput(question=req.question))
        run.query_type = cls.query_type
        if cls.query_type is QueryType.UNSUPPORTED:
            return self._finish(run, QueryStatus.UNSUPPORTED, message=cls.friendly_message, error=cls.reason)

        with self._timed(run, "link"):
            linked = linker.link(LinkerInput(question=req.question, classification=cls))
        with self._timed(run, "retrieve"):
            examples = retriever.retrieve(RetrieverInput(question=req.question, top_k=self._settings.retriever_top_k)).examples

        gin = GeneratorInput(question=req.question, query_type=cls.query_type, linked=linked, examples=examples,
                             dialect=cfg.dialect, clarification=req.clarification)

        # generate -> validate, with exactly ONE validator-driven retry
        gen = val = None
        for attempt in (1, 2):
            with self._timed(run, "generate" if attempt == 1 else "generate_retry"):
                try:
                    gen = generator.generate(gin)
                except GenerationError as e:
                    return self._finish(run, QueryStatus.VALIDATION_FAILED, message=MSG_VALIDATION, error=str(e))
            with self._timed(run, "validate" if attempt == 1 else "validate_retry"):
                val = validator.validate(ValidatorInput(sql=gen.sql, dialect=cfg.dialect))
            if val.valid:
                break
            run.sql = gen.sql
            log.info("validation failed (attempt %d): %s", attempt, val.errors)
            gin = gin.model_copy(update={"previous_sql": gen.sql, "previous_error": "; ".join(val.errors)})
        if not val.valid:
            return self._finish(run, QueryStatus.VALIDATION_FAILED, message=MSG_VALIDATION,
                                error="; ".join(val.errors), explanation=gen.explanation)
        run.sql = val.sanitized_sql

        with self._timed(run, "execute"):
            res = executor.execute(ExecutorInput(sql=val.sanitized_sql))

        if res.error and self._self_heal:  # self-healing: one retry with the DB error injected
            healed = self._heal(run, generator, validator, executor, gin, gen.sql, res.detail or res.error, cfg.dialect)
            if healed:
                gen, val, res = healed
                run.sql = val.sanitized_sql
        if res.error:
            return self._finish(run, QueryStatus.EXECUTION_ERROR, message=MSG_EXECUTION, error=res.detail or res.error,
                                explanation=gen.explanation)

        with self._timed(run, "format"):
            out = formatter.format(FormatterInput(question=req.question, sql=val.sanitized_sql, columns=res.columns,
                                                  rows=res.rows, sensitive_columns=sensitive_names))
        if ctx is not None:  # remember this answer for near-identical future questions
            try:
                self._cache.put(req.question, ctx, sql=val.sanitized_sql, explanation=gen.explanation,
                                query_type=cls.query_type.value, summary=out.nl_summary, signature=rows_signature(res.rows))
            except Exception:  # noqa: BLE001 - the cache is an optimisation, never a failure
                log.exception("semantic cache write failed")
        return self._finish(run, QueryStatus.SUCCESS, explanation=gen.explanation, table=out.table, nl_summary=out.nl_summary,
                            row_count=res.row_count, ambiguities=linked.ambiguities, **self._transpile(val.sanitized_sql, cfg.dialect, req.target_dialect))

    def _from_cache(self, req, run, ctx, cfg, linker, validator, executor, formatter, table_formatter, sensitive_names):
        """Semantic-cache hit: skip classify/retrieve/generate (the LLM-heavy stages) but still validate + execute fresh."""
        try:
            with self._timed(run, "cache_lookup"):
                hit = self._cache.get(req.question, ctx)
            if hit is None:
                return None
            val = validator.validate(ValidatorInput(sql=hit.sql, dialect=cfg.dialect))
            if not val.valid:
                return None
            with self._timed(run, "execute"):
                res = executor.execute(ExecutorInput(sql=val.sanitized_sql))
            if res.error:
                return None
            fin = FormatterInput(question=req.question, sql=val.sanitized_sql, columns=res.columns, rows=res.rows,
                                 sensitive_columns=sensitive_names)
            with self._timed(run, "format"):
                if rows_signature(res.rows) == hit.signature and hit.summary:
                    out = table_formatter.format(fin)
                    summary = hit.summary
                else:  # data changed since it was cached: regenerate the prose
                    out = formatter.format(fin)
                    summary = out.nl_summary
            linked = linker.link(LinkerInput(question=req.question))
            run.query_type = QueryType(hit.query_type) if hit.query_type else None
            run.sql = val.sanitized_sql
            return self._finish(run, QueryStatus.SUCCESS, explanation=hit.explanation, table=out.table, nl_summary=summary,
                                row_count=res.row_count, ambiguities=linked.ambiguities, cached=True,
                                **self._transpile(val.sanitized_sql, cfg.dialect, req.target_dialect))
        except Exception:  # noqa: BLE001 - any cache trouble falls back to the full pipeline
            log.exception("semantic cache lookup failed; using full pipeline")
            return None

    @staticmethod
    def _transpile(sql: str, source: str, target: str | None) -> dict:
        """Best-effort rewrite for display in another dialect (execution always uses the configured dialect)."""
        if not target or target == source:
            return {}
        try:
            out = sqlglot.transpile(sql, read=get_dialect(source).sqlglot_name, write=get_dialect(target).sqlglot_name)[0]
            return {"transpiled_sql": out, "target_dialect": target}
        except Exception:  # noqa: BLE001
            log.warning("could not transpile %s -> %s", source, target)
            return {"target_dialect": target}

    def _heal(self, run, generator, validator, executor, gin, bad_sql, detail, dialect):
        """Returns (gen, val, res) only if the corrected query validates AND executes cleanly."""
        try:
            with self._timed(run, "heal"):
                gen = generator.generate(gin.model_copy(update={"previous_sql": bad_sql, "previous_error": detail}))
                val = validator.validate(ValidatorInput(sql=gen.sql, dialect=dialect))
                if not val.valid:
                    return None
                res = executor.execute(ExecutorInput(sql=val.sanitized_sql))
            return (gen, val, res) if not res.error else None
        except (GenerationError, LLMError):
            return None

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _timed(run: _Run, name: str):
        class _T:
            def __enter__(self_inner):
                self_inner.t = time.perf_counter()

            def __exit__(self_inner, *exc):
                run.timings[name] = round(run.timings.get(name, 0) + (time.perf_counter() - self_inner.t) * 1000, 2)
                return False
        return _T()

    def _finish(self, run: _Run, status: QueryStatus, *, message: str | None = None, error: str | None = None,
                explanation: str | None = None, table=None, nl_summary: str | None = None, row_count: int = 0,
                ambiguities=None, **extra) -> QueryResponse:
        latency = round((time.perf_counter() - run.started) * 1000, 2)
        log_id = None
        try:
            log_id = self._logs.add(question=run.question, status=status.value,
                                    query_type=run.query_type.value if run.query_type else None, sql=run.sql, error=error,
                                    latency_ms=latency, row_count=row_count, stage_timings=run.timings)
        except Exception:  # noqa: BLE001 - logging must never break the answer
            log.exception("failed to write query log")
        return QueryResponse(status=status, question=run.question, query_type=run.query_type, sql=run.sql,
                             explanation=explanation, table=table, nl_summary=nl_summary, latency_ms=latency,
                             row_count=row_count, ambiguities=ambiguities or [], message=message,
                             stage_timings_ms=run.timings, log_id=log_id, **extra)
