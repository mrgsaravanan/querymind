"""Schema Linker: maps words/synonyms in the question to real tables and columns (deterministic).

Matching uses column/table names plus the ``(also: a, b)`` synonym lists in admin-edited descriptions.
It only ever sees the non-sensitive schema, so sensitive columns cannot appear in its output.
"""
from __future__ import annotations

import re
from typing import Callable

from app.schemas.admin import TableInfo
from app.schemas.linker import Ambiguity, ColumnRef, LinkerInput, LinkerOutput

_ALSO = re.compile(r"\(also:\s*([^)]*)\)", re.I)
_SKIP_COLUMNS = {"id"}


def _stem(w: str) -> str:
    for suf, rep in (("ies", "y"), ("ses", "s"), ("es", ""), ("s", "")):
        if w.endswith(suf) and len(w) > len(suf) + 2:
            return w[: -len(suf)] + rep
    return w


def _tokens(text: str) -> list[str]:
    return [_stem(t) for t in re.findall(r"[a-z0-9]+", text.lower())]


def _contains(hay: list[str], needle: list[str]) -> bool:
    n = len(needle)
    return n > 0 and any(hay[i : i + n] == needle for i in range(len(hay) - n + 1))


def _synonyms(description: str) -> list[list[str]]:
    out = []
    for grp in _ALSO.findall(description or ""):
        out += [_tokens(p) for p in grp.split(",") if p.strip()]
    return out


class SchemaLinker:
    def __init__(self, tables_provider: Callable[[], list[TableInfo]]):
        self._tables = tables_provider

    def link(self, inp: LinkerInput) -> LinkerOutput:
        tables = self._tables()
        q = _tokens(inp.question)

        # tables matched by name/synonym, or named by the classifier
        matched_tables: list[str] = []
        for t in tables:
            names = [_tokens(t.name.replace("_", " "))] + _synonyms(t.description)
            if any(_contains(q, n) for n in names):
                matched_tables.append(t.name)
        if inp.classification:
            for name in inp.classification.tables_mentioned:
                if name not in matched_tables and any(t.name == name for t in tables):
                    matched_tables.append(name)

        name_counts: dict[str, int] = {}
        for t in tables:
            for c in t.columns:
                name_counts[c.name] = name_counts.get(c.name, 0) + 1

        columns: dict[str, ColumnRef] = {}
        syn_hits: dict[str, list[ColumnRef]] = {}  # matched synonym phrase -> columns
        for t in tables:
            for c in t.columns:
                if c.name in _SKIP_COLUMNS:
                    continue
                ref = ColumnRef(table=t.name, column=c.name, type=c.type, description=c.description)
                name_hit = _contains(q, _tokens(c.name.replace("_", " ")))
                # generic names (e.g. "name", "created_at") only count when their table is in play
                if name_hit and (name_counts[c.name] == 1 or t.name in matched_tables):
                    columns[ref.qualified] = ref
                for syn in _synonyms(c.description):
                    if _contains(q, syn):
                        columns[ref.qualified] = ref
                        syn_hits.setdefault(" ".join(syn), []).append(ref)
        if inp.classification:
            for cm in inp.classification.columns_mentioned:
                for t in tables:
                    for c in t.columns:
                        if cm in (c.name, f"{t.name}.{c.name}") and c.name not in _SKIP_COLUMNS \
                                and (name_counts[c.name] == 1 or t.name in matched_tables or "." in cm):
                            columns.setdefault(f"{t.name}.{c.name}", ColumnRef(table=t.name, column=c.name, type=c.type, description=c.description))

        ambiguities = []
        for term, refs in syn_hits.items():
            uniq = list(dict.fromkeys(r.qualified for r in refs))
            if len(uniq) > 1:
                by_q = {r.qualified: r for r in refs}
                reason = " | ".join(f"{k}: {by_q[k].description.split('(')[0].strip().rstrip('.')}" for k in uniq)
                ambiguities.append(Ambiguity(term=term, candidates=uniq, reason=reason))

        resolved_tables = list(dict.fromkeys(matched_tables + [r.table for r in columns.values()]))
        return LinkerOutput(resolved_tables=resolved_tables, resolved_columns=list(columns.values()), ambiguities=ambiguities)
