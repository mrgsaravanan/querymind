"""Semantic cache: embedding-similarity lookup of previously answered questions.

Only the *SQL* (plus explanation/summary) is cached; on a hit the pipeline still re-validates the SQL against the
current guardrails and re-executes it, so results are always fresh and a stale cache can never bypass a safety rule.
The cache key space is partitioned by a context hash (model config, guardrails, schema, sensitive flags): any admin
change that could alter the right answer silently invalidates earlier entries.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings

log = logging.getLogger(__name__)


@dataclass
class CacheHit:
    question: str
    sql: str
    explanation: str
    query_type: str | None
    summary: str
    signature: str
    score: float


def rows_signature(rows: list) -> str:
    return hashlib.sha1(json.dumps(rows, default=str, sort_keys=True).encode()).hexdigest()


def context_hash(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, default=str, sort_keys=True).encode()).hexdigest()[:16]


class SemanticCache:
    def __init__(self, path: Path | str | None, embedding_function, threshold: float = 0.95, collection: str = "query_cache"):
        settings = ChromaSettings(anonymized_telemetry=False)
        self._client = chromadb.PersistentClient(path=str(path), settings=settings) if path else chromadb.EphemeralClient(settings=settings)
        self._col = self._client.get_or_create_collection(collection, embedding_function=embedding_function, metadata={"hnsw:space": "cosine"})
        self.threshold = threshold

    @staticmethod
    def _norm(q: str) -> str:
        return re.sub(r"\s+", " ", q.strip().lower())

    def get(self, question: str, ctx: str) -> CacheHit | None:
        try:
            res = self._col.query(query_texts=[self._norm(question)], n_results=1, where={"ctx": ctx})
        except Exception:  # noqa: BLE001 - empty collection / no entries for this ctx
            return None
        if not res["ids"] or not res["ids"][0]:
            return None
        score = 1.0 - float(res["distances"][0][0])
        if score < self.threshold:
            return None
        m = res["metadatas"][0][0]
        return CacheHit(res["documents"][0][0], m["sql"], m.get("explanation", ""), m.get("query_type") or None,
                        m.get("summary", ""), m.get("signature", ""), round(score, 4))

    def put(self, question: str, ctx: str, *, sql: str, explanation: str, query_type: str | None, summary: str, signature: str) -> None:
        key = hashlib.sha1(f"{ctx}|{self._norm(question)}".encode()).hexdigest()
        self._col.upsert(ids=[key], documents=[self._norm(question)],
                         metadatas=[{"ctx": ctx, "sql": sql, "explanation": explanation, "query_type": query_type or "",
                                     "summary": summary, "signature": signature}])

    def count(self) -> int:
        return self._col.count()

    def clear(self) -> None:
        ids = self._col.get()["ids"]
        if ids:
            self._col.delete(ids=ids)
