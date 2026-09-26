"""Embedding the corpus, and finding clauses by meaning."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from dpolens.engine.embedding import Embedder, get_model
from dpolens.engine.embedding.index import build_index
from dpolens.engine.packs.load import load_pack
from dpolens.engine.search.vector import NoActiveModel, vector_search

pytestmark = pytest.mark.integration

MODEL = "e5-small"


@pytest.fixture(scope="session")
def embedder() -> Iterator[Embedder]:
    """One loaded model for the whole session: loading it costs seconds."""
    with Embedder(get_model(MODEL)) as loaded:
        yield loaded


@pytest.fixture
def indexed(session: Session, testlaw_pack: Path, embedder: Embedder) -> Session:
    load_pack(session, testlaw_pack)
    session.commit()
    build_index(session, embedder)
    session.commit()
    return session


def test_only_clauses_with_text_are_embedded(indexed: Session) -> None:
    """An empty string embeds to a vector that matches everything weakly."""
    embedded, embeddable = indexed.execute(
        text(
            """
            SELECT (SELECT count(*) FROM node_embeddings),
                   (SELECT count(*) FROM node_texts WHERE length(trim(body_text)) > 0)
            """
        )
    ).one()

    assert embedded == embeddable
    assert (
        indexed.execute(
            text(
                """
            SELECT count(*) FROM node_embeddings e
            JOIN node_texts t ON t.id = e.node_text_id
            WHERE length(trim(t.body_text)) = 0
            """
            )
        ).scalar_one()
        == 0
    )


def test_the_stored_string_carries_the_ancestry_and_the_prefix(indexed: Session) -> None:
    stored = indexed.execute(
        text(
            """
            SELECT e.embedded_string, e.context_recipe
            FROM node_embeddings e
            JOIN node_texts t ON t.id = e.node_text_id
            JOIN document_nodes n ON n.id = t.node_id
            WHERE n.canonical_key = 'testlaw:art-5:para-1:pt-a'
            """
        )
    ).one()

    assert stored.embedded_string.startswith("Test Data Protection Law > Right to erasure")
    assert stored.embedded_string.endswith("no other legal ground for the processing;")
    assert stored.context_recipe == "v1"


def test_the_passage_prefix_is_applied_at_encoding(embedder: Embedder) -> None:
    """e5 loses accuracy without its prefixes, and nothing errors when they are
    missing, so this is asserted rather than assumed."""
    assert embedder.model.passage_prefix == "passage: "
    assert embedder.model.query_prefix == "query: "


def test_vectors_are_unit_length_and_the_right_width(indexed: Session, embedder: Embedder) -> None:
    dimensions, norm = indexed.execute(
        text(
            f"""
            SELECT vector_dims(embedding::vector({embedder.model.dimensions})),
                   round((embedding::vector({embedder.model.dimensions})
                          <#> embedding::vector({embedder.model.dimensions}))::numeric, 3)
            FROM node_embeddings LIMIT 1
            """
        )
    ).one()

    assert dimensions == embedder.model.dimensions
    # <#> is negative inner product, so a unit vector against itself is -1.
    assert float(norm) == -1.0


def test_meaning_search_finds_a_clause_the_words_do_not_match(
    indexed: Session, embedder: Embedder
) -> None:
    """The fixture's erasure clause never says "delete"."""
    results = vector_search(indexed, embedder, "how do I delete someone's account", limit=3)

    assert "testlaw:art-5:para-1" in [candidate.key for candidate in results]


def test_scores_descend_and_are_similarities(indexed: Session, embedder: Embedder) -> None:
    results = vector_search(indexed, embedder, "erasure of personal data", limit=5)
    scores = [candidate.score for candidate in results]

    assert scores == sorted(scores, reverse=True)
    assert all(-1.0 <= score <= 1.0 for score in scores)


def test_searching_before_indexing_says_so(session: Session, embedder: Embedder) -> None:
    with pytest.raises(NoActiveModel, match="index build"):
        vector_search(session, embedder, "anything", limit=3)


def test_rebuilding_replaces_vectors_rather_than_duplicating(
    indexed: Session, embedder: Embedder
) -> None:
    before = indexed.execute(text("SELECT count(*) FROM node_embeddings")).scalar_one()

    build_index(indexed, embedder)
    indexed.commit()

    assert indexed.execute(text("SELECT count(*) FROM node_embeddings")).scalar_one() == before
