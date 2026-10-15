"""Reading Word files from their XML.

The test files are written from scratch by tests/fixtures/policies/make.py, each one a pattern
found in real policies. Every piece of text in a file has to reach a paragraph, or be counted
as missed, because a clause lost here would be missing from every search.
"""

from __future__ import annotations

import importlib.util
import io
import zipfile
from pathlib import Path

import pytest

from dpolens.engine.policies import docx
from dpolens.engine.policies.blocks import ReadFile, UnreadablePolicy
from dpolens.engine.policies.docx import read_docx

FIXTURES = Path(__file__).parents[1] / "fixtures" / "policies"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def read(name: str) -> ReadFile:
    return read_docx((FIXTURES / name).read_bytes())


def texts(found: ReadFile) -> list[str]:
    return [paragraph.text for paragraph in found.paragraphs() if paragraph.text.strip()]


def package(parts: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as written:
        for name, content in parts.items():
            written.writestr(name, content)
    return buffer.getvalue()


def test_every_place_word_keeps_text_is_read() -> None:
    """A hyperlink, a tracked insertion, content controls, a smart tag, fields, custom XML and
    a table cell inside a content control: python-docx returns none of these."""
    found = read("word-constructs.docx")

    assert found.missed == 0
    assert found.unread == ()
    assert texts(found) == [
        "Constructs",
        "Hyperlinked text",
        "Tracked inserted",
        "Block control text.",
        "Inline control",
        "Smart tag",
        "Simple field",
        "Complex result",
        "Custom XML text.",
        "Tab\tand break\nhere.",
        "Symbol ¶",
        "Hidden text",
        "Noted",
        "Cell in a control",
        "Plain cell",
        "Second",
        "Row",
    ]


def test_deleted_text_is_left_out_and_the_reviewer_is_told() -> None:
    found = read("word-constructs.docx")

    assert not any("deleted" in text for text in texts(found))
    assert "This file has tracked changes, read as if every change were accepted." in found.notices


def test_what_is_not_read_is_said() -> None:
    notices = read("word-constructs.docx").notices

    assert "This file's 1 comment was not read." in notices
    assert "This file's 1 footnote was not read." in notices
    assert "This file has 4 characters of hidden text, read as shown." in notices


def test_a_text_box_written_twice_is_read_once() -> None:
    """Word writes a text box as a drawing and again as a fallback for older readers."""
    found = read("arabic-sections.docx")

    boxes = [p.text for p in found.paragraphs() if p.place == "text box"]

    assert boxes == ["أدخل شعار الجهة هنا."]
    assert found.missed == 0


def test_a_contents_page_is_known_for_what_it_is() -> None:
    found = read("numbered-headings.docx")

    contents = [p.text for p in found.paragraphs() if p.place == "contents"]

    assert contents == ["Contents", "1.\tOVERVIEW\t2", "2.\tPRINCIPLES\t2"]


def test_an_empty_paragraph_keeps_its_automatic_number() -> None:
    """In a requirements table the number is the only thing in the first column."""
    found = read("requirements-table.docx")

    numbers = [p.number.label for p in found.paragraphs() if p.number and not p.text]

    assert numbers == ["1", "1-1", "1-2", "2", "2-1"]


def test_letters_joined_for_print_are_written_apart() -> None:
    """A document converted from a PDF keeps "ﬁ" as one character, which no search for
    "specific" would find."""
    assert "Specific retention periods are set in the schedule." in texts(
        read("automatic-numbering.docx")
    )


def test_headings_and_type_are_read_as_word_resolves_them() -> None:
    paragraphs = {p.text: p for p in read("size-headings.docx").paragraphs()}

    assert paragraphs["Our procedures"].heading_level == 1
    # A body style that carries an outline level says so; the layers decide what it means.
    assert paragraphs["We keep personal data secure against loss or misuse."].heading_level == 3
    assert paragraphs["Fair and lawful processing"].size == 16
    assert paragraphs["Fair and lawful processing"].bold is False
    assert paragraphs["Who is responsible for this policy?"].bold


def test_a_file_that_is_not_a_package_is_refused() -> None:
    with pytest.raises(UnreadablePolicy, match=r"not a \.docx package"):
        read_docx(b"%PDF-1.7 a PDF renamed .docx")


def test_a_package_with_no_document_is_refused() -> None:
    with pytest.raises(UnreadablePolicy, match="no document part"):
        read_docx(package({"docProps/app.xml": "<Properties/>"}))


@pytest.mark.parametrize(
    "declaration",
    ['<!DOCTYPE w:document [<!ENTITY a "aaaaaaaa">]>', '<!DOCTYPE w:document SYSTEM "x.dtd">'],
)
def test_a_part_that_declares_a_dtd_is_refused(declaration: str) -> None:
    """Entities are an old way to make a parser run out of memory, and Word never declares a
    DTD, so a part that does is refused before it is parsed."""
    document = f'<?xml version="1.0"?>{declaration}<w:document xmlns:w="{W}"><w:body/></w:document>'

    with pytest.raises(UnreadablePolicy, match="declares a DTD"):
        read_docx(package({"word/document.xml": document}))


def test_xml_that_is_not_well_formed_is_refused() -> None:
    with pytest.raises(UnreadablePolicy, match="not well-formed"):
        read_docx(package({"word/document.xml": "<w:document><w:body>"}))


@pytest.mark.parametrize(
    ("limit", "value", "message"),
    [
        ("MAX_PARTS", 3, "too many parts"),
        ("MAX_TOTAL_BYTES", 1_000, "unpacks to more than"),
        ("MAX_PART_BYTES", 1_000, "larger than"),
    ],
)
def test_limits_hold_before_a_file_is_unpacked(
    monkeypatch: pytest.MonkeyPatch, limit: str, value: int, message: str
) -> None:
    """The real limits are generous; lowered here, a small file shows each one is enforced."""
    monkeypatch.setattr(docx, limit, value)

    with pytest.raises(UnreadablePolicy, match=message):
        read("word-constructs.docx")


def test_the_committed_files_are_what_their_descriptions_write(tmp_path: Path) -> None:
    """Changing a description in make.py without writing the files again fails here."""
    spec = importlib.util.spec_from_file_location("make_policies", FIXTURES / "make.py")
    assert spec is not None and spec.loader is not None
    make = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(make)

    make.main(tmp_path)

    written = sorted(path.name for path in tmp_path.iterdir())
    assert written == sorted(path.name for path in FIXTURES.glob("*.docx"))
    for name in written:
        assert (tmp_path / name).read_bytes() == (FIXTURES / name).read_bytes(), name
