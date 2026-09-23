"""Reading clauses back out of the corpus."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from dpolens.engine.documents.models import Document, DocumentVersion
from dpolens.engine.documents.read import ClauseNotFound, get_clause, get_subtree
from dpolens.engine.packs.load import load_pack

pytestmark = pytest.mark.integration

GDPR_PACK = Path(__file__).parents[2] / "packs" / "gdpr"


@pytest.fixture
def loaded(session: Session) -> Session:
    load_pack(session, GDPR_PACK)
    session.commit()
    return session


def test_reads_a_clause_with_its_document(loaded: Session) -> None:
    detail = get_clause(loaded, "gdpr:art-17")

    assert detail.clause.label == "Article 17"
    assert detail.clause.heading == "Right to erasure (‘right to be forgotten’)"
    assert detail.clause.document_slug == "gdpr"
    assert detail.clause.effective_date == date(2018, 5, 25)
    assert detail.clause.is_normative is True
    assert detail.clause.is_authoritative is True


def test_a_breadcrumb_names_every_ancestor(loaded: Session) -> None:
    detail = get_clause(loaded, "gdpr:art-17:para-1:pt-a")

    assert [parent.key for parent in detail.breadcrumb] == [
        "gdpr:art-17",
        "gdpr:art-17:para-1",
    ]


def test_children_come_back_in_reading_order(loaded: Session) -> None:
    detail = get_clause(loaded, "gdpr:art-17:para-1")

    assert [child.label for child in detail.children][:3] == ["(a)", "(b)", "(c)"]


def test_a_subtree_is_the_clause_and_everything_under_it(loaded: Session) -> None:
    subtree = get_subtree(loaded, "gdpr:art-17")
    keys = [clause.key for clause in subtree]

    assert keys[0] == "gdpr:art-17"
    assert "gdpr:art-17:para-1:pt-f" in keys
    assert all(key.startswith("gdpr:art-17") for key in keys)
    # Reading order: a paragraph comes before its own points.
    assert keys.index("gdpr:art-17:para-1") < keys.index("gdpr:art-17:para-1:pt-a")
    assert keys.index("gdpr:art-17:para-1:pt-f") < keys.index("gdpr:art-17:para-2")


def test_cross_references_belong_to_the_clause_that_states_them(loaded: Session) -> None:
    point = get_clause(loaded, "gdpr:art-17:para-1:pt-b")
    article = get_clause(loaded, "gdpr:art-17")

    assert ("gdpr:art-6:para-1:pt-a", "point (a) of Article 6(1)") in point.cross_references
    assert article.cross_references == ()


def test_a_recital_says_it_is_not_normative(loaded: Session) -> None:
    detail = get_clause(loaded, "gdpr-recitals:rec-65")

    assert detail.clause.is_normative is False
    assert detail.clause.text.startswith("A data subject should have the right")


def test_an_unknown_key_is_refused(loaded: Session) -> None:
    with pytest.raises(ClauseNotFound, match="gdpr:art-500"):
        get_clause(loaded, "gdpr:art-500")


def test_an_unknown_document_is_refused(loaded: Session) -> None:
    with pytest.raises(ClauseNotFound, match="no document with slug"):
        get_clause(loaded, "lgpd:art-1")


def test_a_version_that_is_not_yet_effective_is_not_returned(loaded: Session) -> None:
    """A published version dated later is scheduled, not in force."""
    with pytest.raises(ClauseNotFound, match="no version in force"):
        get_clause(loaded, "gdpr:art-17", as_of=date(2017, 1, 1))


def test_a_scheduled_version_does_not_replace_the_one_in_force(loaded: Session) -> None:
    document = loaded.scalar(select(Document).where(Document.slug == "gdpr"))
    assert document is not None

    scheduled = DocumentVersion(
        document_id=document.id,
        version_number=2,
        version_label="2030 amendment",
        status="published",
        effective_date=date(2030, 1, 1),
        source_ref="pack:gdpr@2030.1",
    )
    loaded.add(scheduled)
    loaded.commit()

    # Today, the 2018 text still applies.
    assert get_clause(loaded, "gdpr:art-17").clause.effective_date == date(2018, 5, 25)
