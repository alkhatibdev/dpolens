"""Reading clauses back out of the corpus."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from dpolens.engine.documents.models import Document, DocumentVersion
from dpolens.engine.documents.read import (
    ClauseNotFound,
    get_clause,
    get_clauses,
    get_document,
    get_subtree,
    get_whole,
)
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


def test_an_outline_is_named_in_the_language_asked_for(
    session: Session, bilingual_pack: Path
) -> None:
    """A reader of the English translation finds Article (1) under its English
    name, and anyone who names no language gets the text that prevails."""
    load_pack(session, bilingual_pack)
    session.commit()

    english = get_document(session, "bilingual", lang="en").outline[0]
    prevailing = get_document(session, "bilingual").outline[0]

    assert (english.label, english.heading) == ("Article (1)", "Definitions")
    assert (prevailing.label, prevailing.heading) == ("المادة (1)", "التعاريف")
    assert get_document(session, "bilingual").summary.authoritative_language == "ar"


READ_TOGETHER = [
    "gdpr:art-17:para-1:pt-a",
    "gdpr:art-17:para-3",
    "gdpr:art-4:pt-1",
    "gdpr-recitals:rec-65",
    "gdpr:art-6:para-1:pt-f",
]


def test_clauses_read_together_read_as_each_does_alone(loaded: Session) -> None:
    """Search reads its candidates together, so each has to come back as it would alone."""
    together = get_clauses(loaded, READ_TOGETHER)

    assert list(together) == READ_TOGETHER
    for key in READ_TOGETHER:
        alone = get_clause(loaded, key)
        assert together[key].clause == alone.clause
        assert together[key].breadcrumb == alone.breadcrumb
        assert together[key].cross_references == alone.cross_references
        assert together[key].children == ()


def test_clauses_read_together_leave_out_what_is_not_in_force(loaded: Session) -> None:
    assert list(get_clauses(loaded, ["gdpr:art-17", "gdpr:art-999", "lgpd:art-1"])) == [
        "gdpr:art-17"
    ]
    assert get_clauses(loaded, ["gdpr:art-17"], as_of=date(2017, 1, 1)) == {}


def test_clauses_read_together_in_each_language_of_a_law(
    session: Session, bilingual_pack: Path
) -> None:
    load_pack(session, bilingual_pack)
    session.commit()
    keys = [key for key in (view.key for view in get_subtree(session, "bilingual:art-1"))]

    for lang in ("en", "ar", None):
        together = get_clauses(session, keys, lang=lang)
        for key in keys:
            assert together[key].clause == get_clause(session, key, lang=lang).clause


def test_a_whole_clause_is_its_subtree_with_its_links(loaded: Session) -> None:
    whole = get_whole(loaded, "gdpr:art-17:para-1")
    subtree = get_subtree(loaded, "gdpr:art-17:para-1")

    assert [whole.clause, *whole.beneath] == subtree
    assert whole.breadcrumb == get_clause(loaded, "gdpr:art-17:para-1").breadcrumb
    for clause in subtree:
        assert whole.cross_references.get(clause.key, ()) == (
            get_clause(loaded, clause.key).cross_references
        )
