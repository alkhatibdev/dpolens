"""Building the vector index over the corpus.

Every clause with text gets one vector per model. Clauses without text, such as
an article that only holds paragraphs, are skipped: an empty string embeds to a
vector that matches everything weakly and drags on every query.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from dpolens.engine.embedding.encode import Embedder
from dpolens.engine.embedding.models import EmbeddingModel
from dpolens.engine.embedding.recipe import RECIPE_VERSION, RecipeInput, build

# How much one batch may hold, as its clauses times the square of the longest, which is how the
# memory for attention grows: 64 clauses of 64 tokens, 16 of 128, or one of 512.
BATCH_BUDGET = 64 * 64 * 64

# Chosen so the index is not what loses recall, and measured against a
# brute-force scan in the evals.
HNSW_M = 16
HNSW_EF_CONSTRUCTION = 64
EF_SEARCH = 100

# The clauses a model embeds: every one with text, in a published version.
_PUBLISHED_TEXT = """
    FROM node_texts t
    JOIN document_nodes n ON n.id = t.node_id
    JOIN document_versions v ON v.id = n.document_version_id
    JOIN documents d ON d.id = v.document_id
    WHERE v.status = 'published' AND length(trim(t.body_text)) > 0
"""
# Of those, the ones a model has not embedded under the current recipe.
_NOT_EMBEDDED = """
    AND NOT EXISTS (
        SELECT 1 FROM node_embeddings e
        WHERE e.node_text_id = t.id
          AND e.embedding_model_id = :model_id
          AND e.context_recipe = :recipe
    )
"""


@dataclass(frozen=True)
class IndexResult:
    model: str
    recipe: str
    embedded: int
    skipped_without_text: int
    skipped_already_embedded: int = 0


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


def build_index(
    session: Session,
    embedder: Embedder,
    activate: bool = True,
    skip_embedded: bool = False,
    create_index: bool = True,
) -> IndexResult:
    """Embed every clause that has text, then build the vector index.

    With `skip_embedded`, a clause this model has already embedded under the
    current recipe is left alone. That makes a second run cheap, which is what an
    instance restarting wants, and it is why the recipe is part of the condition:
    a change to the recipe has to embed everything again.

    Without `create_index`, the index is left as it is: Postgres adds each new
    vector to it, and creating one needs the role that owns the table, which the
    worker embedding a newly published policy does not hold.
    """
    model_id = register_model(session, embedder.model, activate=activate)

    rows = session.execute(
        text(
            f"""
            SELECT t.id AS text_id, t.body_text, t.heading, t.lang, d.title AS document_title,
                   n.canonical_key, n.id AS node_id
            {_PUBLISHED_TEXT}
            {_NOT_EMBEDDED if skip_embedded else ""}
            ORDER BY n.canonical_key
            """
        ),
        {"model_id": model_id, "recipe": RECIPE_VERSION} if skip_embedded else {},
    ).all()

    already = (
        session.execute(
            text(
                """
                SELECT count(*) FROM node_embeddings
                WHERE embedding_model_id = :model_id AND context_recipe = :recipe
                """
            ),
            {"model_id": model_id, "recipe": RECIPE_VERSION},
        ).scalar_one()
        if skip_embedded
        else 0
    )

    skipped = session.execute(
        text("SELECT count(*) FROM node_texts WHERE length(trim(body_text)) = 0")
    ).scalar_one()

    strings = [
        build(
            RecipeInput(
                document_short_name=row.document_title,
                ancestor_headings=_ancestor_headings(session, row.node_id, row.lang),
                text=row.body_text,
            ),
            embedder.count_tokens,
        )
        for row in rows
    ]

    embedded = 0
    for batch in batches([embedder.passage_tokens(string) for string in strings]):
        vectors = embedder.encode_passages([strings[at] for at in batch])

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
                    "text_id": rows[at].text_id,
                    "model_id": model_id,
                    "recipe": RECIPE_VERSION,
                    "embedded_string": strings[at],
                    "embedding": str(vector.tolist()),
                }
                for at, vector in zip(batch, vectors, strict=True)
            ],
        )
        embedded += len(batch)

    if create_index:
        _create_index(session, model_id, embedder.model.dimensions)

    return IndexResult(
        model=embedder.model.name,
        recipe=RECIPE_VERSION,
        embedded=embedded,
        skipped_without_text=int(skipped),
        skipped_already_embedded=int(already),
    )


def unembedded(session: Session, model: EmbeddingModel) -> int:
    """How many clauses `build_index` with `skip_embedded` would embed, counted without the
    model, so that a caller with nothing to embed need not load it."""
    model_id = session.execute(
        text("SELECT id FROM embedding_models WHERE name = :name"), {"name": model.name}
    ).scalar()
    if model_id is None:
        return int(session.execute(text(f"SELECT count(*) {_PUBLISHED_TEXT}")).scalar_one())
    return int(
        session.execute(
            text(f"SELECT count(*) {_PUBLISHED_TEXT} {_NOT_EMBEDDED}"),
            {"model_id": model_id, "recipe": RECIPE_VERSION},
        ).scalar_one()
    )


def batches(tokens: Sequence[int]) -> list[list[int]]:
    """The strings' positions in batches of similar length, shortest first.

    A batch is padded to its longest string. In key order, a clause of twenty tokens would be
    padded to the 512 of a long article beside it, and most of what the model reads would be
    padding. Sorted, a batch holds strings of about one length, and the budget keeps the
    longest few in small batches of their own, which bounds the memory any batch needs.
    """
    found: list[list[int]] = []
    batch: list[int] = []
    for at in sorted(range(len(tokens)), key=lambda position: tokens[position]):
        # Sorted, so this string is the longest the batch would hold.
        if batch and (len(batch) + 1) * tokens[at] ** 2 > BATCH_BUDGET:
            found.append(batch)
            batch = []
        batch.append(at)
    if batch:
        found.append(batch)
    return found


def _ancestor_headings(session: Session, node_id: uuid.UUID, lang: str) -> list[str]:
    """The headings above a clause, outermost first, in the language of its text."""
    rows = session.execute(
        text(
            """
            WITH RECURSIVE up AS (
                SELECT id, parent_node_id, 0 AS depth FROM document_nodes WHERE id = :node_id
                UNION ALL
                SELECT n.id, n.parent_node_id, up.depth + 1
                FROM document_nodes n JOIN up ON n.id = up.parent_node_id
            )
            SELECT coalesce(t.heading, t.label, n.label) AS heading
            FROM up
            JOIN document_nodes n ON n.id = up.id
            LEFT JOIN node_texts t ON t.node_id = n.id AND t.lang = :lang
            WHERE up.depth > 0
            ORDER BY up.depth DESC
            """
        ),
        {"node_id": node_id, "lang": lang},
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
