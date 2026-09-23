"""The GDPR pack in this repository, loaded the way an instance loads it."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dpolens.engine.documents.models import Document, DocumentNode, NodeReference, NodeText
from dpolens.engine.packs.load import load_pack

pytestmark = pytest.mark.integration

GDPR_PACK = Path(__file__).parents[2] / "packs" / "gdpr"


@pytest.fixture
def loaded(session: Session) -> Session:
    load_pack(session, GDPR_PACK)
    session.commit()
    return session


def test_loads_the_articles_and_the_recitals(loaded: Session) -> None:
    articles = loaded.scalar(
        select(func.count()).select_from(DocumentNode).where(DocumentNode.node_type == "article")
    )
    recitals = loaded.scalar(
        select(func.count()).select_from(DocumentNode).where(DocumentNode.node_type == "recital")
    )

    assert articles == 99
    assert recitals == 173


def test_article_17_reads_as_published(loaded: Session) -> None:
    node = loaded.scalar(select(DocumentNode).where(DocumentNode.canonical_key == "gdpr:art-17"))
    assert node is not None
    assert node.label == "Article 17"

    heading = loaded.scalar(select(NodeText.heading).where(NodeText.node_id == node.id))
    assert heading == "Right to erasure (‘right to be forgotten’)"

    point = loaded.scalar(
        select(NodeText.body_text)
        .join(DocumentNode)
        .where(DocumentNode.canonical_key == "gdpr:art-17:para-1:pt-a")
    )
    assert point == (
        "the personal data are no longer necessary in relation to the purposes for "
        "which they were collected or otherwise processed;"
    )


def test_definitions_keep_their_own_keys(loaded: Session) -> None:
    """Article 4 has no numbered paragraphs, and its definitions are cited by number."""
    consent = loaded.scalar(
        select(NodeText.body_text)
        .join(DocumentNode)
        .where(DocumentNode.canonical_key == "gdpr:art-4:pt-11")
    )

    assert consent is not None
    assert consent.startswith("‘consent’ of the data subject means")


def test_recitals_are_marked_non_normative(loaded: Session) -> None:
    recital = loaded.scalar(
        select(DocumentNode).where(DocumentNode.canonical_key == "gdpr-recitals:rec-1")
    )
    article = loaded.scalar(select(DocumentNode).where(DocumentNode.canonical_key == "gdpr:art-1"))

    assert recital is not None and recital.is_normative is False
    assert article is not None and article.is_normative is True


def test_cross_references_point_inside_the_law(loaded: Session) -> None:
    targets = loaded.scalars(select(NodeReference.to_canonical_key)).all()
    known = set(loaded.scalars(select(DocumentNode.canonical_key)).all())

    assert targets, "the pack should carry the references its text states"
    assert set(targets) <= known, "every stored link resolves to a clause in this pack"


def test_both_documents_are_one_pack_version(loaded: Session) -> None:
    slugs = loaded.scalars(select(Document.slug).order_by(Document.slug)).all()

    assert list(slugs) == ["gdpr", "gdpr-recitals"]
