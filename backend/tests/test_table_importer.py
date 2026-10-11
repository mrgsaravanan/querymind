import json
import shutil
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.admin import create_admin_sessionmaker
from app.db.business import create_readonly_engine, create_write_engine
from app.main import create_app
from app.pipeline.sql_executor import SQLExecutor
from app.schemas.admin import QueryRequest, QueryStatus
from app.schemas.executor import ExecutorInput
from app.schemas.tables import ImportColumn, ImportConfig
from app.services import table_importer as ti
from app.services.schema_manager import SchemaManager
from tests.fakes import ScriptedLLM

SUPPLIERS = (
    "Supplier Name,City,Rating,Founded,Contact Email,Phone,Zip,Active\n"
    "Acme Ltd,Pune,4.5,2010-03-01,acme@example.com,+91 98765 43210,0123,yes\n"
    "Globex,Delhi,3.9,2012-07-15,globex@example.com,+91 91234 56789,0456,no\n"
    "Initech,Mumbai,,2015-01-20,init@example.com,+91 99999 88888,0789,yes\n"
).encode()


# ------------------------------------------------------------------ parsing / inference / naming
def test_parse_delimiters_bom_blank_lines_and_padding():
    d = ti.parse_csv("﻿a;b;c\n1;2;3\n\n4;5\n".encode("utf-8"), 100)
    assert d.header == ["a", "b", "c"] and d.delimiter == ";" and d.rows == [["1", "2", "3"], ["4", "5", None]]
    assert ti.parse_csv(b"a\tb\n1\t2\n", 10).delimiter == "\t"


def test_parse_non_utf8_warns():
    d = ti.parse_csv("name\nJosé\n".encode("cp1252"), 10)
    assert d.encoding == "cp1252" and d.rows == [["José"]] and "not UTF-8" in d.warnings[0]


@pytest.mark.parametrize("data,msg", [(b"", "empty"), (b"a,b\n", "no data rows"), (b"a,b\n1,2,3,4\n", "malformed"),
                                      (b"a,b\n" + b"1,2\n" * 6, "Too many rows")])
def test_parse_errors(data, msg):
    with pytest.raises(ti.ImportValidationError, match=msg):
        ti.parse_csv(data, 5)


def test_parse_too_many_columns():
    with pytest.raises(ti.ImportValidationError, match="Too many columns"):
        ti.parse_csv((",".join(f"c{i}" for i in range(101)) + "\n" + ",".join("1" for _ in range(101))).encode(), 10)


@pytest.mark.parametrize("values,expected", [
    (["1", "-2", None], "INTEGER"), (["1.5", "2", None], "REAL"), (["1e3", "2.5"], "REAL"),
    (["0123", "0456"], "TEXT"), (["007", "7"], "TEXT"),                                  # padded ids / zip codes stay text
    (["2024-01-31", "2023-12-01"], "DATE"), (["2024-02-30"], "TEXT"),                   # impossible date
    (["2024-01-31 10:00", "2024-01-31T10:00:05Z"], "DATETIME"), (["a", "1"], "TEXT"), ([None, None], "TEXT"),
    (["12345678901234567890"], "TEXT"),                                                   # beyond int64 safety
])
def test_infer_type(values, expected):
    assert ti.infer_type(values) == expected


def test_coerce():
    assert ti.coerce("5", "INTEGER") == 5 and ti.coerce("2.5", "REAL") == 2.5 and ti.coerce(None, "INTEGER") is None
    for bad, t in [("x", "INTEGER"), ("1.5", "INTEGER"), ("abc", "REAL"), ("31/01/2024", "DATE"), ("tomorrow", "DATETIME")]:
        with pytest.raises(ValueError):
            ti.coerce(bad, t)


@pytest.mark.parametrize("raw,expected", [
    ("Order Date", "order_date"), ("OrderDate", "order_date"), ("  Total ($)  ", "total"), ("2024 sales", "c_2024_sales"),
    ("order", "order_col"), ("group", "group_col"), ("select", "select_col"), ("name", "name"), ("date", "date"),
    ("", "column_3"), ("%%%", "column_3"), ("sqlite_master", "x_sqlite_master"),
])
def test_sanitize_identifier(raw, expected):
    assert ti.sanitize_identifier(raw, set(), "column_3") == expected


def test_sanitize_dedupes():
    taken: set[str] = set()
    out = []
    for raw in ["Name", "name", "NAME"]:
        out.append(ti.sanitize_identifier(raw, taken, "c"))
        taken.add(out[-1])
    assert out == ["name", "name_2", "name_3"]


def test_identifier_validation():
    for bad in ["My Table", "1abc", "orders; DROP TABLE x", "", "UPPER", "a" * 70, "order", "sqlite_x", 'a"b']:
        with pytest.raises(ti.ImportValidationError):
            ti.validate_identifier(bad, "Table name")
    ti.validate_identifier("my_table2", "Table name")


def test_sensitive_suggestions():
    s = ti.suggest_sensitive
    assert s("Contact Email", "contact_email", "TEXT", ["a"]) and s("phone_no", "phone_no", "TEXT", []) and s("Passport", "passport", "TEXT", [])
    assert "email" in s("contact", "contact", "TEXT", ["a@b.com", "c@d.org", "e@f.io", "g@h.net"])
    assert "phone" in s("c1", "c1", "TEXT", ["+91 98765 43210", "+91 91234 56789", "+1 (555) 123-4567"])
    assert "national" in s("c2", "c2", "TEXT", ["123-45-6789", "987-65-4321", "111-22-3333"])
    assert s("amount", "amount", "INTEGER", ["1234567890", "9876543210", "1112223334"]) is None   # numbers are not phones
    assert s("city", "city", "TEXT", ["Pune", "Delhi", "Mumbai"]) is None and s("rating", "rating", "REAL", []) is None


# ------------------------------------------------------------------ service
@pytest.fixture()
def env(tmp_path, business_db_path):
    db = tmp_path / "biz.db"
    shutil.copy(business_db_path, db)                           # never mutate the shared session database
    sessions = create_admin_sessionmaker(":memory:")
    ro = create_readonly_engine(db)
    schema = SchemaManager(ro, sessions)
    schema.seed_defaults()
    imp = ti.TableImporter(create_write_engine(db), sessions, schema, max_rows=1000)
    return imp, schema, db, ro


def cfg_from_preview(p, **over):
    base = dict(table_name=p.suggested_table_name, description=p.suggested_table_description, mode="create",
                columns=[ImportColumn(original_name=c.original_name, name=c.name, type=c.type, description=c.suggested_description,
                                      sensitive=c.suggested_sensitive) for c in p.columns])
    base.update(over)
    return ImportConfig(**base)


def test_preview_is_read_only_and_detects_everything(env):
    imp, schema, db, _ = env
    p = imp.preview("Suppliers 2025.csv", SUPPLIERS)
    assert p.suggested_table_name == "suppliers_2025" and p.row_count == 3 and not p.name_conflict
    by = {c.original_name: c for c in p.columns}
    assert by["Supplier Name"].name == "supplier_name" and by["Rating"].type == "REAL" and by["Rating"].null_count == 1
    assert by["Founded"].type == "DATE" and by["Zip"].type == "TEXT" and by["Active"].type == "TEXT"
    assert by["Contact Email"].suggested_sensitive and by["Phone"].suggested_sensitive and not by["City"].suggested_sensitive
    assert p.sample_rows[0][0] == "Acme Ltd" and any("rewritten" in w for w in p.warnings)
    assert "suppliers_2025" not in {t.name for t in schema.list_tables()}          # preview wrote nothing


def test_preview_warns_on_non_iso_dates(env):
    imp, *_ = env
    p = imp.preview("x.csv", b"id,when\n1,31/01/2024\n2,15/02/2024\n3,01/03/2024\n")
    assert p.columns[1].type == "TEXT" and any("non-ISO" in w for w in p.warnings)


def test_import_creates_table_rows_types_and_metadata(env):
    imp, schema, db, _ = env
    p = imp.preview("suppliers.csv", SUPPLIERS)
    res = imp.import_table("suppliers.csv", SUPPLIERS, cfg_from_preview(p))
    assert res.rows_imported == 3 and not res.replaced and res.table.name == "suppliers"
    con = sqlite3.connect(db)
    assert con.execute("SELECT supplier_name, rating, founded, zip FROM suppliers ORDER BY rowid").fetchall() == [
        ("Acme Ltd", 4.5, "2010-03-01", "0123"), ("Globex", 3.9, "2012-07-15", "0456"), ("Initech", None, "2015-01-20", "0789")]
    assert [r[2] for r in con.execute("PRAGMA table_info(suppliers)")] == ["TEXT", "TEXT", "REAL", "DATE", "TEXT", "TEXT", "TEXT", "TEXT"]
    tbl = schema.get_table("suppliers")
    cols = {c.name: c for c in tbl.columns}
    assert cols["contact_email"].sensitive and cols["phone"].sensitive and not cols["city"].sensitive
    assert cols["rating"].description and tbl.description.startswith("Suppliers")
    assert ("suppliers", "contact_email") in schema.sensitive_columns()
    assert [i.table_name for i in imp.list_imported()] == ["suppliers"] and imp.list_imported()[0].row_count == 3


def test_import_is_all_or_nothing_on_bad_values(env):
    imp, schema, db, _ = env
    p = imp.preview("t.csv", b"id,qty\n1,5\n2,six\n")            # qty detected as TEXT
    cfg = cfg_from_preview(p)
    cfg.columns[1].type = "INTEGER"                                # user forces a wrong type
    with pytest.raises(ti.ImportValidationError) as e:
        imp.import_table("t.csv", b"id,qty\n1,5\n2,six\n", cfg)
    assert "line 3" in e.value.details[0] and "six" in e.value.details[0]
    assert "t" not in {x.name for x in schema.list_tables()} and imp.list_imported() == []


@pytest.mark.parametrize("name", ["My Table", "1abc", "orders; DROP TABLE x", "", "order", "UPPER"])
def test_invalid_table_names_rejected(env, name):
    imp, *_ = env
    p = imp.preview("t.csv", b"a,b\n1,2\n")
    with pytest.raises(ti.ImportValidationError):
        imp.import_table("t.csv", b"a,b\n1,2\n", cfg_from_preview(p, table_name=name))


def test_invalid_column_configs_rejected(env):
    imp, *_ = env
    data = b"a,b\n1,2\n"
    p = imp.preview("t.csv", data)
    cfg = cfg_from_preview(p)
    cfg.columns[1].name = cfg.columns[0].name
    with pytest.raises(ti.ImportValidationError, match="Duplicate"):
        imp.import_table("t.csv", data, cfg)
    cfg = cfg_from_preview(p)
    cfg.columns[0].original_name = "not_in_file"
    with pytest.raises(ti.ImportValidationError, match="not in the uploaded file"):
        imp.import_table("t.csv", data, cfg)
    cfg = cfg_from_preview(p)
    cfg.columns[0].name = "select"
    with pytest.raises(ti.ImportValidationError, match="reserved"):
        imp.import_table("t.csv", data, cfg)


def test_cannot_overwrite_or_replace_seeded_tables(env):
    imp, schema, db, _ = env
    data = b"id,name\n1,x\n"
    p = imp.preview("orders.csv", data)
    assert p.name_conflict and not p.can_replace
    for mode in ("create", "replace"):
        with pytest.raises(ti.ImportConflictError):
            imp.import_table("orders.csv", data, cfg_from_preview(p, mode=mode))
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 5000


def test_replace_imported_table_refreshes_data_and_metadata(env):
    imp, schema, db, _ = env
    v1 = b"a,b\n1,x\n2,y\n"
    imp.import_table("t.csv", v1, cfg_from_preview(imp.preview("t.csv", v1)))
    v2 = b"a,c\n9,z\n"
    p2 = imp.preview("t.csv", v2)
    assert p2.name_conflict and p2.can_replace
    with pytest.raises(ti.ImportConflictError):                                   # must opt in
        imp.import_table("t.csv", v2, cfg_from_preview(p2))
    res = imp.import_table("t.csv", v2, cfg_from_preview(p2, mode="replace"))
    assert res.replaced and res.rows_imported == 1
    assert [c.name for c in schema.get_table("t").columns] == ["a", "c"]          # old column b is gone from the schema
    with schema._sessions() as s:                                                 # ...and from stale metadata
        from app.db.admin import ColumnMeta
        assert {c.column_name for c in s.query(ColumnMeta).filter_by(table_name="t")} == {"a", "c"}
    with pytest.raises(ti.ImportValidationError, match="no such imported table"):
        imp.import_table("n.csv", v2, cfg_from_preview(imp.preview("n.csv", v2), table_name="nope", mode="replace"))


def test_delete_only_imported_tables(env):
    imp, schema, db, _ = env
    imp.import_table("t.csv", b"a\n1\n", cfg_from_preview(imp.preview("t.csv", b"a\n1\n")))
    imp.delete("t")
    assert "t" not in {x.name for x in schema.list_tables()} and imp.list_imported() == []
    for protected in ("orders", "customers", "does_not_exist"):
        with pytest.raises(ti.ImportNotFoundError):
            imp.delete(protected)
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 5000


def test_hostile_cell_values_are_stored_literally(env):
    imp, schema, db, _ = env
    evil = "x'); DROP TABLE orders; --"
    data = f'id,note\n1,"{evil}"\n2,"Robert\'); DELETE FROM customers;--"\n'.encode()
    imp.import_table("notes.csv", data, cfg_from_preview(imp.preview("notes.csv", data)))
    con = sqlite3.connect(db)
    assert con.execute("SELECT note FROM notes WHERE id = 1").fetchone()[0] == evil
    assert con.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 5000 and con.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 1200


def test_query_path_stays_read_only_after_import(env):
    imp, schema, db, ro = env
    imp.import_table("t.csv", b"a\n1\n", cfg_from_preview(imp.preview("t.csv", b"a\n1\n")))
    ex = SQLExecutor(ro)
    assert ex.execute(ExecutorInput(sql="SELECT a FROM t")).rows == [[1]]          # the read-only engine sees the new table
    for sql in ("DELETE FROM t", "DROP TABLE t", "INSERT INTO t(a) VALUES (2)"):
        assert ex.execute(ExecutorInput(sql=sql)).error
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1


def test_reserved_looking_headers_become_usable_columns(env):
    imp, schema, db, ro = env
    data = b"Order,Group,Date,Name\n1,a,2024-01-01,x\n"
    p = imp.preview("odd.csv", data)
    assert [c.name for c in p.columns] == ["order_col", "group_col", "date", "name"]
    imp.import_table("odd.csv", data, cfg_from_preview(p))
    assert SQLExecutor(ro).execute(ExecutorInput(sql="SELECT order_col, group_col, date, name FROM odd")).rows == [[1, "a", "2024-01-01", "x"]]


# ------------------------------------------------------------------ API + end to end
def make_app(tmp_path, business_db_path, llm=None, **kw):
    db = tmp_path / "biz.db"
    if not db.exists():
        shutil.copy(business_db_path, db)
    st = Settings(business_db_path=db, admin_db_path=tmp_path / "admin.db", chroma_path=tmp_path / "chroma", embedding_backend="hashing", **kw)
    return create_app(st, llm_factory=(lambda cfg: llm) if llm else None)


def upload(client, data=SUPPLIERS, name="suppliers.csv"):
    return client.post("/admin/tables/preview", files={"file": (name, data, "text/csv")})


def do_import(client, preview_json, data=SUPPLIERS, name="suppliers.csv", **over):
    cfg = {"table_name": preview_json["suggested_table_name"], "description": "Our suppliers", "mode": "create",
           "columns": [{"original_name": c["original_name"], "name": c["name"], "type": c["type"], "description": c["suggested_description"],
                        "sensitive": c["suggested_sensitive"]} for c in preview_json["columns"]]}
    cfg.update(over)
    return client.post("/admin/tables/import", files={"file": (name, data, "text/csv")}, data={"config": json.dumps(cfg)})


def test_api_preview_import_list_delete_and_persistence(tmp_path, business_db_path):
    client = TestClient(make_app(tmp_path, business_db_path))
    pj = upload(client).json()
    assert pj["row_count"] == 3 and pj["suggested_table_name"] == "suppliers" and pj["columns"][4]["suggested_sensitive"]
    r = do_import(client, pj)
    assert r.status_code == 201 and r.json()["rows_imported"] == 3
    assert "suppliers" in {t["name"] for t in client.get("/admin/schema").json()}
    assert [i["table_name"] for i in client.get("/admin/tables/imported").json()] == ["suppliers"]
    # survives an app restart
    client2 = TestClient(make_app(tmp_path, business_db_path))
    sup = next(t for t in client2.get("/admin/schema").json() if t["name"] == "suppliers")
    assert next(c for c in sup["columns"] if c["name"] == "contact_email")["sensitive"] is True
    assert client2.delete("/admin/tables/suppliers").status_code == 204
    assert client2.delete("/admin/tables/suppliers").status_code == 404
    assert client2.delete("/admin/tables/orders").status_code == 404


def test_api_errors(tmp_path, business_db_path):
    client = TestClient(make_app(tmp_path, business_db_path, import_max_bytes=200))
    assert upload(client, b"x" * 500).status_code == 413
    assert upload(client, b"").status_code == 422
    big = TestClient(make_app(tmp_path, business_db_path))
    pj = upload(big).json()
    assert do_import(big, pj, table_name="Bad Name").status_code == 422
    assert do_import(big, pj, table_name="orders").status_code == 409
    assert big.post("/admin/tables/import", files={"file": ("a.csv", SUPPLIERS, "text/csv")}, data={"config": "{not json"}).status_code == 422
    assert big.post("/admin/tables/import", files={"file": ("a.csv", SUPPLIERS, "text/csv")}, data={"config": json.dumps({"table_name": "x"})}).status_code == 422
    assert big.post("/admin/tables/preview").status_code == 422


def test_api_import_can_be_disabled(tmp_path, business_db_path):
    client = TestClient(make_app(tmp_path, business_db_path, allow_table_import=False))
    assert upload(client).status_code == 403 and client.get("/admin/tables/imported").status_code == 403
    assert client.get("/health").status_code == 200                                  # rest of the app unaffected


def test_end_to_end_ask_questions_about_imported_table(tmp_path, business_db_path):
    llm = ScriptedLLM(json.dumps({"query_type": "SELECT_SIMPLE", "tables_mentioned": ["suppliers"], "columns_mentioned": []}),
                      json.dumps({"sql": "SELECT * FROM suppliers WHERE rating > 4", "explanation": "Suppliers rated above 4."}), "One supplier.")
    app = make_app(tmp_path, business_db_path, llm=llm)
    client = TestClient(app)
    do_import(client, upload(client).json())
    r = client.post("/query", json={"question": "Which suppliers have a rating above 4?"}).json()
    assert r["status"] == "success" and r["row_count"] == 1
    assert r["table"]["columns"] == ["supplier_name", "city", "rating", "founded", "zip", "active"]   # email + phone hidden
    assert r["table"]["rows"][0][0] == "Acme Ltd"
    seen = " ".join(system + user for _, system, user in llm.calls).lower()
    assert "suppliers" in seen and "rating" in seen                                   # the model was shown the new table...
    assert "contact_email" not in seen and "phone" not in seen.replace("telephone", "")  # ...but never its sensitive columns
