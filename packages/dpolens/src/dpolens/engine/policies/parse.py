"""Parsing a policy file: read it, build its tree, give its clauses keys, check the result."""

from __future__ import annotations

from pathlib import PurePath

from dpolens.engine.policies.blocks import ReadFile, UnreadablePolicy
from dpolens.engine.policies.checks import check_coverage, check_keys, check_numbering
from dpolens.engine.policies.docx import read_docx
from dpolens.engine.policies.keys import assign, slug_of
from dpolens.engine.policies.markdown import read_markdown
from dpolens.engine.policies.reading import lines_of
from dpolens.engine.policies.structure import build
from dpolens.engine.policies.tree import Clause, Flag, ParsedPolicy

REFUSED = {
    ".doc": "This is Word's older format (.doc). Save it as .docx in Word and use that file.",
    ".pdf": "PDF files are not read. Use the Word or Markdown file the PDF was made from.",
    ".odt": "OpenDocument files are not read. Save it as .docx and use that file.",
    ".rtf": "Rich Text files are not read. Save it as .docx and use that file.",
    ".pages": "Pages files are not read. Export it as Word (.docx) and use that file.",
}


def read_file(data: bytes, filename: str) -> ReadFile:
    suffix = PurePath(filename).suffix.lower()
    if suffix == ".docx":
        return read_docx(data)
    if suffix in (".md", ".markdown"):
        return read_markdown(data)
    raise UnreadablePolicy(
        REFUSED.get(suffix, "DPOLens reads Word (.docx) and Markdown (.md) policy files.")
    )


def parse_policy(data: bytes, filename: str, slug: str | None = None) -> ParsedPolicy:
    """Parse a Word or Markdown policy into clauses, with its flags and its checks."""
    read = read_file(data, filename)
    if not any(paragraph.text.strip() for paragraph in read.paragraphs()):
        raise UnreadablePolicy(
            "This file has no text to read. A scanned document holds pictures of its pages, "
            "not their text."
        )
    built = build(read)
    clauses = assign(slug or slug_of(PurePath(filename).stem), built.roots)
    coverage, coverage_flags = check_coverage(read, built)
    flags = [
        *coverage_flags,
        *(located(flag, clauses) for flag in built.flags),
        *check_numbering(clauses),
        *check_keys(clauses),
    ]
    return ParsedPolicy(
        slug=slug or slug_of(PurePath(filename).stem),
        format=read.format,
        title=built.title,
        clauses=clauses,
        set_aside=tuple(built.set_aside),
        flags=tuple(flags),
        coverage=coverage,
        notices=read.notices,
        lines=lines_of(read),
    )


def located(flag: Flag, clauses: tuple[Clause, ...]) -> Flag:
    """A flag the layers raised at a paragraph, with the key of the clause that holds it."""
    if flag.key is not None or flag.position is None:
        return flag
    for root in clauses:
        for clause in root.walk():
            if flag.position in clause.positions:
                return Flag(
                    kind=flag.kind, detail=flag.detail, key=clause.key, position=flag.position
                )
    return flag
