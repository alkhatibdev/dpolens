"""Meaning retrieval, over the vectors built from clause text.

This is the half that finds "right to erasure" from "how do I delete a user
account", and the half that crosses languages: every text of a clause is embedded,
so a question can reach a clause through whichever of its texts is closer.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from dpolens.engine.embedding.encode import Embedder
from dpolens.engine.embedding.index import EF_SEARCH
from dpolens.engine.search.keyword import Candidate, scoped


class NoActiveModel(Exception):
    """Nothing has been indexed yet, so meaning search has nothing to search."""


def vector_search(
    session: Session,
    embedder: Embedder,
    query: str,
    limit: int = 100,
    normative_only: bool = False,
    packs: Sequence[str] | None = None,
) -> list[Candidate]:
    """The clauses closest in meaning to the query, best first, each once.

    `packs` keeps the search to those laws and the organisation's own policies.
    """
    model_id = session.execute(
        text("SELECT id FROM embedding_models WHERE name = :name"), {"name": embedder.model.name}
    ).scalar()
    if model_id is None:
        raise NoActiveModel(
            f"{embedder.model.name} has not indexed this corpus. Run `dpolens index build` first."
        )

    vector = embedder.encode_query(query)
    session.execute(text(f"SET LOCAL hnsw.ef_search = {EF_SEARCH}"))
    # The index finds the nearest vectors first and the filter runs after it, so a
    # search kept to some laws could end with fewer candidates than it asked for.
    # An iterative scan goes on until enough pass. Set either way, because SET
    # LOCAL lasts for the transaction and the next search may not be kept.
    session.execute(
        text(f"SET LOCAL hnsw.iterative_scan = {'strict_order' if packs is not None else 'off'}")
    )
    scope_join, scope_condition = scoped(packs)

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
            {scope_join}
            WHERE e.embedding_model_id = :model_id
              AND v.status = 'published'
              AND v.effective_date <= :as_of
              AND (NOT :normative_only OR n.is_normative)
              {scope_condition}
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
            **({"packs": list(packs)} if packs is not None else {}),
        },
    ).all()

    # Every text of a clause is embedded, so a law with a translation has two rows
    # per clause. It is one candidate, at its closest text: counting both would rank
    # a translated law above one with a single text for no better reason.
    candidates: list[Candidate] = []
    seen: set[str] = set()
    for row in rows:
        if row.key in seen:
            continue
        seen.add(row.key)
        candidates.append(
            Candidate(key=row.key, lang=row.lang, score=float(row.score), rank=len(candidates) + 1)
        )
    return candidates
