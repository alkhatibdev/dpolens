"""Building the vector index over the corpus.

Every clause with text gets one vector per model. Clauses without text, such as
an article that only holds paragraphs, are skipped: an empty string embeds to a
vector that matches everything weakly and drags on every query.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from dpolens.engine.embedding.encode import Embedder
from dpolens.engine.embedding.models import EmbeddingModel
from dpolens.engine.embedding.recipe import RECIPE_VERSION, RecipeInput, build

BATCH = 64

# Chosen so the index is not what loses recall, and measured against a
# brute-force scan in the evals.
HNSW_M = 16
HNSW_EF_CONSTRUCTION = 64
EF_SEARCH = 100


@dataclass(frozen=True)
class IndexResult:
    model: str
    recipe: str
    embedded: int
    skipped_without_text: int


def register_model(session: Session, model: EmbeddingModel, activate: bool = True) -> uuid.UUID:
    """Record the model, and make it the one queries use."""
    existing = session.execute(
        text("SELECT id FROM embedding_models WHERE name = :name"), {"name": model.name}
    ).scalar()
    model_id = existing or uuid.uuid4()

    if existing is None:
        session.execute(
            text(
                "INSERT INTO embedding_models (id, name, dimensions, is_active) "
                "VALUES (:id, :name, :dimensions, false)"
            ),
            {"id": model_id, "name": model.name, "dimensions": model.dimensions},
        )

    if activate:
        session.execute(text("UPDATE embedding_models SET is_active = false WHERE is_active"))
        session.execute(
            text("UPDATE embedding_models SET is_active = true WHERE id = :id"), {"id": model_id}
        )
    return uuid.UUID(str(model_id))


def build_index(session: Session, embedder: Embedder, activate: bool = True) -> IndexResult:
    """Embed every clause that has text, then build the vector index."""
    model_id = register_model(session, embedder.model, activate=activate)

    rows = session.execute(
        text(
            """
            SELECT t.id AS text_id, t.body_text, t.heading, d.title AS document_title,
                   n.canonical_key, n.id AS node_id
            FROM node_texts t
            JOIN document_nodes n ON n.id = t.node_id
            JOIN document_versions v ON v.id = n.document_version_id
            JOIN documents d ON d.id = v.document_id
            WHERE v.status = 'published' AND length(trim(t.body_text)) > 0
            ORDER BY n.canonical_key
            """
        )
    ).all()

    skipped = session.execute(
        text("SELECT count(*) FROM node_texts WHERE length(trim(body_text)) = 0")
    ).scalar_one()

    embedded = 0
    for start in range(0, len(rows), BATCH):
        chunk = rows[start : start + BATCH]
        strings = [
            build(
                RecipeInput(
                    document_short_name=row.document_title,
                    ancestor_headings=_ancestor_headings(session, row.node_id),
                    text=row.body_text,
                ),
                embedder.count_tokens,
            )
            for row in chunk
        ]
        vectors = embedder.encode_passages(strings)

        session.execute(
            text(
                """
                INSERT INTO node_embeddings
                    (node_text_id, embedding_model_id, context_recipe, embedded_string, embedding)
                VALUES (:text_id, :model_id, :recipe, :embedded_string, :embedding)
                ON CONFLICT (node_text_id, embedding_model_id) DO UPDATE
                SET context_recipe = EXCLUDED.context_recipe,
                    embedded_string = EXCLUDED.embedded_string,
                    embedding = EXCLUDED.embedding
                """
            ),
            [
                {
                    "text_id": row.text_id,
                    "model_id": model_id,
                    "recipe": RECIPE_VERSION,
                    "embedded_string": string,
                    "embedding": str(vector.tolist()),
                }
                for row, string, vector in zip(chunk, strings, vectors, strict=True)
            ],
        )
        embedded += len(chunk)

    _create_index(session, model_id, embedder.model.dimensions)

    return IndexResult(
        model=embedder.model.name,
        recipe=RECIPE_VERSION,
        embedded=embedded,
        skipped_without_text=int(skipped),
    )


def _ancestor_headings(session: Session, node_id: uuid.UUID) -> list[str]:
    """The headings above a clause, outermost first."""
    rows = session.execute(
        text(
            """
            WITH RECURSIVE up AS (
                SELECT id, parent_node_id, 0 AS depth FROM document_nodes WHERE id = :node_id
                UNION ALL
                SELECT n.id, n.parent_node_id, up.depth + 1
                FROM document_nodes n JOIN up ON n.id = up.parent_node_id
            )
            SELECT coalesce(t.heading, n.label) AS heading
            FROM up
            JOIN document_nodes n ON n.id = up.id
            LEFT JOIN node_texts t ON t.node_id = n.id
            WHERE up.depth > 0
            ORDER BY up.depth DESC
            """
        ),
        {"node_id": node_id},
    ).all()
    return [row.heading for row in rows if row.heading]


def _create_index(session: Session, model_id: uuid.UUID, dimensions: int) -> None:
    """One index per model, built after the rows are in, which is far faster."""
    name = f"node_embeddings_hnsw_{str(model_id).replace('-', '')}"
    session.execute(
        text(
            f"""
            CREATE INDEX IF NOT EXISTS {name} ON node_embeddings
            USING hnsw ((embedding::vector({dimensions})) vector_cosine_ops)
            WITH (m = {HNSW_M}, ef_construction = {HNSW_EF_CONSTRUCTION})
            WHERE embedding_model_id = '{model_id}'
            """
        )
    )
