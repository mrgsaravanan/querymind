import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas.admin import QueryRequest, QueryStatus
from app.schemas.validator import GuardrailConfig
from app.services.semantic_cache import SemanticCache, context_hash, rows_signature
from app.services.embeddings import HashingEmbeddingFunction
from tests.fakes import ScriptedLLM

CLS = json.dumps({"query_type": "SELECT_AGGREGATE", "tables_mentioned": ["orders"], "columns_mentioned": []})
SQL = "SELECT status, COUNT(*) AS n FROM orders GROUP BY status ORDER BY n DESC"


def gen(sql=SQL):
    return json.dumps({"sql": sql, "explanation": "Counts orders per status."})


@pytest.fixture()
def make(tmp_path, business_db_path):
    def _make(llm, **kw):
        st = Settings(business_db_path=business_db_path, admin_db_path=tmp_path / "a.db", chroma_path=tmp_path / "c",
                      embedding_backend="hashing", **kw)
        app = create_app(st, llm_factory=lambda cfg: llm)
        return app, app.state.container
    return _make


# ---------------- multi-dialect ----------------
def test_transpile_to_other_dialect(make):
    llm = ScriptedLLM(CLS, gen("SELECT strftime('%Y-%m', order_date) AS m, COUNT(*) AS n FROM orders GROUP BY m"), "ok")
    app, _ = make(llm)
    body = TestClient(app).post("/query", json={"question": "orders per month", "target_dialect": "postgresql"}).json()
    assert body["status"] == "success" and body["target_dialect"] == "postgresql"
    assert body["transpiled_sql"] and "strftime" not in body["transpiled_sql"].lower()   # rewritten, not copied
    assert "strftime" in body["sql"].lower()                                              # executed SQL unchanged


def test_transpile_noop_and_validation(make):
    app, _ = make(ScriptedLLM(CLS, gen(), "ok"))
    c = TestClient(app)
    assert c.post("/query", json={"question": "orders per status"}).json()["transpiled_sql"] is None
    assert c.post("/query", json={"question": "orders per status", "target_dialect": "sqlite"}).json()["transpiled_sql"] is None
    assert c.post("/query", json={"question": "x", "target_dialect": "oracle"}).status_code == 422


# ---------------- semantic cache ----------------
def test_cache_unit():
    cache = SemanticCache(None, HashingEmbeddingFunction(), 0.9, collection="unit_cache_1")
    ctx = context_hash({"a": 1})
    cache.put("How many orders per status?", ctx, sql="SELECT 1", explanation="e", query_type="SELECT_AGGREGATE", summary="s", signature="x")
    assert cache.get("how many   orders per status?", ctx).sql == "SELECT 1"      # normalisation
    assert cache.get("completely unrelated astronomy question", ctx) is None
    assert cache.get("How many orders per status?", context_hash({"a": 2})) is None  # different context = miss
    assert rows_signature([[1]]) == rows_signature([[1]]) != rows_signature([[2]])
    cache.clear()
    assert cache.count() == 0


def test_repeated_question_hits_cache_and_spends_no_sql_tokens(make):
    llm = ScriptedLLM(CLS, gen(), "Most are delivered.")
    _, c = make(llm)
    first = c.orchestrator.run(QueryRequest(question="How many orders are there per status?"))
    assert first.status is QueryStatus.SUCCESS and not first.cached
    n_calls = len(llm.calls)
    second = c.orchestrator.run(QueryRequest(question="how many orders are there per status"))
    assert second.cached and second.status is QueryStatus.SUCCESS and second.table.rows == first.table.rows
    assert len(llm.calls) == n_calls                                  # zero LLM calls: same data, summary reused
    assert second.nl_summary == "Most are delivered." and second.sql == first.sql and "classify" not in second.stage_timings_ms
    assert c.logs.list()[0].status == "success"                       # cache hits are still logged


def test_cache_miss_for_different_question(make):
    llm = ScriptedLLM(CLS, gen(), "ok")
    _, c = make(llm)
    c.orchestrator.run(QueryRequest(question="How many orders are there per status?"))
    r = c.orchestrator.run(QueryRequest(question="Which payment method is the most popular overall?"))
    assert not r.cached


def test_cache_respects_guardrail_and_sensitivity_changes(make):
    llm = ScriptedLLM(CLS, gen("SELECT id FROM orders"), "ok")
    _, c = make(llm)
    q = QueryRequest(question="List some order ids please")
    assert c.orchestrator.run(q).row_count == 100
    assert c.orchestrator.run(q).cached
    c.guardrails.update(GuardrailConfig(max_rows=5))                  # context changed -> old entry unusable
    r = c.orchestrator.run(q)
    assert not r.cached and r.row_count == 5


def test_cached_sql_is_revalidated_every_time(make):
    llm = ScriptedLLM(CLS, gen("SELECT id, total_amount FROM orders"), "ok")
    _, c = make(llm)
    q = QueryRequest(question="Show order ids with their totals")
    assert c.orchestrator.run(q).status is QueryStatus.SUCCESS
    # an admin now flags total_amount sensitive; the cached SQL must NOT bypass that
    from app.schemas.admin import ColumnUpdate
    c.schema.update_column(ColumnUpdate(table="orders", column="total_amount", sensitive=True))
    llm.queues["generator"] = [gen("SELECT id FROM orders")]
    r = c.orchestrator.run(q)
    assert not r.cached and "total_amount" not in (r.sql or "")


def test_clarification_bypasses_cache(make):
    llm = ScriptedLLM(CLS, gen(), "ok")
    _, c = make(llm)
    c.orchestrator.run(QueryRequest(question="orders per status please"))
    r = c.orchestrator.run(QueryRequest(question="orders per status please", clarification="Interpret x as y"))
    assert not r.cached


def test_cache_can_be_disabled(make):
    llm = ScriptedLLM(CLS, gen(), "ok")
    _, c = make(llm, semantic_cache_enabled=False)
    c.orchestrator.run(QueryRequest(question="orders per status please"))
    assert not c.orchestrator.run(QueryRequest(question="orders per status please")).cached
