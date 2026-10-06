"""SQL Validator: AST-based syntax, guardrail, schema and row-limit checks.

Decisions are made on the sqlglot AST, never on substrings, so a write hidden in a CTE/subquery is caught and a
column called ``updated_at`` is not. The SQL that gets executed is *re-rendered from the validated AST*, so what
runs is exactly what was checked (comments and parser quirks are gone).
"""
from __future__ import annotations

import logging
from typing import Callable

import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, ParseError, TokenError
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import traverse_scope

from app.db.dialects import get_dialect
from app.schemas.admin import TableInfo
from app.schemas.validator import GuardrailConfig, ValidatorInput, ValidatorOutput

log = logging.getLogger(__name__)

# AST node -> (operation label, GuardrailConfig toggle)
_WRITE_NODES: dict[type[exp.Expression], tuple[str, str]] = {
    exp.Insert: ("INSERT", "allow_insert"),
    exp.Update: ("UPDATE", "allow_update"),
    exp.Delete: ("DELETE", "allow_delete"),
    exp.Drop: ("DROP", "allow_drop"),
    exp.TruncateTable: ("TRUNCATE", "allow_truncate"),
    exp.Alter: ("ALTER", "allow_alter"),
    exp.Create: ("CREATE", "allow_create"),
}
# Never allowed, no toggle: can change engine state or escape the sandbox.
_ALWAYS_BLOCKED: dict[type[exp.Expression], str] = {
    exp.Pragma: "PRAGMA", exp.Attach: "ATTACH", exp.Command: "COMMAND", exp.Merge: "MERGE", exp.Copy: "COPY",
    exp.Set: "SET", exp.Use: "USE", exp.Transaction: "TRANSACTION", exp.Commit: "COMMIT", exp.Rollback: "ROLLBACK",
    exp.Into: "SELECT INTO",
}
_FIRST_TOKEN_BLOCKED = {"DROP", "DELETE", "UPDATE", "INSERT", "TRUNCATE", "ALTER", "CREATE", "REPLACE", "ATTACH",
                        "DETACH", "PRAGMA", "VACUUM", "MERGE", "GRANT", "REVOKE", "COPY"}
_FORBIDDEN_FUNCTIONS = {"load_extension", "readfile", "writefile", "edit", "pg_read_file", "pg_sleep", "sleep",
                        "benchmark", "load_file", "lo_import", "lo_export", "dblink", "xp_cmdshell"}


class SQLValidator:
    def __init__(self, tables_provider: Callable[[], list[TableInfo]], sensitive_provider: Callable[[], set[tuple[str, str]]],
                 guardrails_provider: Callable[[], GuardrailConfig]):
        """Providers are called on every validation so admin changes apply immediately."""
        self._tables = tables_provider            # full schema (incl. sensitive) as seen by the DB
        self._sensitive = sensitive_provider
        self._guardrails = guardrails_provider

    # ---------------------------------------------------------------- public
    def validate(self, inp: ValidatorInput) -> ValidatorOutput:
        cfg = self._guardrails()
        dialect = get_dialect(inp.dialect).sqlglot_name
        errors: list[str] = []

        sql = (inp.sql or "").strip()
        if not sql:
            return self._fail("Empty SQL.")

        try:
            statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
        except (ParseError, TokenError) as e:
            blocked = self._first_token_blocked(sql, dialect)
            if blocked and not self._op_allowed(blocked, cfg):
                return self._fail(f"Blocked operation: {blocked} statements are not allowed.")
            return self._fail(f"SQL syntax error: {str(e).splitlines()[0][:200]}")

        if not statements:
            return self._fail("No SQL statement found.")
        if len(statements) > 1:
            return self._fail("Multiple statements are not allowed (stacked queries). Send exactly one SELECT.")
        tree = statements[0]

        errors += self._guardrail_errors(tree, cfg)
        if errors:
            return ValidatorOutput(valid=False, errors=errors)
        if not isinstance(tree, exp.Query):
            if isinstance(tree, tuple(_WRITE_NODES)):  # an operation the admin explicitly toggled on
                errors += self._table_errors(tree, cfg)
                if errors:
                    return ValidatorOutput(valid=False, errors=errors)
                return ValidatorOutput(valid=True, sanitized_sql=tree.sql(dialect=dialect, comments=False))
            return self._fail("Only SELECT queries are allowed.")

        errors += self._function_errors(tree)
        schema_errors, final_tree = self._schema_errors(tree, dialect, cfg)
        errors += schema_errors
        if errors:
            return ValidatorOutput(valid=False, errors=errors)

        final_tree = self._apply_limit(final_tree, cfg.max_rows)
        return ValidatorOutput(valid=True, sanitized_sql=final_tree.sql(dialect=dialect, comments=False, pretty=False))

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _fail(msg: str) -> ValidatorOutput:
        return ValidatorOutput(valid=False, errors=[msg])

    @staticmethod
    def _op_allowed(op: str, cfg: GuardrailConfig) -> bool:
        toggle = {"DROP": "allow_drop", "DELETE": "allow_delete", "UPDATE": "allow_update", "INSERT": "allow_insert",
                  "TRUNCATE": "allow_truncate", "ALTER": "allow_alter", "CREATE": "allow_create"}.get(op)
        return bool(toggle and getattr(cfg, toggle))

    @staticmethod
    def _first_token_blocked(sql: str, dialect: str) -> str | None:
        """Tokenizer-based (comments are skipped) fallback for statements sqlglot cannot parse."""
        try:
            toks = sqlglot.tokenize(sql, read=dialect)
        except TokenError:
            return None
        if toks and toks[0].text.upper() in _FIRST_TOKEN_BLOCKED:
            return toks[0].text.upper()
        return None

    def _guardrail_errors(self, tree: exp.Expression, cfg: GuardrailConfig) -> list[str]:
        errors: list[str] = []
        for node in tree.walk():
            for cls, (label, toggle) in _WRITE_NODES.items():
                if isinstance(node, cls) and not getattr(cfg, toggle):
                    errors.append(f"Blocked operation: {label} is not allowed.")
            for cls, label in _ALWAYS_BLOCKED.items():
                if isinstance(node, cls):
                    errors.append(f"Blocked operation: {label} is not allowed.")
        if isinstance(tree, exp.Query) and not cfg.allow_select:
            errors.append("Blocked operation: SELECT is disabled by the administrator.")
        return list(dict.fromkeys(errors))

    @staticmethod
    def _function_errors(tree: exp.Expression) -> list[str]:
        errs = []
        for f in tree.find_all(exp.Func):
            name = (f.name if isinstance(f, exp.Anonymous) else f.sql_name()).lower()
            if name in _FORBIDDEN_FUNCTIONS:
                errs.append(f"Blocked function: {name}() is not allowed.")
        return list(dict.fromkeys(errs))

    def _table_errors(self, tree: exp.Expression, cfg: GuardrailConfig) -> list[str]:
        """Every referenced real table must exist and fall inside the allowed schemas/prefixes (CTE names excluded)."""
        known = {t.name for t in self._tables()}
        cte_names = {c.alias_or_name for c in tree.find_all(exp.CTE)}
        errors: list[str] = []
        for t in tree.find_all(exp.Table):
            if not t.name or (t.name in cte_names and not t.db):
                continue
            if t.db and t.db.lower() not in {s.lower() for s in cfg.allowed_schemas}:
                errors.append(f"Schema '{t.db}' is outside the allowed scope.")
            elif t.name not in known:
                errors.append(f"Unknown table '{t.name}'.")
            elif cfg.allowed_table_prefixes and not any(t.name.startswith(p) for p in cfg.allowed_table_prefixes):
                errors.append(f"Table '{t.name}' is outside the allowed scope.")
        return list(dict.fromkeys(errors))

    def _schema_errors(self, tree: exp.Expression, dialect: str, cfg: GuardrailConfig) -> tuple[list[str], exp.Expression]:
        tables = self._tables()
        sensitive = self._sensitive()
        full = {t.name: {c.name: "TEXT" for c in t.columns} for t in tables}
        safe = {t.name: {c.name: "TEXT" for c in t.columns if (t.name, c.name) not in sensitive} for t in tables}

        errors = self._table_errors(tree, cfg)
        if errors:
            return errors, tree

        # columns: resolve every reference to a real table.column on a copy
        try:
            q = qualify(tree.copy(), schema=full, dialect=dialect, expand_stars=False, validate_qualify_columns=True,
                        quote_identifiers=False, identify=False)
        except OptimizeError as e:
            msg = str(e)
            return [f"Schema check failed: {msg[:200]}"], tree

        for scope in traverse_scope(q):
            for col in scope.columns:
                src = scope.sources.get(col.table)
                if isinstance(src, exp.Table) and (src.name, col.name) in sensitive:
                    return [f"Column '{src.name}.{col.name}' is sensitive and cannot be queried."], tree

        # projection stars: expand against the NON-sensitive schema so they can never leak a sensitive column
        if any(isinstance(p, exp.Star) or (isinstance(p, exp.Column) and isinstance(p.this, exp.Star))
               for s in tree.find_all(exp.Select) for p in s.expressions):
            try:
                q2 = qualify(tree.copy(), schema=safe, dialect=dialect, expand_stars=True, validate_qualify_columns=True,
                             quote_identifiers=False, identify=False)
            except OptimizeError as e:
                return [f"Schema check failed: {str(e)[:200]}"], tree
            return [], q2
        return [], tree

    @staticmethod
    def _apply_limit(tree: exp.Expression, max_rows: int) -> exp.Expression:
        """Append LIMIT if missing; clamp an excessive literal (or non-literal) existing limit."""
        limit = tree.args.get("limit")
        if limit is None:
            return tree.limit(max_rows)
        node = limit.expression
        if isinstance(node, exp.Literal) and node.is_int:
            if int(node.this) > max_rows:
                limit.set("expression", exp.Literal.number(max_rows))
        else:
            limit.set("expression", exp.Literal.number(max_rows))
        return tree
