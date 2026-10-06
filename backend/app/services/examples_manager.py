"""Examples Manager: admin CRUD for few-shot pairs, kept in sync with the ChromaDB index."""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db.admin import ExampleMeta
from app.schemas.admin import ExampleIn
from app.schemas.classifier import QueryType
from app.schemas.retriever import ExampleRecord, ExampleSearchHit
from app.services.vector_store import ExampleVectorStore

log = logging.getLogger(__name__)


class ExampleNotFoundError(LookupError):
    pass


def _record(r: ExampleMeta) -> ExampleRecord:
    return ExampleRecord(id=r.id, question=r.question, sql=r.sql, query_type=QueryType(r.query_type) if r.query_type else None)


class ExamplesManager:
    """admin.db is the source of truth; the vector index is derived and updated on every write."""

    def __init__(self, admin_sessions: sessionmaker, store: ExampleVectorStore):
        self._sessions = admin_sessions
        self._store = store

    def _index(self, r: ExampleMeta) -> None:
        self._store.upsert(r.id, r.question, r.sql, r.query_type)

    def list(self) -> list[ExampleRecord]:
        with self._sessions() as s:
            return [_record(r) for r in s.scalars(select(ExampleMeta).order_by(ExampleMeta.id))]

    def get(self, id: int) -> ExampleRecord:  # noqa: A002
        with self._sessions() as s:
            r = s.get(ExampleMeta, id)
            if r is None:
                raise ExampleNotFoundError(f"Example {id} not found")
            return _record(r)

    def create(self, data: ExampleIn) -> ExampleRecord:
        with self._sessions() as s:
            r = ExampleMeta(question=data.question, sql=data.sql, query_type=data.query_type.value if data.query_type else None)
            s.add(r)
            s.commit()
            self._index(r)
            return _record(r)

    def update(self, id: int, data: ExampleIn) -> ExampleRecord:  # noqa: A002
        with self._sessions() as s:
            r = s.get(ExampleMeta, id)
            if r is None:
                raise ExampleNotFoundError(f"Example {id} not found")
            r.question, r.sql = data.question, data.sql
            r.query_type = data.query_type.value if data.query_type else None
            s.commit()
            self._index(r)  # upsert re-embeds the (possibly changed) question
            return _record(r)

    def delete(self, id: int) -> None:  # noqa: A002
        with self._sessions() as s:
            r = s.get(ExampleMeta, id)
            if r is None:
                raise ExampleNotFoundError(f"Example {id} not found")
            s.delete(r)
            s.commit()
        self._store.delete(id)

    def search(self, q: str, k: int = 5, query_type: QueryType | None = None) -> list[ExampleSearchHit]:
        hits = self._store.query(q, k, query_type.value if query_type else None)
        return [ExampleSearchHit(id=h["id"], question=h["question"], sql=h["sql"],
                                 query_type=QueryType(h["query_type"]) if h["query_type"] else None, score=h["score"])
                for h in hits]

    def in_sync(self) -> bool:
        return {e.id for e in self.list()} == self._store.ids()

    def reindex(self) -> int:
        """Rebuild the whole vector index from admin.db."""
        self._store.reset()
        with self._sessions() as s:
            rows = list(s.scalars(select(ExampleMeta)))
            for r in rows:
                self._index(r)
        return len(rows)

    def seed_from_file(self, path: Path) -> int:
        """Insert seed examples whose question is not already present. Idempotent."""
        items = json.loads(Path(path).read_text())
        existing = {e.question for e in self.list()}
        added = 0
        for it in items:
            if it["question"] in existing:
                continue
            self.create(ExampleIn(question=it["question"], sql=it["sql"], query_type=QueryType(it["query_type"])))
            added += 1
        return added


def main() -> None:
    from app.config import get_settings
    from app.db.admin import create_admin_sessionmaker
    from app.services.embeddings import create_embedding_function

    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--reindex", action="store_true", help="seed (if needed) and rebuild the vector index")
    ap.parse_args()
    st = get_settings()
    mgr = ExamplesManager(create_admin_sessionmaker(st.admin_db_path),
                          ExampleVectorStore(st.chroma_path, create_embedding_function(st.embedding_backend)))
    added = mgr.seed_from_file(st.examples_seed_path)
    n = mgr.reindex()
    print(f"Seeded {added} new examples; indexed {n} examples ({st.embedding_backend} embeddings).")


if __name__ == "__main__":
    main()
