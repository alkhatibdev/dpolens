"""Reading pack files: the tree comes from the headings, never from the prose."""

from __future__ import annotations

from pathlib import Path

import pytest

from dpolens.engine.packs.format import (
    PackFormatError,
    read_clause_file,
    read_document,
    read_pack_metadata,
)

FIXTURE_PACK = Path(__file__).parents[1] / "fixtures" / "packs" / "testlaw"


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
