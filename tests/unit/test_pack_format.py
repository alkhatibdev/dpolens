"""Reading pack files: the tree comes from the headings, never from the prose."""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest

from dpolens.engine.packs.format import (
    Clause,
    Dates,
    PackFormatError,
    law_order,
    read_clause_file,
    read_coming,
    read_document,
    read_pack_metadata,
    read_translations,
)

FIXTURE_PACK = Path(__file__).parents[1] / "fixtures" / "packs" / "testlaw"
BILINGUAL_PACK = Path(__file__).parents[1] / "fixtures" / "packs" / "bilingual"


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "clause.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_reads_pack_metadata() -> None:
    pack = read_pack_metadata(FIXTURE_PACK)

    assert pack.slug == "testlaw"
    assert pack.authoritative_language == "en"
    assert [document.slug for document in pack.documents] == ["testlaw", "testlaw-recitals"]
    assert pack.documents[1].normative is False


def test_builds_the_tree_from_headings() -> None:
    clause = read_clause_file(FIXTURE_PACK / "testlaw" / "art-5.md")

    assert clause.key == "testlaw:art-5"
    assert clause.clause_type == "article"
    assert clause.heading == "Right to erasure"
    assert clause.body_text.startswith("The controller shall erase")

    paragraphs = [child.key for child in clause.children]
    assert paragraphs == ["testlaw:art-5:para-1", "testlaw:art-5:para-2"]

    points = clause.children[0].children
    assert [point.key for point in points] == [
        "testlaw:art-5:para-1:pt-a",
        "testlaw:art-5:para-1:pt-b",
    ]


def test_keeps_the_label_the_law_uses() -> None:
    clause = read_clause_file(FIXTURE_PACK / "testlaw" / "art-5.md")
    point = clause.children[0].children[0]

    assert point.label == "(a)"
    assert point.clause_type == "point"
    assert point.body_text == "where there is no other legal ground for the processing;"


def test_recitals_are_not_normative() -> None:
    clause = read_clause_file(
        FIXTURE_PACK / "testlaw-recitals" / "rec-12.md", document_normative=False
    )

    assert clause.normative is False
    assert clause.clause_type == "recital"


def test_reads_cross_references() -> None:
    clause = read_clause_file(FIXTURE_PACK / "testlaw" / "art-5.md")

    assert clause.cross_references[0].key == "testlaw:art-6:para-1"
    assert clause.cross_references[0].text == "Article 6(1)"


def test_counts_must_match_pack_yaml() -> None:
    pack = read_pack_metadata(FIXTURE_PACK)
    inflated = pack.documents[0].__class__(
        slug="testlaw", title={"en": "Test"}, normative=True, expected_clauses=99
    )

    with pytest.raises(PackFormatError, match="expects 99 clauses, found 2"):
        read_document(FIXTURE_PACK, inflated)


def test_rejects_a_heading_without_a_key_segment(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "---\nkey: testlaw:art-1\nlang: en\n---\n\n## 1.\n\nSome text.\n",
    )

    with pytest.raises(PackFormatError, match="key segment anchor"):
        read_clause_file(path)


def test_rejects_a_skipped_heading_level(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "---\nkey: testlaw:art-1\nlang: en\n---\n\n#### (a) {#pt-a}\n\nSome text.\n",
    )

    with pytest.raises(PackFormatError, match="jumps from level"):
        read_clause_file(path)


def test_rejects_a_repeated_key(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "---\nkey: testlaw:art-1\nlang: en\n---\n"
        "\n## 1. {#para-1}\n\nFirst.\n"
        "\n## 1. {#para-1}\n\nAgain.\n",
    )

    with pytest.raises(PackFormatError, match="appears twice"):
        read_clause_file(path)


def test_rejects_an_unknown_segment(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "---\nkey: testlaw:art-1\nlang: en\n---\n\n## 1. {#clause-1}\n\nSome text.\n",
    )

    with pytest.raises(PackFormatError, match="unknown key segment"):
        read_clause_file(path)


def test_rejects_a_file_without_front_matter(tmp_path: Path) -> None:
    path = write(tmp_path, "## 1. {#para-1}\n\nSome text.\n")

    with pytest.raises(PackFormatError, match="front matter"):
        read_clause_file(path)


def bilingual_copy(tmp_path: Path) -> Path:
    """The two-language fixture, somewhere a test may break it."""
    return Path(shutil.copytree(BILINGUAL_PACK, tmp_path / "bilingual"))


def read_both(pack_dir: Path) -> tuple[list[Clause], dict[str, list[Clause]]]:
    pack = read_pack_metadata(pack_dir)
    clauses = read_document(pack_dir, pack.documents[0])
    return clauses, read_translations(pack_dir, pack.documents[0], pack, clauses)


def test_articles_keep_the_laws_order() -> None:
    """Sorted as text, article 10 would come before article 2."""
    names = [Path(name) for name in ("art-10.md", "art-2.md", "art-1.md", "rec-100.md", "rec-9.md")]

    assert [path.name for path in sorted(names, key=law_order)] == [
        "art-1.md",
        "art-2.md",
        "art-10.md",
        "rec-9.md",
        "rec-100.md",
    ]
    clauses, _ = read_both(BILINGUAL_PACK)
    assert [clause.key for clause in clauses] == [
        "bilingual:art-1",
        "bilingual:art-2",
        "bilingual:art-10",
    ]


def test_reads_a_translation_clause_for_clause() -> None:
    clauses, translations = read_both(BILINGUAL_PACK)
    english = translations["en"]

    assert [clause.key for clause in english] == [clause.key for clause in clauses]
    point, translated = clauses[1].children[0].children[0], english[1].children[0].children[0]
    assert (point.key, point.lang, point.label) == ("bilingual:art-2:para-1:pt-a", "ar", "أ.")
    assert (translated.key, translated.lang, translated.label) == (point.key, "en", "a.")


def test_a_translation_declares_its_status() -> None:
    pack = read_pack_metadata(BILINGUAL_PACK)

    [translation] = pack.translations
    assert (translation.lang, translation.translation_status) == ("en", "official_translation")


def test_a_translation_missing_a_clause_is_refused(tmp_path: Path) -> None:
    pack_dir = bilingual_copy(tmp_path)
    (pack_dir / "bilingual" / "art-10.en.md").unlink()

    with pytest.raises(PackFormatError, match="has no 'en' translation"):
        read_both(pack_dir)


def test_a_translation_with_other_clauses_is_refused(tmp_path: Path) -> None:
    pack_dir = bilingual_copy(tmp_path)
    english = pack_dir / "bilingual" / "art-2.en.md"
    text = english.read_text(encoding="utf-8")
    english.write_text(text.split("### b.")[0], encoding="utf-8")

    with pytest.raises(PackFormatError, match="does not have the same clauses"):
        read_both(pack_dir)


def test_two_translations_of_one_clause_are_refused(tmp_path: Path) -> None:
    """Otherwise one of them would be loaded and the other silently ignored."""
    pack_dir = bilingual_copy(tmp_path)
    english = pack_dir / "bilingual" / "art-1.en.md"
    shutil.copy(english, english.with_name("art-1-again.en.md"))

    with pytest.raises(PackFormatError, match="more than one 'en' file holds"):
        read_both(pack_dir)


def test_a_language_pack_yaml_does_not_declare_is_refused(tmp_path: Path) -> None:
    pack_dir = bilingual_copy(tmp_path)
    french = (pack_dir / "bilingual" / "art-1.en.md").read_text(encoding="utf-8")
    (pack_dir / "bilingual" / "art-1.fr.md").write_text(
        french.replace("lang: en", "lang: fr"), encoding="utf-8"
    )

    with pytest.raises(PackFormatError, match="'fr' is not a translation"):
        read_both(pack_dir)


def test_a_file_name_and_its_front_matter_must_agree(tmp_path: Path) -> None:
    pack_dir = bilingual_copy(tmp_path)
    english = pack_dir / "bilingual" / "art-1.en.md"
    english.write_text(english.read_text(encoding="utf-8").replace("lang: en", "lang: ar"))

    with pytest.raises(PackFormatError, match="the file name says 'en'"):
        read_both(pack_dir)


def test_a_translation_status_must_be_known(tmp_path: Path) -> None:
    pack_dir = bilingual_copy(tmp_path)
    metadata = pack_dir / "pack.yaml"
    metadata.write_text(metadata.read_text().replace("status: official", "status: machine"))

    with pytest.raises(PackFormatError, match="translation status must be one of"):
        read_pack_metadata(pack_dir)


def test_a_licence_left_empty_is_refused(tmp_path: Path) -> None:
    """The licensing gate checks what a field says, not only that it is there."""
    pack_dir = bilingual_copy(tmp_path)
    metadata = pack_dir / "pack.yaml"
    metadata.write_text(
        metadata.read_text().replace(
            "license: Public domain, official documents are excluded from copyright.",
            'license: ""',
        )
    )

    with pytest.raises(PackFormatError, match="leaves required fields empty: license"):
        read_pack_metadata(pack_dir)


def test_a_translation_with_no_licence_is_refused(tmp_path: Path) -> None:
    pack_dir = bilingual_copy(tmp_path)
    metadata = pack_dir / "pack.yaml"
    licence = "license: Public domain, under the same exclusion."
    metadata.write_text(metadata.read_text().replace(licence, "license:"))

    with pytest.raises(PackFormatError, match="each translation needs"):
        read_pack_metadata(pack_dir)


def one_language_copy(tmp_path: Path) -> Path:
    """The one-language fixture, somewhere a test may break it."""
    return Path(shutil.copytree(FIXTURE_PACK, tmp_path / "testlaw"))


def rewrite(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} is not in {path}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_names_the_law_in_each_language() -> None:
    pack = read_pack_metadata(BILINGUAL_PACK)

    assert pack.name == {"ar": "قانون تجريبي ثنائي اللغة", "en": "Test Bilingual Law"}
    assert pack.short_name == {"ar": "القانون التجريبي", "en": "BILINGUAL"}
    assert pack.jurisdiction["en"] == "Example Republic"
    assert pack.region == "Middle East"
    assert pack.documents[0].title["ar"] == "قانون تجريبي ثنائي اللغة"
    assert pack.languages == ("ar", "en")


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("format: 2\n", "", "says no pack format, and this engine reads format 2"),
        ("format: 2\n", "format: 3\n", "says pack format 3, and this engine reads format 2. Use"),
        ("  ar: القانون التجريبي\n", "", "short_name has nothing for ar"),
        ("  en: Example Republic\n", "", "jurisdiction has nothing for en"),
        ("      ar: قانون تجريبي ثنائي اللغة\n", "", "the title of bilingual has nothing for ar"),
        ("region: Middle East", "region: Gulf", "region must be one of"),
    ],
)
def test_format_2_is_refused_when_it_leaves_something_out(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    pack_dir = bilingual_copy(tmp_path)
    rewrite(pack_dir / "pack.yaml", old, new)

    with pytest.raises(PackFormatError, match=message):
        read_pack_metadata(pack_dir)


def test_a_pack_yaml_that_is_not_fields_is_refused(tmp_path: Path) -> None:
    pack_dir = one_language_copy(tmp_path)
    (pack_dir / "pack.yaml").write_text("- slug: testlaw\n", encoding="utf-8")

    with pytest.raises(PackFormatError, match="where it holds fields by name"):
        read_pack_metadata(pack_dir)


def test_a_language_left_empty_names_nothing(tmp_path: Path) -> None:
    pack_dir = one_language_copy(tmp_path)
    rewrite(pack_dir / "pack.yaml", "  en: TESTLAW\n", "  en: TESTLAW\n  fr: ''\n")

    assert read_pack_metadata(pack_dir).short_name == {"en": "TESTLAW"}


def test_a_law_in_another_language_is_named_in_english_too(tmp_path: Path) -> None:
    """Every interface is in English, so English is needed even with no English text."""
    pack_dir = bilingual_copy(tmp_path)
    rewrite(
        pack_dir / "pack.yaml",
        "translations:\n  - lang: en\n    status: official\n    license: Public domain, under "
        "the same exclusion.\n",
        "translations: []\n",
    )
    rewrite(pack_dir / "pack.yaml", "  en: BILINGUAL\n", "")

    with pytest.raises(PackFormatError, match="short_name has nothing for en"):
        read_pack_metadata(pack_dir)


def test_the_names_are_in_the_same_languages(tmp_path: Path) -> None:
    pack_dir = one_language_copy(tmp_path)
    rewrite(
        pack_dir / "pack.yaml",
        "  en: Test Data Protection Law\n",
        "  en: Test Data Protection Law\n  fr: Loi d'essai\n",
    )

    with pytest.raises(PackFormatError, match="name the law in different languages"):
        read_pack_metadata(pack_dir)


def test_a_name_written_once_is_refused_with_the_shape_it_needs(tmp_path: Path) -> None:
    pack_dir = one_language_copy(tmp_path)
    rewrite(pack_dir / "pack.yaml", "short_name:\n  en: TESTLAW\n", "short_name: TESTLAW\n")

    with pytest.raises(PackFormatError, match="short_name is written once per language"):
        read_pack_metadata(pack_dir)


def commencing(pack_dir: Path, entries: str) -> None:
    """Give the fixture's articles a commencement list."""
    rewrite(
        pack_dir / "pack.yaml",
        "    expected_clauses: 2\n",
        "    expected_clauses: 2\n    commencement:\n" + entries,
    )


def test_dates_come_from_the_most_specific_key(tmp_path: Path) -> None:
    pack_dir = one_language_copy(tmp_path)
    commencing(
        pack_dir,
        """      - from: 2027-05-13
        keys: [testlaw:art-5]
        source: Notice 843, 13 November 2025
      - from: 2026-11-13
        keys: [testlaw:art-5:para-1]
        source: Notice 843, 13 November 2025
      - from: pending
        keys: [testlaw:art-5:para-1:pt-b]
        source: Section 1(2), on a date the government appoints
      - until: 2027-05-13
        keys: [testlaw:art-6]
        source: Act 2 of 2026, section 44(2)
""",
    )
    pack = read_pack_metadata(pack_dir)
    articles = pack.documents[0]
    read_document(pack_dir, articles)

    assert articles.dates_of("testlaw:art-5") == Dates(
        starts=date(2027, 5, 13), source="Notice 843, 13 November 2025"
    )
    assert articles.dates_of("testlaw:art-5:para-2").starts == date(2027, 5, 13)
    assert articles.dates_of("testlaw:art-5:para-1").starts == date(2026, 11, 13)
    assert articles.dates_of("testlaw:art-5:para-1:pt-a").starts == date(2026, 11, 13)
    assert articles.dates_of("testlaw:art-5:para-1:pt-b") == Dates(
        pending=True, source="Section 1(2), on a date the government appoints"
    )
    assert articles.dates_of("testlaw:art-6:para-1").ends == date(2027, 5, 13)
    assert articles.dates_of("testlaw:art-50") == Dates()


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        (
            "      - from: 2027-05-13\n        keys: [testlaw:art-9]\n        source: A notice\n",
            r"names \['testlaw:art-9'\], which the document does not have",
        ),
        (
            "      - from: 2027-05-13\n        keys: [testlaw:art-5]\n",
            "needs a 'source': what set these dates",
        ),
        (
            "      - from: soon\n        keys: [testlaw:art-5]\n        source: A notice\n",
            "'from' must be a date, for example 2027-05-13, or pending",
        ),
        (
            "      - keys: [testlaw:art-5]\n        source: A notice\n",
            "needs a 'from' date, 'from: pending', or an 'until' date",
        ),
        (
            "      - from: 2027-05-13\n        until: 2027-01-01\n        keys: [testlaw:art-5]\n"
            "        source: A notice\n",
            "ends on 2027-01-01, which is not after it starts",
        ),
        (
            "      - from: 2027-05-13\n        keys: [testlaw:art-5]\n        source: A notice\n"
            "      - from: 2028-01-01\n        keys: [testlaw:art-5]\n        source: Another\n",
            "dates 'testlaw:art-5' twice",
        ),
    ],
)
def test_a_commencement_that_cannot_be_checked_is_refused(
    tmp_path: Path, entries: str, message: str
) -> None:
    pack_dir = one_language_copy(tmp_path)
    commencing(pack_dir, entries)

    with pytest.raises(PackFormatError, match=message):
        pack = read_pack_metadata(pack_dir)
        read_document(pack_dir, pack.documents[0])


AMENDED = """---
key: testlaw:art-6
title: Lawfulness of processing
lang: en
source: Act 2 of 2026, Article 3
---

## 1. {#para-1}

Processing shall be lawful only where a legal ground in this Article applies.

## 2. {#para-2}

Consent shall be as easy to withdraw as to give.
"""


def test_a_coming_text_is_read_beside_the_text_in_force(tmp_path: Path) -> None:
    pack_dir = one_language_copy(tmp_path)
    (pack_dir / "testlaw" / "art-6@2027-01-17.md").write_text(AMENDED, encoding="utf-8")
    (pack_dir / "testlaw" / "art-7@2027-01-17.md").write_text(
        AMENDED.replace("art-6", "art-7"), encoding="utf-8"
    )
    pack = read_pack_metadata(pack_dir)

    clauses = read_document(pack_dir, pack.documents[0])
    coming = read_coming(pack_dir, pack.documents[0], pack)

    assert [clause.key for clause in clauses] == ["testlaw:art-5", "testlaw:art-6"]
    assert [(text.clause.key, text.starts) for text in coming] == [
        ("testlaw:art-6", date(2027, 1, 17)),
        ("testlaw:art-7", date(2027, 1, 17)),
    ]
    assert coming[0].source == "Act 2 of 2026, Article 3"
    assert [child.key for child in coming[0].clause.children][-1] == "testlaw:art-6:para-2"


@pytest.mark.parametrize(
    ("name", "text", "message"),
    [
        ("art-6@2027.md", AMENDED, "named for the file it replaces and the day it starts"),
        ("art-6@2027-02-30.md", AMENDED, "2027-02-30 is not a date"),
        ("art-6@2025-01-01.md", AMENDED, "which is not after the pack's effective_date"),
        (
            "art-6@2027-01-17.md",
            AMENDED.replace("source: Act 2 of 2026, Article 3\n", ""),
            "needs a 'source', the amendment that brings this text",
        ),
        ("art-6@2027-01-17.fr.md", AMENDED, "'fr' is not a translation pack.yaml declares"),
    ],
)
def test_a_coming_text_that_cannot_be_checked_is_refused(
    tmp_path: Path, name: str, text: str, message: str
) -> None:
    pack_dir = one_language_copy(tmp_path)
    (pack_dir / "testlaw" / name).write_text(text, encoding="utf-8")
    pack = read_pack_metadata(pack_dir)

    with pytest.raises(PackFormatError, match=message):
        read_coming(pack_dir, pack.documents[0], pack)


def test_a_coming_text_is_translated_like_any_other(tmp_path: Path) -> None:
    pack_dir = bilingual_copy(tmp_path)
    articles = pack_dir / "bilingual"
    shutil.copy(articles / "art-2.md", articles / "art-2@2027-01-17.md")
    rewrite(articles / "art-2@2027-01-17.md", "lang: ar\n", "lang: ar\nsource: قانون رقم 2\n")
    pack = read_pack_metadata(pack_dir)

    with pytest.raises(PackFormatError, match="has no 'en' translation"):
        read_coming(pack_dir, pack.documents[0], pack)

    shutil.copy(articles / "art-2.en.md", articles / "art-2@2027-01-17.en.md")
    coming = read_coming(pack_dir, pack.documents[0], pack)

    assert coming[0].translations["en"].lang == "en"
    assert [clause.key for clause in read_both(pack_dir)[0]] == [
        "bilingual:art-1",
        "bilingual:art-2",
        "bilingual:art-10",
    ]


def test_inserted_and_coming_files_keep_the_laws_order() -> None:
    names = [
        Path(name) for name in ("art-5-bis.md", "art-5@2027-01-17.md", "art-5.en.md", "art-5.md")
    ]

    assert [path.name for path in sorted(names, key=law_order)] == [
        "art-5.en.md",
        "art-5.md",
        "art-5@2027-01-17.md",
        "art-5-bis.md",
    ]


@pytest.mark.parametrize(
    ("key", "clause_type"),
    [
        ("dpdp-rules:rule-3", "rule"),
        ("sg-pdpr:reg-4", "regulation"),
        ("dpdp:sch", "schedule"),
        ("pipeda:sch-1", "schedule"),
        ("appi:suppl", "supplementary provisions"),
    ],
)
def test_segments_cover_each_legal_tradition(tmp_path: Path, key: str, clause_type: str) -> None:
    path = write(tmp_path, f"---\nkey: {key}\nlang: en\n---\n\nText.\n")

    assert read_clause_file(path).clause_type == clause_type


def test_a_schedules_clause_has_its_own_segment(tmp_path: Path) -> None:
    path = write(tmp_path, "---\nkey: pipeda:sch-1\nlang: en\n---\n\n## 4.3 {#cl-4-3}\n\nText.\n")

    assert read_clause_file(path).children[0].clause_type == "clause"
