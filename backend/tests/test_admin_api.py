import csv
import io
import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.fakes import ScriptedLLM

GOOD_SQL = "SELECT name FROM categories ORDER BY name"


def settings(tmp_path, business_db_path):
    return Settings(business_db_path=business_db_path, admin_db_path=tmp_path / "admin.db", chroma_path=tmp_path / "chroma",
                    embedding_backend="hashing")


@pytest.fixture()
def env(tmp_path, business_db_path):
    llm = ScriptedLLM(json.dumps({"query_type": "SELECT_SIMPLE", "tables_mentioned": [], "columns_mentioned": []}),
                      json.dumps({"sql": "SELECT id FROM orders", "explanation": "e"}), "ok")
    seen = []
    app = create_app(settings(tmp_path, business_db_path), llm_factory=lambda cfg: (seen.append(cfg), llm)[1])
    return TestClient(app), seen, tmp_path, business_db_path


@pytest.fixture()
def client(env):
    return env[0]


# ---------------- schema ----------------
def test_schema_get_and_update_persist(env):
    client, _, tmp_path, biz = env
    tables = client.get("/admin/schema").json()
    assert len(tables) == 7
    cust = next(t for t in tables if t["name"] == "customers")
    assert next(c for c in cust["columns"] if c["name"] == "email")["sensitive"] is True
    r = client.put("/admin/schema", json={"tables": [{"table": "orders", "description": "Orders!"}],
                                          "columns": [{"table": "customers", "column": "country", "description": "Nation", "sensitive": True}]})
    assert r.status_code == 200
    # persistence: a brand-new app instance on the same admin.db sees the edits
    again = TestClient(create_app(settings(tmp_path, biz))).get("/admin/schema").json()
    assert next(t for t in again if t["name"] == "orders")["description"] == "Orders!"
    country = next(c for t in again if t["name"] == "customers" for c in t["columns"] if c["name"] == "country")
    assert country["description"] == "Nation" and country["sensitive"] is True


def test_schema_update_unknown_is_404_and_atomic(client):
    r = client.put("/admin/schema", json={"tables": [{"table": "orders", "description": "changed"}],
                                          "columns": [{"table": "orders", "column": "ghost", "description": "x"}]})
    assert r.status_code == 404 and r.json()["error"]
    assert next(t for t in client.get("/admin/schema").json() if t["name"] == "orders")["description"] != "changed"


def test_toggling_sensitive_takes_effect_on_next_query(client):
    client.put("/admin/schema", json={"columns": [{"table": "orders", "column": "total_amount", "sensitive": True}]})
    # the very next validation (hot reload) must reject the now-sensitive column
    from app.pipeline.sql_validator import SQLValidator
    from app.schemas.validator import ValidatorInput
    c = client.app.state.container
    out = SQLValidator(c.schema.list_tables, c.schema.sensitive_columns, c.guardrails.get).validate(
        ValidatorInput(sql="SELECT total_amount FROM orders"))
    assert not out.valid and "sensitive" in out.errors[0]


# ---------------- examples ----------------
def test_examples_crud_and_index_sync(client):
    base = client.get("/admin/examples").json()
    assert len(base) >= 41
    c = client.app.state.container
    r = client.post("/admin/examples", json={"question": "List category names alphabetically", "sql": GOOD_SQL, "query_type": "SELECT_SIMPLE"})
    assert r.status_code == 201
    new = r.json()
    assert client.get(f"/admin/examples/{new['id']}").json()["sql"] == GOOD_SQL
    assert c.examples.in_sync()
    hits = client.get("/admin/examples/search", params={"q": "category names alphabetically", "k": 1}).json()
    assert hits[0]["id"] == new["id"] and 0 < hits[0]["score"] <= 1

    u = client.put(f"/admin/examples/{new['id']}", json={"question": "Zebra crossing frequency", "sql": GOOD_SQL, "query_type": "SELECT_SIMPLE"})
    assert u.status_code == 200 and u.json()["question"] == "Zebra crossing frequency"
    assert client.get("/admin/examples/search", params={"q": "zebra crossing", "k": 1}).json()[0]["id"] == new["id"]

    assert client.delete(f"/admin/examples/{new['id']}").status_code == 204
    assert client.get(f"/admin/examples/{new['id']}").status_code == 404
    assert client.delete(f"/admin/examples/{new['id']}").status_code == 404
    assert c.examples.in_sync() and len(client.get("/admin/examples").json()) == len(base)
    ids = [h["id"] for h in client.get("/admin/examples/search", params={"q": "zebra crossing", "k": 20}).json()]
    assert new["id"] not in ids


def test_examples_reject_bad_sql_and_bad_input(client):
    for sql in ["DELETE FROM orders", "SELECT email FROM customers", "SELECT * FROM ghosts"]:
        r = client.post("/admin/examples", json={"question": "Something harmless", "sql": sql})
        assert r.status_code == 422, sql
    assert client.post("/admin/examples", json={"question": "x", "sql": GOOD_SQL}).status_code == 422
    assert client.post("/admin/examples", json={"question": "Valid question", "sql": GOOD_SQL, "query_type": "BOGUS"}).status_code == 422
    assert client.put("/admin/examples/99999", json={"question": "Valid question", "sql": GOOD_SQL}).status_code == 404
    assert client.get("/admin/examples/search").status_code == 422


def test_examples_filter_by_type_in_search(client):
    hits = client.get("/admin/examples/search", params={"q": "orders last month", "k": 5, "query_type": "SELECT_TEMPORAL"}).json()
    assert hits and all(h["query_type"] == "SELECT_TEMPORAL" for h in hits)


def test_examples_persist_across_restart(env):
    client, _, tmp_path, biz = env
    n = client.post("/admin/examples", json={"question": "Persistent question here", "sql": GOOD_SQL}).json()["id"]
    app2 = TestClient(create_app(settings(tmp_path, biz)))
    assert any(e["id"] == n for e in app2.get("/admin/examples").json())
    assert app2.app.state.container.examples.in_sync()


# ---------------- guardrails ----------------
def test_guardrails_get_put_persist_and_apply(env):
    client, _, tmp_path, biz = env
    g = client.get("/admin/guardrails").json()
    assert g["max_rows"] == 100 and g["allow_delete"] is False and g["allow_select"] is True
    g.update(max_rows=5, allowed_table_prefixes=["order"], allow_drop=True)
    assert client.put("/admin/guardrails", json=g).json()["max_rows"] == 5
    assert TestClient(create_app(settings(tmp_path, biz))).get("/admin/guardrails").json()["allowed_table_prefixes"] == ["order"]
    # applies to the next /query without restart
    r = client.post("/query", json={"question": "list orders"}).json()
    assert r["status"] == "success" and r["row_count"] == 5


def test_guardrails_validation(client):
    assert client.put("/admin/guardrails", json={"max_rows": 0}).status_code == 422
    assert client.put("/admin/guardrails", json={"max_rows": "lots"}).status_code == 422


# ---------------- model config ----------------
def test_config_put_applies_to_next_request(env):
    client, seen, *_ = env
    assert client.get("/admin/config").json()["provider"] == "anthropic"
    new = {"provider": "openai", "model": "gpt-4o", "temperature": 0.3, "dialect": "sqlite", "max_tokens": 2048}
    assert client.put("/admin/config", json=new).json() == new
    client.post("/query", json={"question": "list orders"})
    assert seen[-1].provider == "openai" and seen[-1].model == "gpt-4o" and seen[-1].temperature == 0.3


@pytest.mark.parametrize("bad", [{"provider": "bogus"}, {"dialect": "oracle"}, {"temperature": 2}, {"max_tokens": 1}, {"model": " "}])
def test_config_validation(client, bad):
    body = {"provider": "anthropic", "model": "m", "temperature": 0.0, "dialect": "sqlite", "max_tokens": 512, **bad}
    assert client.put("/admin/config", json=body).status_code == 422


# ---------------- logs ----------------
def test_logs_filters_and_csv_export(client):
    client.post("/query", json={"question": "list orders"})
    client.post("/query", json={"question": "Delete all orders please"})
    logs = client.get("/admin/logs").json()
    assert [l["status"] for l in logs] == ["unsupported", "success"]
    ok = logs[1]
    assert ok["sql"] and ok["latency_ms"] >= 0 and ok["row_count"] == 100 and ok["question"] == "list orders"
    assert [l["status"] for l in client.get("/admin/logs", params={"status": "unsupported"}).json()] == ["unsupported"]
    assert len(client.get("/admin/logs", params={"q": "LIST"}).json()) == 1
    now = datetime.utcnow()
    assert len(client.get("/admin/logs", params={"from": (now - timedelta(hours=1)).isoformat()}).json()) == 2
    assert client.get("/admin/logs", params={"from": (now + timedelta(hours=1)).isoformat()}).json() == []
    assert len(client.get("/admin/logs", params={"limit": 1}).json()) == 1
    assert client.get("/admin/logs", params={"limit": 0}).status_code == 422

    r = client.get("/admin/logs/export", params={"format": "csv", "status": "success"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv") and "attachment" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 1 and rows[0]["question"] == "list orders" and rows[0]["row_count"] == "100"
    assert client.get("/admin/logs/export", params={"format": "xml"}).status_code == 400
