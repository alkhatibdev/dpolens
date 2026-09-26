"""Meaning retrieval, over the vectors built from clause text.

This is the half that finds "right to erasure" from "how do I delete a user
account", and the half that will cross languages when the Arabic pack lands.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from dpolens.engine.embedding.encode import Embedder
from dpolens.engine.embedding.index import EF_SEARCH
from dpolens.engine.search.keyword import Candidate


class NoActiveModel(Exception):
    """Nothing has been indexed yet, so meaning search has nothing to search."""


def vector_search(
    session: Session,
    embedder: Embedder,
    query: str,
    limit: int = 100,
    normative_only: bool = False,
) -> list[Candidate]:
    """The clauses closest in meaning to the query, best first."""
    model_id = session.execute(
        text("SELECT id FROM embedding_models WHERE name = :name"), {"name": embedder.model.name}
    ).scalar()
    if model_id is None:
        raise NoActiveModel(
            f"{embedder.model.name} has not indexed this corpus. Run `dpolens index build` first."
        )

    vector = embedder.encode_query(query)
    session.execute(text(f"SET LOCAL hnsw.ef_search = {EF_SEARCH}"))

    rows = session.execute(
        text(
            f"""
            SELECT n.canonical_key AS key,
                   t.lang AS lang,
                   1 - (e.embedding::vector({embedder.model.dimensions}) <=> :vector) AS score
            FROM node_embeddings e
            JOIN node_texts t ON t.id = e.node_text_id
            JOIN document_nodes n ON n.id = t.node_id
            JOIN document_versions v ON v.id = n.document_version_id
            WHERE e.embedding_model_id = :model_id
              AND v.status = 'published'
              AND v.effective_date <= :as_of
              AND (NOT :normative_only OR n.is_normative)
            ORDER BY e.embedding::vector({embedder.model.dimensions}) <=> :vector
            LIMIT :limit
            """
        ),
        {
            "vector": str(vector.tolist()),
            "model_id": model_id,
            "as_of": date.today(),
            "limit": limit,
            "normative_only": normative_only,
        },
    ).all()

    return [
        Candidate(key=row.key, lang=row.lang, score=float(row.score), rank=position)
        for position, row in enumerate(rows, start=1)
    ]
