"""Examples Retriever: top-k similar (question -> SQL) pairs from the vector index."""
from __future__ import annotations

from app.schemas.retriever import Example, RetrieverInput, RetrieverOutput
from app.services.vector_store import ExampleVectorStore


class ExamplesRetriever:
    def __init__(self, store: ExampleVectorStore):
        self._store = store

    def retrieve(self, inp: RetrieverInput) -> RetrieverOutput:
        """Top-k by similarity. If ``query_type`` is given, same-type examples rank first and
        the remainder is filled from the unfiltered ranking so we always return up to k."""
        chosen: list[dict] = []
        if inp.query_type:
            chosen = self._store.query(inp.question, inp.top_k, inp.query_type.value)
        if len(chosen) < inp.top_k:
            seen = {h["id"] for h in chosen}
            chosen += [h for h in self._store.query(inp.question, inp.top_k) if h["id"] not in seen][: inp.top_k - len(chosen)]
        return RetrieverOutput(examples=[Example(question=h["question"], sql=h["sql"]) for h in chosen])
