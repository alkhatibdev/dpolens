"""A law named in the language of its text, and each text read on the days it applies.

The fixture law here starts in stages, has a provision no date has been set for, one a law
has ended, and an article an amendment rewrites from a later day, the four patterns the
packs DPOLens is asked for show between them.
"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from dpolens.engine.documents.models import Document
from dpolens.engine.documents.read import (
    ClauseNotFound,
    get_clause,
    get_document,
    list_documents,
    list_laws,
)
from dpolens.engine.logs.governance import Actor
from dpolens.engine.originals import Directory
from dpolens.engine.packs.load import load_pack
from dpolens.engine.policies.store import upload_policy
from dpolens.engine.search import keyword_search

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parents[1] / "fixtures" / "policies"

COMMENCEMENT = """    commencement:
      - from: 2999-01-01
        keys: [testlaw:art-5:para-2]
        source: Commencement Notice No. 1
      - from: pending
        keys: [testlaw:art-5:para-1:pt-b]
        source: Section 1(2), on a day the Minister appoints
      - until: 2026-06-01
        keys: [testlaw:art-5:para-1:pt-a]
        source: Repealing Act 2025, section 3
"""

IN_FORCE = "Processing shall be lawful only if and to the extent that consent has been given."

AMENDED = """---
key: testlaw:art-6
title: Lawfulness of processing
lang: en
source: Amending Act 2026, section 4
---

## 1. {#para-1}

Processing shall be lawful only where a ground set out in the Schedule applies.

## 2. {#para-2}

Consent shall be as easy to withdraw as to give, and its withdrawal shall be recorded.
"""


@pytest.fixture
def staged(session: Session, testlaw_pack: Path, tmp_path: Path) -> Session:
    pack = Path(shutil.copytree(testlaw_pack, tmp_path / "testlaw"))
    metadata = pack / "pack.yaml"
    metadata.write_text(
        metadata.read_text(encoding="utf-8").replace(
            "    expected_clauses: 2\n", "    expected_clauses: 2\n" + COMMENCEMENT, 1
        ),
        encoding="utf-8",
    )
    (pack / "testlaw" / "art-6@2999-06-01.md").write_text(AMENDED, encoding="utf-8")
    load_pack(session, pack)
    session.commit()
    return session


class TestNames:
    @pytest.fixture
    def loaded(self, session: Session, bilingual_pack: Path) -> Session:
        load_pack(session, bilingual_pack)
        session.commit()
        return session

    def test_a_clause_names_its_law_in_its_own_language(self, loaded: Session) -> None:
        arabic = get_clause(loaded, "bilingual:art-1", lang="ar").clause
        english = get_clause(loaded, "bilingual:art-1", lang="en").clause

        assert (arabic.document_title, arabic.law_short_name, arabic.jurisdiction) == (
            "قانون تجريبي ثنائي اللغة",
            "القانون التجريبي",
            "جمهورية المثال",
        )
        assert (english.document_title, english.law_short_name, english.jurisdiction) == (
            "Test Bilingual Law",
            "BILINGUAL",
            "Example Republic",
        )

    def test_a_list_names_it_in_every_language(self, loaded: Session) -> None:
        [document], _ = list_documents(loaded)
        [law] = list_laws(loaded)

        assert document.title == {"ar": "قانون تجريبي ثنائي اللغة", "en": "Test Bilingual Law"}
        assert document.short_name == {"ar": "القانون التجريبي", "en": "BILINGUAL"}
        assert law.name["en"] == "Test Bilingual Law"
        assert law.region == "Middle East"
        assert get_document(loaded, "bilingual").summary.jurisdiction == {
            "ar": "جمهورية المثال",
            "en": "Example Republic",
        }

    def test_a_policy_s_title_is_filed_under_the_language_of_its_text(
        self, session: Session, tmp_path: Path
    ) -> None:
        upload_policy(
            session,
            Directory(tmp_path),
            (FIXTURES / "arabic-sections.docx").read_bytes(),
            "arabic-sections.docx",
            actor=Actor(via="cli", identity={"os_user": "tests", "host": "ci"}),
            slug="arabic-sections",
            title="سياسة حماية البيانات",
        )
        document = session.scalar(select(Document).where(Document.slug == "arabic-sections"))

        assert document is not None
        assert [(title.lang, title.title) for title in document.titles] == [
            ("ar", "سياسة حماية البيانات")
        ]


class TestDates:
    def test_a_provision_in_force_says_since_when(self, staged: Session) -> None:
        clause = get_clause(staged, "testlaw:art-5:para-1").clause

        assert clause.in_force is True
        assert clause.in_force_from == date(2026, 1, 1)
        assert (clause.in_force_until, clause.dates_set_by, clause.coming) == (None, None, None)

    def test_a_provision_that_starts_later_reads_marked(self, staged: Session) -> None:
        clause = get_clause(staged, "testlaw:art-5:para-2").clause

        assert clause.in_force is False
        assert clause.in_force_from == date(2999, 1, 1)
        assert clause.dates_set_by == "Commencement Notice No. 1"
        assert get_clause(staged, "testlaw:art-5:para-2", as_of=date(2999, 1, 1)).clause.in_force

    def test_a_provision_with_no_day_set_says_so(self, staged: Session) -> None:
        clause = get_clause(staged, "testlaw:art-5:para-1:pt-b").clause

        assert (clause.in_force, clause.in_force_from) == (False, None)
        assert clause.dates_set_by == "Section 1(2), on a day the Minister appoints"

    def test_a_provision_a_law_ended_still_reads_by_key_and_is_not_searched(
        self, staged: Session
    ) -> None:
        clause = get_clause(staged, "testlaw:art-5:para-1:pt-a").clause
        words = "no other legal ground for the processing"
        today = keyword_search(staged, words, limit=10)
        then = keyword_search(staged, words, limit=10, as_of=date(2026, 3, 1))

        assert (clause.in_force, clause.in_force_until) == (False, date(2026, 6, 1))
        assert "testlaw:art-5:para-1:pt-a" not in [candidate.key for candidate in today]
        # Asked about a day it still applied, it is an answer.
        assert "testlaw:art-5:para-1:pt-a" in [candidate.key for candidate in then]

    def test_the_words_in_force_carry_the_words_an_amendment_brings(self, staged: Session) -> None:
        today = get_clause(staged, "testlaw:art-6:para-1").clause
        then = get_clause(staged, "testlaw:art-6:para-1", as_of=date(2999, 6, 1)).clause

        assert today.text == IN_FORCE
        assert (today.in_force, today.in_force_until) == (True, date(2999, 6, 1))
        assert today.coming is not None
        assert today.coming.text.startswith("Processing shall be lawful only where a ground")
        assert today.coming.in_force_from == date(2999, 6, 1)
        assert today.coming.dates_set_by == "Amending Act 2026, section 4"
        assert then.text == today.coming.text
        assert (then.in_force, then.coming) == (True, None)

    def test_a_clause_an_amendment_adds_is_found_before_it_applies(self, staged: Session) -> None:
        found = keyword_search(staged, "withdrawal shall be recorded", limit=10)
        added = get_clause(staged, "testlaw:art-6:para-2").clause

        assert "testlaw:art-6:para-2" in [candidate.key for candidate in found]
        assert (added.in_force, added.in_force_from) == (False, date(2999, 6, 1))

    def test_an_outline_names_a_clause_by_the_words_in_force(self, staged: Session) -> None:
        outline = get_document(staged, "testlaw").outline

        assert [(item.key, item.heading) for item in outline] == [
            ("testlaw:art-5", "Right to erasure"),
            ("testlaw:art-6", "Lawfulness of processing"),
        ]


def test_a_provision_amended_before_it_starts_keeps_its_day_with_the_amended_words(
    session: Session, testlaw_pack: Path, tmp_path: Path
) -> None:
    pack = Path(shutil.copytree(testlaw_pack, tmp_path / "testlaw"))
    metadata = pack / "pack.yaml"
    metadata.write_text(
        metadata.read_text(encoding="utf-8").replace(
            "    expected_clauses: 2\n",
            "    expected_clauses: 2\n    commencement:\n      - from: 2999-01-01\n"
            "        keys: [testlaw:art-5:para-2]\n        source: Commencement Notice No. 1\n",
            1,
        ),
        encoding="utf-8",
    )
    original = (pack / "testlaw" / "art-5.md").read_text(encoding="utf-8")
    amended = original.replace("lang: en\n", "lang: en\nsource: Amending Act 2998\n", 1)
    second = (
        "Paragraph 1 shall not apply to processing necessary for compliance with a legal\n"
        "obligation."
    )
    assert second in amended
    (pack / "testlaw" / "art-5@2998-01-01.md").write_text(
        amended.replace(second, "The controller shall erase the data within ten days."),
        encoding="utf-8",
    )
    load_pack(session, pack)
    session.commit()

    before = get_clause(session, "testlaw:art-5:para-2", as_of=date(2998, 6, 1)).clause
    then = get_clause(session, "testlaw:art-5:para-2", as_of=date(2999, 6, 1)).clause
    first = get_clause(session, "testlaw:art-5:para-1", as_of=date(2998, 6, 1)).clause

    # The amendment changed its words, not the day it comes into force.
    assert before.text == then.text == "The controller shall erase the data within ten days."
    assert (before.in_force, before.in_force_from) == (False, date(2999, 1, 1))
    assert (then.in_force, then.in_force_from) == (True, date(2999, 1, 1))
    # A paragraph in force already takes the amendment's words from the amendment's day.
    assert (first.in_force, first.in_force_from) == (True, date(2998, 1, 1))


def without_its_second_paragraph(pack: Path, commencement: str) -> None:
    """Article 5 as an amendment of 2998 words it: its second paragraph deleted."""
    metadata = pack / "pack.yaml"
    metadata.write_text(
        metadata.read_text(encoding="utf-8").replace(
            "    expected_clauses: 2\n", "    expected_clauses: 2\n" + commencement, 1
        ),
        encoding="utf-8",
    )
    original = (pack / "testlaw" / "art-5.md").read_text(encoding="utf-8")
    kept = original.split("## 2. {#para-2}")[0].rstrip() + "\n"
    (pack / "testlaw" / "art-5@2998-01-01.md").write_text(
        kept.replace("lang: en\n", "lang: en\nsource: Amending Act 2998\n", 1), encoding="utf-8"
    )


def test_a_paragraph_an_amendment_deletes_ends_that_day(
    session: Session, testlaw_pack: Path, tmp_path: Path
) -> None:
    pack = Path(shutil.copytree(testlaw_pack, tmp_path / "testlaw"))
    without_its_second_paragraph(pack, "")
    load_pack(session, pack)
    session.commit()

    then = get_clause(session, "testlaw:art-5:para-2", as_of=date(2999, 1, 1)).clause
    found = keyword_search(session, "compliance with a legal obligation", as_of=date(2999, 1, 1))

    assert (then.in_force, then.in_force_until) == (False, date(2998, 1, 1))
    assert "testlaw:art-5:para-2" not in [candidate.key for candidate in found]


def test_a_paragraph_deleted_before_it_ever_applied_is_not_kept(
    session: Session, testlaw_pack: Path, tmp_path: Path
) -> None:
    pack = Path(shutil.copytree(testlaw_pack, tmp_path / "testlaw"))
    without_its_second_paragraph(
        pack,
        "    commencement:\n      - from: 2999-01-01\n        keys: [testlaw:art-5:para-2]\n"
        "        source: Commencement Notice No. 1\n",
    )
    load_pack(session, pack)
    session.commit()

    with pytest.raises(ClauseNotFound):
        get_clause(session, "testlaw:art-5:para-2")
    assert [child.key for child in get_clause(session, "testlaw:art-5").children] == [
        "testlaw:art-5:para-1"
    ]


def amending(pack: Path, name: str, text: str) -> None:
    (pack / "testlaw" / name).write_text(text, encoding="utf-8")


def test_an_article_amended_twice_reads_each_text_in_its_own_days(
    session: Session, testlaw_pack: Path, tmp_path: Path
) -> None:
    """As Japan's APPI is amended from 17 January 2027 and again from 16 July 2028."""
    pack = Path(shutil.copytree(testlaw_pack, tmp_path / "testlaw"))
    first = AMENDED.replace("Amending Act 2026, section 4", "Act No. 56, first stage")
    second = first.replace("Act No. 56, first stage", "Act No. 56, second stage").replace(
        "a ground set out in the Schedule", "a ground set out in Schedule 2"
    )
    amending(pack, "art-6@2027-01-17.md", first)
    amending(pack, "art-6@2028-07-16.md", second)
    load_pack(session, pack)
    session.commit()

    def read(day: date) -> str:
        return get_clause(session, "testlaw:art-6:para-1", as_of=day).clause.text

    today = get_clause(session, "testlaw:art-6:para-1", as_of=date(2026, 11, 6)).clause
    between = get_clause(session, "testlaw:art-6:para-1", as_of=date(2027, 6, 1)).clause

    assert read(date(2026, 11, 6)) == IN_FORCE
    assert "in the Schedule applies" in read(date(2027, 6, 1))
    assert "in Schedule 2 applies" in read(date(2028, 7, 16))
    # Each text carries the next one, and ends when it starts.
    assert today.coming is not None and today.coming.in_force_from == date(2027, 1, 17)
    assert between.in_force_until == date(2028, 7, 16)
    assert between.coming is not None and between.coming.in_force_from == date(2028, 7, 16)


def test_an_amendment_in_a_law_with_a_translation_reads_in_both_languages(
    session: Session, bilingual_pack: Path, tmp_path: Path
) -> None:
    pack = Path(shutil.copytree(bilingual_pack, tmp_path / "bilingual"))
    articles = pack / "bilingual"
    for lang, (old, new) in {
        "": ("تجوز المعالجة في الحالات الآتية:", "لا تجوز المعالجة إلا في الحالات الآتية:"),
        ".en": (
            "Processing is permitted in the following cases:",
            "Processing is permitted only in the following cases:",
        ),
    }.items():
        text = (articles / f"art-2{lang}.md").read_text(encoding="utf-8")
        marked = text.replace("\n---\n", "\nsource: Decree No. 7 of 2027\n---\n", 1)
        (articles / f"art-2@2027-03-01{lang}.md").write_text(
            marked.replace(old, new), encoding="utf-8"
        )
    load_pack(session, pack)
    session.commit()

    arabic = get_clause(session, "bilingual:art-2:para-1", lang="ar").clause
    english = get_clause(session, "bilingual:art-2:para-1", lang="en").clause
    later = get_clause(session, "bilingual:art-2:para-1", lang="en", as_of=date(2027, 3, 1))

    assert arabic.coming is not None and arabic.coming.text.startswith("لا تجوز المعالجة إلا")
    assert english.coming is not None and english.coming.text.startswith(
        "Processing is permitted only"
    )
    assert later.clause.text.startswith("Processing is permitted only")
    # The English is a translation, and says which text prevails, as it did before.
    assert later.clause.authoritative_text is not None
    assert later.clause.authoritative_text.startswith("لا تجوز المعالجة إلا")


def test_an_article_an_amendment_adds_takes_its_place_in_the_law(
    session: Session, testlaw_pack: Path, tmp_path: Path
) -> None:
    pack = Path(shutil.copytree(testlaw_pack, tmp_path / "testlaw"))
    amending(
        pack,
        "art-5-bis@2027-01-17.md",
        AMENDED.replace("testlaw:art-6", "testlaw:art-5-bis").replace(
            "Lawfulness of processing", "Erasure on request"
        ),
    )
    load_pack(session, pack)
    session.commit()

    added = get_clause(session, "testlaw:art-5-bis").clause

    assert [item.key for item in get_document(session, "testlaw").outline] == [
        "testlaw:art-5",
        "testlaw:art-5-bis",
        "testlaw:art-6",
    ]
    assert (added.in_force, added.in_force_from) == (False, date(2027, 1, 17))


def test_a_provision_amended_on_the_day_it_starts_starts_with_the_amended_words(
    session: Session, testlaw_pack: Path, tmp_path: Path
) -> None:
    pack = Path(shutil.copytree(testlaw_pack, tmp_path / "testlaw"))
    metadata = pack / "pack.yaml"
    metadata.write_text(
        metadata.read_text(encoding="utf-8").replace(
            "    expected_clauses: 2\n",
            "    expected_clauses: 2\n    commencement:\n      - from: 2027-01-17\n"
            "        keys: [testlaw:art-6]\n        source: Commencement Notice No. 2\n",
            1,
        ),
        encoding="utf-8",
    )
    amending(pack, "art-6@2027-01-17.md", AMENDED)
    load_pack(session, pack)
    session.commit()

    clause = get_clause(session, "testlaw:art-6:para-1", as_of=date(2027, 1, 17)).clause

    assert clause.text.startswith("Processing shall be lawful only where a ground")
    assert (clause.in_force, clause.in_force_from) == (True, date(2027, 1, 17))


def test_a_name_a_later_version_drops_is_dropped(
    session: Session, testlaw_pack: Path, tmp_path: Path
) -> None:
    pack = Path(shutil.copytree(testlaw_pack, tmp_path / "testlaw"))
    metadata = pack / "pack.yaml"
    first = metadata.read_text(encoding="utf-8")
    for line in ("  en: Test Data Protection Law\n", "  en: TESTLAW\n", "  en: Example Republic\n"):
        first = first.replace(line, line + "  fr: Loi d'essai\n", 1)
    metadata.write_text(first, encoding="utf-8")
    load_pack(session, pack)
    session.commit()
    metadata.write_text(
        first.replace("  fr: Loi d'essai\n", "").replace('version: "2026.1"', 'version: "2026.2"'),
        encoding="utf-8",
    )
    load_pack(session, pack)
    session.commit()

    [law] = list_laws(session)

    assert law.version == "2026.2"
    assert law.name == {"en": "Test Data Protection Law"}
    assert law.short_name == {"en": "TESTLAW"}
