import json
import sqlite3
from pathlib import Path

import pytest

from app.pipeline.sql_executor import SQLExecutor
from app.pipeline.sql_validator import SQLValidator
from app.schemas.executor import ExecutorInput
from app.schemas.validator import GuardrailConfig, ValidatorInput
from app.services.schema_manager import SchemaManager

SEED = Path(__file__).resolve().parent.parent / "data" / "examples_seed.json"


@pytest.fixture()
def cfg():
    return GuardrailConfig()


@pytest.fixture()
def validator(business_engine, admin_sessions, cfg):
    sm = SchemaManager(business_engine, admin_sessions)
    sm.seed_defaults()
    return SQLValidator(sm.list_tables, sm.sensitive_columns, lambda: cfg)


def v(validator, sql):
    return validator.validate(ValidatorInput(sql=sql))


# ---------- positive ----------
def test_all_seed_examples_validate(validator):
    for ex in json.loads(SEED.read_text()):
        out = v(validator, ex["sql"])
        assert out.valid, (ex["question"], out.errors)


def test_updated_at_column_is_not_a_false_positive(validator):
    assert v(validator, "SELECT 'update' AS verb, name FROM products WHERE name LIKE '%delete%'").valid


def test_sanitized_sql_is_rendered_from_ast_without_comments(validator):
    out = v(validator, "SELECT id /* DROP TABLE x */ FROM orders -- trailing")
    assert out.valid and "DROP" not in out.sanitized_sql and "--" not in out.sanitized_sql


# ---------- guardrails ----------
@pytest.mark.parametrize("sql", [
    "DELETE FROM orders", "drop table orders", "DrOp TaBlE orders", "UPDATE orders SET status='x'",
    "INSERT INTO categories(name) VALUES ('x')", "TRUNCATE TABLE orders", "ALTER TABLE orders ADD COLUMN x INT",
    "CREATE TABLE t(a INT)", "REPLACE INTO categories VALUES (1,'x')", "PRAGMA writable_schema=1",
    "ATTACH DATABASE 'x.db' AS x", "VACUUM", "DROP/**/TABLE orders", "DELETE/* hi */FROM orders",
    "WITH d AS (SELECT 1) DELETE FROM orders", "SELECT 1; DROP TABLE orders", "SELECT * FROM orders; DELETE FROM orders;",
    "SELECT load_extension('evil')", "BEGIN",
])
def test_blocked(validator, sql):
    out = v(validator, sql)
    assert not out.valid and out.errors and out.sanitized_sql == ""


def test_stacked_query_message(validator):
    assert "stacked" in v(validator, "SELECT 1; SELECT 2").errors[0].lower()


def test_trailing_semicolon_is_fine(validator):
    assert v(validator, "SELECT id FROM orders;").valid


def test_admin_toggle_allows_operation_at_validator_but_not_db(validator, cfg, business_engine):
    cfg.allow_delete = True
    out = v(validator, "DELETE FROM orders WHERE id = 1")
    assert out.valid  # validator honours the toggle...
    res = SQLExecutor(business_engine).execute(ExecutorInput(sql=out.sanitized_sql))
    assert res.error  # ...but the read-only DB layer still refuses


def test_syntax_error(validator):
    out = v(validator, "SELEC id FROM orders")
    assert not out.valid


# ---------- schema ----------
def test_unknown_table_and_column(validator):
    assert "Unknown table" in v(validator, "SELECT * FROM ghosts").errors[0]
    assert not v(validator, "SELECT nope FROM orders").valid
    assert not v(validator, "SELECT o.nope FROM orders o").valid


def test_sensitive_columns_rejected_everywhere(validator):
    for sql in ["SELECT email FROM customers", "SELECT c.phone FROM customers c",
                "SELECT id FROM customers WHERE email LIKE '%@x.com'",
                "WITH x AS (SELECT email FROM customers) SELECT * FROM x",
                "SELECT n FROM (SELECT email AS n FROM customers) t"]:
        out = v(validator, sql)
        assert not out.valid and "sensitive" in out.errors[0], sql


def test_star_expands_without_sensitive_columns(validator):
    out = v(validator, "SELECT * FROM customers")
    assert out.valid and "email" not in out.sanitized_sql and "phone" not in out.sanitized_sql and "country" in out.sanitized_sql
    assert v(validator, "SELECT COUNT(*) FROM customers").valid


def test_allowed_prefixes_and_schemas(validator, cfg):
    cfg.allowed_table_prefixes = ["order"]
    assert v(validator, "SELECT id FROM orders").valid
    assert "outside the allowed scope" in v(validator, "SELECT id FROM customers").errors[0]
    cfg.allowed_table_prefixes = []
    assert "outside the allowed scope" in v(validator, "SELECT 1 FROM other.orders").errors[0]


# ---------- limits ----------
def test_limit_appended_clamped_and_respected(validator, cfg):
    cfg.max_rows = 50
    assert v(validator, "SELECT id FROM orders").sanitized_sql.upper().endswith("LIMIT 50")
    assert v(validator, "SELECT id FROM orders LIMIT 1000").sanitized_sql.upper().endswith("LIMIT 50")
    assert v(validator, "SELECT id FROM orders LIMIT 5").sanitized_sql.upper().endswith("LIMIT 5")
    assert "LIMIT 50" in v(validator, "SELECT id FROM orders UNION SELECT id FROM customers").sanitized_sql.upper()
    cfg.max_rows = 7
    assert "LIMIT 7" in v(validator, "WITH a AS (SELECT id FROM orders) SELECT id FROM a").sanitized_sql.upper()


# ---------- executor ----------
def test_executor_runs_validated_sql(validator, business_engine):
    out = v(validator, "SELECT status, COUNT(*) AS n FROM orders GROUP BY status ORDER BY n DESC")
    res = SQLExecutor(business_engine).execute(ExecutorInput(sql=out.sanitized_sql))
    assert res.error is None and res.columns == ["status", "n"] and res.row_count == 5 and res.latency_ms >= 0


def test_executor_write_fails_at_db_layer_even_without_validator(business_engine, business_db_path):
    ex = SQLExecutor(business_engine)
    for sql in ["DELETE FROM orders", "DROP TABLE orders", "UPDATE orders SET status='x'", "INSERT INTO categories(name) VALUES ('z')"]:
        res = ex.execute(ExecutorInput(sql=sql))
        assert res.error and "sqlite" not in res.error.lower() and "orders" not in res.error
    assert sqlite3.connect(business_db_path).execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 5000


def test_executor_safe_error_and_hidden_detail(business_engine):
    res = SQLExecutor(business_engine).execute(ExecutorInput(sql="SELECT nope FROM orders"))
    assert res.error == "The database could not run this query." and res.detail
    assert "detail" not in json.loads(res.model_dump_json())


def test_executor_timeout(business_engine):
    slow = ("WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x < 100000000) SELECT COUNT(*) FROM c")
    res = SQLExecutor(business_engine).execute(ExecutorInput(sql=slow, timeout_seconds=0.3))
    assert res.error and "too long" in res.error and res.latency_ms < 5000


def test_timeout_handler_does_not_leak_to_pooled_connection(business_engine):
    """Regression: a stale progress-handler deadline used to abort the next user of the same pooled connection."""
    import time
    ex = SQLExecutor(business_engine)
    assert ex.execute(ExecutorInput(sql="SELECT COUNT(*) FROM orders", timeout_seconds=0.2)).error is None
    time.sleep(0.4)  # deadline has now passed
    heavy = "SELECT COUNT(*) FROM order_items a JOIN order_items b ON a.product_id = b.product_id"
    with business_engine.connect() as conn:  # same pool, e.g. schema introspection
        assert conn.exec_driver_sql(heavy).scalar() > 0
