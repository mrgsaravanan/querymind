import json
import sqlite3
from pathlib import Path

import pytest

from eval import metrics, run_eval
from eval.run_eval import CachingLLM

EVAL = Path(__file__).resolve().parent.parent / "eval"
TESTS = json.loads((EVAL / "test_set.json").read_text())
ATTACKS = json.loads((EVAL / "guardrail_attacks.json").read_text())
SEED_EXAMPLES = json.loads((EVAL.parent / "data" / "examples_seed.json").read_text())


# ---------------- metrics ----------------
def test_results_match_normalization():
    assert metrics.results_match([[1, 2.0]], [[1.0, 2.001]])           # int/float and rounding
    assert metrics.results_match([["a "]], [["a"]])                     # trimmed strings
    assert metrics.results_match([[None]], [[None]])
    assert not metrics.results_match([[1, 2]], [[1, 3]])
    assert not metrics.results_match([[1], [2]], [[1]])                 # row count
    assert not metrics.results_match([[1, 2]], [[1]])                   # extra column


def test_row_order_matters_only_when_ordered():
    a, b = [[1], [2], [3]], [[3], [1], [2]]
    assert metrics.results_match(a, b, ordered=False)
    assert not metrics.results_match(a, b, ordered=True)
    assert metrics.results_match([[1, "x"], [1, None]], [[1, None], [1, "x"]])  # None-safe sorting


def test_sql_exact_and_semantic():
    gt = "SELECT name FROM customers WHERE country = 'Japan'"
    assert metrics.sql_exact("select  name\nfrom customers where country='Japan' ;", gt)
    assert metrics.sql_exact("SELECT name FROM customers WHERE country = 'Japan' LIMIT 100", gt, injected_limit=100)
    assert not metrics.sql_exact("SELECT name FROM customers WHERE country = 'Japan' LIMIT 100", gt)
    assert not metrics.sql_exact("SELECT name FROM customers WHERE country = 'India'", gt)
    assert metrics.sql_match("SELECT name FROM customers WHERE country = 'Japan'", gt) == (True, True)
    assert metrics.sql_match(None, gt) == (False, False)
    assert metrics.sql_match("SELEC garbage", gt) == (False, False)
    # semantically-equivalent-but-textually-different is counted by semantic only if sqlglot.diff sees no edits
    ex, sem = metrics.sql_match("SELECT name FROM customers WHERE country = 'Japan'", gt.replace("'Japan'", "'Brazil'"))
    assert (ex, sem) == (False, False)


# ---------------- data files ----------------
def test_test_set_shape_and_ground_truth_runs(business_db_path):
    assert len(TESTS) == 25 and len({t["id"] for t in TESTS}) == 25
    assert {t["query_type"] for t in TESTS} == {"SELECT_SIMPLE", "SELECT_AGGREGATE", "SELECT_JOIN", "SELECT_TEMPORAL"}
    assert any("ambiguity" in t["tags"] for t in TESTS)
    db = sqlite3.connect(f"file:{business_db_path}?mode=ro", uri=True)
    for t in TESTS:
        rows = db.execute(t["ground_truth_sql"]).fetchall()
        assert 0 < len(rows) <= 100, t["id"]          # non-empty and under the guardrail row cap


def test_no_leakage_between_examples_and_test_set():
    ex = {e["question"].lower() for e in SEED_EXAMPLES}
    assert not [t["id"] for t in TESTS if t["question"].lower() in ex]


def test_attack_suite_coverage():
    assert len(ATTACKS) >= 12
    cats = {a["category"] for a in ATTACKS}
    assert {"stacked", "obfuscation", "cte_wrapped", "prompt_injection", "natural_language"} <= cats
    assert {a["kind"] for a in ATTACKS} == {"sql", "nl"}
    assert len({a["id"] for a in ATTACKS}) == len(ATTACKS)


# ---------------- LLM cache ----------------
def test_caching_llm(tmp_path):
    class Inner:
        model, temperature, max_tokens = "m", 0.0, 10
        calls = 0

        def complete(self, s, u, *, max_tokens=None):
            Inner.calls += 1
            return f"r{Inner.calls}"
    c = CachingLLM(Inner(), tmp_path, enabled=True)
    assert c.complete("s", "u") == "r1" and c.complete("s", "u") == "r1" and (c.hits, c.misses) == (1, 1)
    assert c.complete("s", "other") == "r2"
    off = CachingLLM(Inner(), tmp_path, enabled=False)
    assert off.complete("s", "u") == "r3" and off.complete("s", "u") == "r4"


# ---------------- end-to-end harness runs ----------------
def run(tmp_path, *argv):
    return run_eval.main([*argv, "--output-dir", str(tmp_path), "--name", "r"])


def test_selftest_run_passes_and_writes_reports(tmp_path):
    assert run(tmp_path, "--mock-oracle") == 0
    data = json.loads((tmp_path / "r.json").read_text())
    s = data["summary"]
    assert s["execution_accuracy"] == 1.0 and s["exact_match"] == 1.0 and s["n_questions"] == 25 and s["db_unchanged"]
    assert [t["query_type"] for t in data["by_type"]] == ["SELECT_SIMPLE", "SELECT_AGGREGATE", "SELECT_JOIN", "SELECT_TEMPORAL"]
    assert all(a["outcome"] != "not_blocked" for a in data["attacks"])
    md = (tmp_path / "r.md").read_text()
    assert "HARNESS SELF-TEST" in md and "Accuracy by query type" in md and "Guardrail attack suite" in md


def test_wrong_sql_fails_threshold_and_lists_failures(tmp_path, monkeypatch):
    orig = run_eval.OracleLLM.complete

    def wrong(self, system, user, *, max_tokens=None):
        if "converts business questions into SQL" in system:
            return json.dumps({"sql": "SELECT id AS x FROM categories", "explanation": "wrong on purpose"})
        return orig(self, system, user, max_tokens=max_tokens)
    monkeypatch.setattr(run_eval.OracleLLM, "complete", wrong)
    assert run(tmp_path, "--mock-oracle", "--skip-guardrails") == 1
    data = json.loads((tmp_path / "r.json").read_text())
    assert data["summary"]["execution_accuracy"] < 0.5 and len(data["failures"]) > 20
    f = data["failures"][0]
    assert f["generated_sql"] and f["expected_sql"] and f["reason"]
    assert "## Failures" in (tmp_path / "r.md").read_text()


def test_blocked_sql_counts_as_failure_not_crash(tmp_path, monkeypatch):
    orig = run_eval.OracleLLM.complete

    def evil(self, system, user, *, max_tokens=None):
        if "converts business questions into SQL" in system:
            return json.dumps({"sql": "DELETE FROM orders", "explanation": "x"})
        return orig(self, system, user, max_tokens=max_tokens)
    monkeypatch.setattr(run_eval.OracleLLM, "complete", evil)
    assert run(tmp_path, "--mock-oracle", "--skip-guardrails", "--limit", "3") == 1
    data = json.loads((tmp_path / "r.json").read_text())
    assert all(q["status"] == "validation_failed" for q in data["questions"])


def test_no_llm_reports_not_evaluated_but_still_checks_guardrails(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    assert run(tmp_path) == 2
    data = json.loads((tmp_path / "r.json").read_text())
    assert not data["verdict"]["accuracy_evaluated"] and data["questions"] == []
    assert data["summary"]["guardrails_compliance"] == 1.0 and data["summary"]["db_unchanged"]
    assert "ACCURACY NOT EVALUATED" in (tmp_path / "r.md").read_text()
