"""Loading a pack into the corpus."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from dpolens.engine.documents.models import (
    Document,
    DocumentNode,
    DocumentVersion,
    NodeReference,
    NodeText,
)
from dpolens.engine.packs.load import load_pack

pytestmark = pytest.mark.integration


def test_loads_every_document_in_the_pack(session: Session, testlaw_pack: Path) -> None:
    result = load_pack(session, testlaw_pack)
    session.commit()

    assert result.documents_loaded == 2
    assert result.clauses_loaded == 8  # 2 articles, 3 paragraphs, 2 points, 1 recital
    assert result.already_loaded is False

    slugs = session.scalars(select(Document.slug).order_by(Document.slug)).all()
    assert list(slugs) == ["testlaw", "testlaw-recitals"]


def test_stores_the_clause_tree(session: Session, testlaw_pack: Path) -> None:
    load_pack(session, testlaw_pack)
    session.commit()

    point = session.scalar(
        select(DocumentNode).where(DocumentNode.canonical_key == "testlaw:art-5:para-1:pt-b")
    )
    assert point is not None
    assert point.depth == 2
    assert point.label == "(b)"
    assert point.node_type == "point"

    parent = session.get(DocumentNode, point.parent_node_id)
    assert parent is not None
    assert parent.canonical_key == "testlaw:art-5:para-1"


def test_stores_text_verbatim_with_its_language(session: Session, testlaw_pack: Path) -> None:
    load_pack(session, testlaw_pack)
    session.commit()

    text = session.scalar(
        select(NodeText)
        .join(DocumentNode)
        .where(DocumentNode.canonical_key == "testlaw:art-5:para-1:pt-a")
    )
    assert text is not None
    assert text.body_text == "where there is no other legal ground for the processing;"
    assert text.lang == "en"
    assert text.is_authoritative is True
    assert text.translation_status == "original"


def test_marks_recitals_as_non_normative(session: Session, testlaw_pack: Path) -> None:
    load_pack(session, testlaw_pack)
    session.commit()

    recital = session.scalar(
        select(DocumentNode).where(DocumentNode.canonical_key == "testlaw-recitals:rec-12")
    )
    article = session.scalar(
        select(DocumentNode).where(DocumentNode.canonical_key == "testlaw:art-5")
    )

    assert recital is not None and recital.is_normative is False
    assert article is not None and article.is_normative is True


def test_stores_cross_references(session: Session, testlaw_pack: Path) -> None:
    load_pack(session, testlaw_pack)
    session.commit()

    reference = session.scalar(
        select(NodeReference)
        .join(DocumentNode)
        .where(DocumentNode.canonical_key == "testlaw:art-5")
    )
    assert reference is not None
    assert reference.to_canonical_key == "testlaw:art-6:para-1"
    assert reference.raw_text == "Article 6(1)"


def test_versions_are_published_and_dated(session: Session, testlaw_pack: Path) -> None:
    load_pack(session, testlaw_pack)
    session.commit()

    version = session.scalar(
        select(DocumentVersion).join(Document).where(Document.slug == "testlaw")
    )
    assert version is not None
    assert version.status == "published"
    assert version.version_number == 1
    assert version.effective_date.isoformat() == "2026-01-01"
    assert version.source_ref == "pack:testlaw@2026.1"


def test_loading_the_same_pack_version_twice_changes_nothing(
    session: Session, testlaw_pack: Path
) -> None:
    load_pack(session, testlaw_pack)
    session.commit()

    second = load_pack(session, testlaw_pack)
    session.commit()

    assert second.already_loaded is True
    assert second.clauses_loaded == 0

    versions = session.scalars(select(DocumentVersion)).all()
    assert len(versions) == 2  # one per document, not four
