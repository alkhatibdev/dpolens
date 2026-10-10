"""Reading pack files: the tree comes from the headings, never from the prose."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from dpolens.engine.packs.format import (
    Clause,
    PackFormatError,
    law_order,
    read_clause_file,
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
        slug="testlaw", title="Test", normative=True, expected_clauses=99
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
