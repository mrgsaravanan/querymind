import json
from pathlib import Path

import pytest

from app.pipeline.examples_retriever import ExamplesRetriever
from app.pipeline.schema_linker import SchemaLinker
from app.schemas.admin import ExampleIn
from app.schemas.classifier import ClassifierOutput, QueryType
from app.schemas.linker import LinkerInput
from app.schemas.retriever import RetrieverInput
from app.services.embeddings import HashingEmbeddingFunction
from app.services.examples_manager import ExampleNotFoundError, ExamplesManager
from app.services.schema_manager import SchemaManager
from app.services.vector_store import ExampleVectorStore

SEED = Path(__file__).resolve().parent.parent / "data" / "examples_seed.json"


@pytest.fixture()
def sm(business_engine, admin_sessions):
    m = SchemaManager(business_engine, admin_sessions)
    m.seed_defaults()
    return m


@pytest.fixture()
def mgr(admin_sessions):
    import uuid
    store = ExampleVectorStore(None, HashingEmbeddingFunction(), collection=f"t_{uuid.uuid4().hex}")
    return ExamplesManager(admin_sessions, store)


# ---------- linker ----------
def test_linker_resolves_synonyms_and_flags_revenue_ambiguity(sm):
    out = SchemaLinker(sm.non_sensitive_tables).link(LinkerInput(question="What was the total revenue by customer country?"))
    cols = {c.qualified for c in out.resolved_columns}
    assert {"orders.total_amount", "order_items.line_total", "customers.country"} <= cols
    amb = next(a for a in out.ambiguities if a.term == "revenue")
    assert set(amb.candidates) == {"orders.total_amount", "order_items.line_total"} and amb.reason
    assert "customers" in out.resolved_tables


def test_linker_no_ambiguity_for_unambiguous_question(sm):
    out = SchemaLinker(sm.non_sensitive_tables).link(LinkerInput(question="average rating of products"))
    assert out.ambiguities == [] and "reviews.rating" in {c.qualified for c in out.resolved_columns}


def test_linker_excludes_sensitive_columns(sm):
    clf = ClassifierOutput(query_type=QueryType.SELECT_SIMPLE, tables_mentioned=["customers"],
                           columns_mentioned=["customers.email", "email", "phone"])
    out = SchemaLinker(sm.non_sensitive_tables).link(LinkerInput(question="show customer email and phone number", classification=clf))
    blob = out.model_dump_json()
    assert "email" not in blob and "phone" not in blob and "customers" in out.resolved_tables


def test_linker_generic_names_need_their_table(sm):
    out = SchemaLinker(sm.non_sensitive_tables).link(LinkerInput(question="list product name and price"))
    cols = {c.qualified for c in out.resolved_columns}
    assert "products.name" in cols and "customers.name" not in cols and "categories.name" not in cols


# ---------- examples manager / retriever ----------
def test_seed_library_size_and_idempotency(mgr):
    assert mgr.seed_from_file(SEED) >= 30
    assert mgr.seed_from_file(SEED) == 0
    assert mgr.in_sync() and len(mgr.list()) >= 30
    types = {e.query_type for e in mgr.list()}
    assert types == {QueryType.SELECT_SIMPLE, QueryType.SELECT_AGGREGATE, QueryType.SELECT_JOIN, QueryType.SELECT_TEMPORAL}


def test_seed_sql_all_executes(business_db_path):
    import sqlite3
    db = sqlite3.connect(f"file:{business_db_path}?mode=ro", uri=True)
    for ex in json.loads(SEED.read_text()):
        db.execute(ex["sql"]).fetchall()


def test_crud_keeps_index_in_sync(mgr):
    a = mgr.create(ExampleIn(question="How many cancelled orders are there?", sql="SELECT COUNT(*) FROM orders WHERE status='cancelled'", query_type=QueryType.SELECT_AGGREGATE))
    mgr.create(ExampleIn(question="List all product categories", sql="SELECT name FROM categories", query_type=QueryType.SELECT_SIMPLE))
    assert mgr.in_sync()
    assert mgr.search("count of cancelled orders", k=1)[0].id == a.id
    # edit re-embeds
    mgr.update(a.id, ExampleIn(question="Average shipping delay in days", sql="SELECT 1", query_type=QueryType.SELECT_TEMPORAL))
    assert mgr.search("shipping delay days", k=1)[0].id == a.id
    assert mgr.search("shipping delay days", k=1, query_type=QueryType.SELECT_TEMPORAL)[0].id == a.id
    # delete removes
    mgr.delete(a.id)
    assert mgr.in_sync() and a.id not in {h.id for h in mgr.search("shipping delay days", k=5)}
    with pytest.raises(ExampleNotFoundError):
        mgr.delete(a.id)


def test_reindex_repairs_drift(mgr):
    mgr.seed_from_file(SEED)
    mgr._store.reset()
    assert not mgr.in_sync()
    mgr.reindex()
    assert mgr.in_sync()


def test_retriever_top_k_and_type_fill(mgr):
    mgr.seed_from_file(SEED)
    r = ExamplesRetriever(mgr._store)
    out = r.retrieve(RetrieverInput(question="total revenue by product category"))
    assert len(out.examples) == 4 and "category" in out.examples[0].question.lower()
    assert len(r.retrieve(RetrieverInput(question="orders last quarter", top_k=5, query_type=QueryType.SELECT_TEMPORAL)).examples) == 5
    # a type with fewer matches than k is filled from the unfiltered ranking
    mgr.delete(next(e.id for e in mgr.list() if e.query_type == QueryType.SELECT_JOIN))
    only_one = ExampleVectorStore(None, HashingEmbeddingFunction(), collection="t_single")
    only_one.upsert(1, "customers per country", "SELECT 1", "SELECT_AGGREGATE")
    only_one.upsert(2, "list categories", "SELECT 2", "SELECT_SIMPLE")
    only_one.upsert(3, "order status counts", "SELECT 3", "SELECT_SIMPLE")
    only_one.upsert(4, "cheap products", "SELECT 4", "SELECT_SIMPLE")
    assert len(ExamplesRetriever(only_one).retrieve(RetrieverInput(question="x", query_type=QueryType.SELECT_AGGREGATE)).examples) == 4
