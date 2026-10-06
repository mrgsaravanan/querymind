from datetime import datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.schemas.admin import ColumnUpdate, ModelConfig, TableUpdate
from app.schemas.validator import GuardrailConfig
from app.services.config_manager import ConfigManager, ConfigValidationError
from app.services.guardrails_manager import GuardrailsManager
from app.services.log_service import LogService
from app.services.schema_manager import SchemaManager, SchemaNotFoundError


def test_readonly_engine_rejects_writes(business_engine):
    with business_engine.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM orders")).scalar() == 5000
        with pytest.raises(OperationalError):
            c.execute(text("DELETE FROM orders"))
            c.commit()


def test_schema_introspection_and_defaults(business_engine, admin_sessions):
    sm = SchemaManager(business_engine, admin_sessions)
    sm.seed_defaults()
    tables = {t.name: t for t in sm.list_tables()}
    assert len(tables) == 7
    assert tables["order_items"].columns[1].foreign_key == "orders.id"
    assert sm.sensitive_columns() == {("customers", "email"), ("customers", "phone")}
    assert "email" not in {c.name for t in sm.non_sensitive_tables() if t.name == "customers" for c in t.columns}


def test_seed_defaults_does_not_overwrite_edits(business_engine, admin_sessions):
    sm = SchemaManager(business_engine, admin_sessions)
    sm.seed_defaults()
    sm.update_column(ColumnUpdate(table="customers", column="country", description="edited", sensitive=True))
    sm.seed_defaults()
    col = next(c for c in sm.get_table("customers").columns if c.name == "country")
    assert col.description == "edited" and col.sensitive


def test_update_unknown_column(business_engine, admin_sessions):
    sm = SchemaManager(business_engine, admin_sessions)
    with pytest.raises(SchemaNotFoundError):
        sm.update_column(ColumnUpdate(table="orders", column="nope", description="x"))
    assert sm.update_table(TableUpdate(table="orders", description="d")).description == "d"


def test_guardrails_persist(admin_sessions):
    gm = GuardrailsManager(admin_sessions)
    assert gm.get().max_rows == 100 and not gm.get().allow_delete
    gm.update(GuardrailConfig(max_rows=25, allowed_table_prefixes=["ord"]))
    assert GuardrailsManager(admin_sessions).get().max_rows == 25


def test_config_persist_and_validation(admin_sessions, settings):
    cm = ConfigManager(admin_sessions, settings)
    assert cm.get().provider == "anthropic"
    cm.update(ModelConfig(provider="ollama", model="llama3", temperature=0.2))
    assert cm.get().provider == "ollama"
    with pytest.raises(ConfigValidationError):
        cm.update(ModelConfig(provider="bogus"))


def test_logs_filter_and_csv(admin_sessions):
    ls = LogService(admin_sessions)
    ls.add(question="top products", status="success", sql="SELECT 1", latency_ms=5, row_count=3)
    ls.add(question="delete everything", status="unsupported")
    assert len(ls.list()) == 2
    assert [e.question for e in ls.list(status="unsupported")] == ["delete everything"]
    assert len(ls.list(q="TOP")) == 1
    assert ls.list(date_from=datetime.utcnow() + timedelta(days=1)) == []
    csv_text = ls.export_csv(status="success")
    assert csv_text.splitlines()[0].startswith("id,created_at,question") and "top products" in csv_text
