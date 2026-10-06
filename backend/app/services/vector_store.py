"""Thin ChromaDB wrapper for the few-shot example index."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

# chromadb 0.6 telemetry is incompatible with newer posthog and only emits noise; it is already disabled.
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)


class ExampleVectorStore:
    """Persistent (or in-memory if ``path`` is None) vector index keyed by example id."""

    def __init__(self, path: Path | str | None, embedding_function, collection: str = "examples"):
        self._client = chromadb.PersistentClient(path=str(path), settings=ChromaSettings(anonymized_telemetry=False)) \
            if path else chromadb.EphemeralClient(settings=ChromaSettings(anonymized_telemetry=False))
        self._name = collection
        self._ef = embedding_function
        self._col = self._client.get_or_create_collection(collection, embedding_function=embedding_function,
                                                          metadata={"hnsw:space": "cosine"})

    def upsert(self, id: int, question: str, sql: str, query_type: str | None) -> None:  # noqa: A002
        self._col.upsert(ids=[str(id)], documents=[question],
                         metadatas=[{"sql": sql, "query_type": query_type or ""}])

    def delete(self, id: int) -> None:  # noqa: A002
        self._col.delete(ids=[str(id)])

    def count(self) -> int:
        return self._col.count()

    def ids(self) -> set[int]:
        return {int(i) for i in self._col.get()["ids"]}

    def reset(self) -> None:
        self._client.delete_collection(self._name)
        self._col = self._client.get_or_create_collection(self._name, embedding_function=self._ef,
                                                          metadata={"hnsw:space": "cosine"})

    def query(self, text: str, k: int, query_type: str | None = None) -> list[dict[str, Any]]:
        n = self.count()
        if n == 0:
            return []
        kwargs: dict[str, Any] = {"query_texts": [text], "n_results": min(k, n)}
        if query_type:
            kwargs["where"] = {"query_type": query_type}
        res = self._col.query(**kwargs) if not query_type else self._safe_filtered(kwargs, n)
        hits = []
        for id_, doc, meta, dist in zip(res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]):
            hits.append({"id": int(id_), "question": doc, "sql": meta["sql"],
                         "query_type": meta.get("query_type") or None, "score": round(min(1.0, max(0.0, 1.0 - float(dist))), 4)})
        return hits

    def _safe_filtered(self, kwargs: dict[str, Any], n: int) -> dict[str, Any]:
        """Filtered queries can return fewer rows than requested; cap n_results to the match count."""
        matches = len(self._col.get(where=kwargs["where"])["ids"])
        if matches == 0:
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
        kwargs["n_results"] = min(kwargs["n_results"], matches)
        return self._col.query(**kwargs)
