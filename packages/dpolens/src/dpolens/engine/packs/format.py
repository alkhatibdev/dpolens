"""Reading pack files.

A clause exists because a heading declares it, never because the prose looked
like one. Every failure here names the file and says what was expected, since
the reader is usually a contributor building a pack for their own jurisdiction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any

import yaml

SEGMENT_TYPES = {
    "art": "article",
    "para": "paragraph",
    "sub": "subparagraph",
    "pt": "point",
    "sec": "section",
    "ch": "chapter",
    "rec": "recital",
    "annex": "annex",
}

FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)
ANY_HEADING = re.compile(r"^#{1,6}[ \t]")
HEADING = re.compile(r"^(#{2,6})[ \t]+(.*?)[ \t]*\{#([a-z0-9][a-z0-9-]*)\}[ \t]*$")
KEY = re.compile(r"^[a-z0-9][a-z0-9-]*(?::[a-z0-9][a-z0-9-]*)+$")


class PackFormatError(Exception):
    """A pack file could not be read as written."""


@dataclass(frozen=True)
class CrossReference:
    key: str
    text: str


@dataclass(frozen=True)
class Clause:
    key: str
    clause_type: str
    label: str | None
    heading: str | None
    body_text: str
    lang: str
    normative: bool
    cross_references: tuple[CrossReference, ...] = ()
    children: tuple[Clause, ...] = ()

    def walk(self) -> list[Clause]:
        """This clause and everything beneath it, depth first."""
        found = [self]
        for child in self.children:
            found.extend(child.walk())
        return found


@dataclass(frozen=True)
class PackDocument:
    slug: str
    title: str
    normative: bool
    expected_clauses: int
    source_url: str | None = None
    source_sha256: str | None = None
    """Where this document's text came from, so a rebuild can prove it used the same file."""


@dataclass(frozen=True)
class PackMetadata:
    slug: str
    name: str
    jurisdiction: str
    version: str
    effective_date: date
    trust_tier: str
    source_url: str
    license: str
    authoritative_language: str
    documents: tuple[PackDocument, ...]
    translations: tuple[dict[str, Any], ...] = field(default=())


REQUIRED_PACK_FIELDS = (
    "slug",
    "name",
    "jurisdiction",
    "version",
    "effective_date",
    "trust_tier",
    "source_url",
    "license",
    "authoritative_language",
    "documents",
)
TRUST_TIERS = ("verified", "community")


def clause_type_for(segment: str) -> str:
    prefix = segment.split("-", 1)[0]
    clause_type = SEGMENT_TYPES.get(prefix)
    if clause_type is None:
        raise PackFormatError(
            f"unknown key segment '{segment}': expected one of "
            f"{', '.join(sorted(SEGMENT_TYPES))} followed by a number or letter"
        )
    return clause_type


def read_pack_metadata(pack_dir: Path) -> PackMetadata:
    path = pack_dir / "pack.yaml"
    if not path.is_file():
        raise PackFormatError(f"{pack_dir} has no pack.yaml")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    missing = [name for name in REQUIRED_PACK_FIELDS if name not in raw]
    if missing:
        raise PackFormatError(f"{path} is missing required fields: {', '.join(missing)}")

    if raw["trust_tier"] not in TRUST_TIERS:
        raise PackFormatError(
            f"{path}: trust_tier must be one of {', '.join(TRUST_TIERS)}, not {raw['trust_tier']!r}"
        )

    effective_date = raw["effective_date"]
    if not isinstance(effective_date, date):
        raise PackFormatError(f"{path}: effective_date must be a date, for example 2018-05-25")

    documents = tuple(_read_document_entry(path, entry) for entry in raw["documents"])
    if not documents:
        raise PackFormatError(f"{path}: a pack needs at least one document")

    return PackMetadata(
        slug=str(raw["slug"]),
        name=str(raw["name"]),
        jurisdiction=str(raw["jurisdiction"]),
        version=str(raw["version"]),
        effective_date=effective_date,
        trust_tier=str(raw["trust_tier"]),
        source_url=str(raw["source_url"]),
        license=str(raw["license"]),
        authoritative_language=str(raw["authoritative_language"]),
        documents=documents,
        translations=tuple(raw.get("translations") or ()),
    )


def _read_document_entry(path: Path, entry: dict[str, Any]) -> PackDocument:
    for name in ("slug", "title", "expected_clauses"):
        if name not in entry:
            raise PackFormatError(f"{path}: document entry is missing '{name}'")
    return PackDocument(
        slug=str(entry["slug"]),
        title=str(entry["title"]),
        normative=bool(entry.get("normative", True)),
        expected_clauses=int(entry["expected_clauses"]),
        source_url=str(entry["source_url"]) if entry.get("source_url") else None,
        source_sha256=str(entry["source_sha256"]) if entry.get("source_sha256") else None,
    )


def read_clause_file(path: Path, document_normative: bool = True) -> Clause:
    """Read one clause file into a clause and its children."""
    text = path.read_text(encoding="utf-8")
    match = FRONT_MATTER.match(text)
    if match is None:
        raise PackFormatError(
            f"{path}: a clause file starts with YAML front matter between --- lines"
        )

    meta = yaml.safe_load(match.group(1)) or {}
    body = match.group(2)

    for name in ("key", "lang"):
        if name not in meta:
            raise PackFormatError(f"{path}: front matter is missing '{name}'")

    key = str(meta["key"])
    if not KEY.match(key):
        raise PackFormatError(
            f"{path}: '{key}' is not a canonical key. Expected a document slug and at "
            "least one segment, such as gdpr:art-17"
        )

    normative = bool(meta.get("normative", document_normative))
    root_text, children = _read_body(
        path, body, parent_key=key, lang=str(meta["lang"]), normative=normative
    )

    clause = Clause(
        key=key,
        clause_type=clause_type_for(key.split(":")[-1]),
        label=str(meta["label"]) if meta.get("label") else None,
        heading=str(meta["title"]) if meta.get("title") else None,
        body_text=root_text,
        lang=str(meta["lang"]),
        normative=normative,
        children=children,
    )
    _reject_repeated_keys(path, clause)
    return _attach_cross_references(
        path, clause, _read_cross_references(path, meta.get("cross_references") or [])
    )


def _reject_repeated_keys(path: Path, clause: Clause) -> None:
    seen: set[str] = set()
    for found in clause.walk():
        if found.key in seen:
            raise PackFormatError(
                f"{path}: '{found.key}' appears twice. A key identifies one clause, and "
                "citations to it must never become ambiguous"
            )
        seen.add(found.key)


def _read_cross_references(
    path: Path, entries: list[Any]
) -> dict[str | None, list[CrossReference]]:
    """Group the file's links by the clause that states each one.

    An entry without a `from` is stated by the file's own clause.
    """
    grouped: dict[str | None, list[CrossReference]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or "key" not in entry or "text" not in entry:
            raise PackFormatError(
                f"{path}: each cross reference needs a 'key' and the 'text' as written"
            )
        stated_by = str(entry["from"]) if entry.get("from") else None
        reference = CrossReference(key=str(entry["key"]), text=str(entry["text"]))
        grouped.setdefault(stated_by, []).append(reference)
    return grouped


def _attach_cross_references(
    path: Path, clause: Clause, grouped: dict[str | None, list[CrossReference]]
) -> Clause:
    """Give every link to the clause that states it."""
    keys = {found.key for found in clause.walk()}
    for stated_by in grouped:
        if stated_by is not None and stated_by not in keys:
            raise PackFormatError(
                f"{path}: a cross reference says it comes from '{stated_by}', which is "
                "not a clause in this file"
            )

    def rebuild(current: Clause, is_root: bool) -> Clause:
        found = grouped.get(None, []) if is_root else grouped.get(current.key, [])
        return replace(
            current,
            cross_references=tuple(found),
            children=tuple(rebuild(child, is_root=False) for child in current.children),
        )

    return rebuild(clause, is_root=True)


@dataclass
class _Section:
    level: int
    label: str
    segment: str
    lines: list[str]


def _read_body(
    path: Path, body: str, parent_key: str, lang: str, normative: bool
) -> tuple[str, tuple[Clause, ...]]:
    """Split a body into the clause's own text and its child clauses."""
    own_lines: list[str] = []
    sections: list[_Section] = []

    for number, line in enumerate(body.splitlines(), start=1):
        heading = HEADING.match(line)
        if heading is None:
            if ANY_HEADING.match(line):
                raise PackFormatError(
                    f"{path} line {number}: a heading opens a clause, so it needs a key "
                    "segment anchor, for example '## 1. {#para-1}'. Text that is not a "
                    "clause belongs in the body."
                )
            (sections[-1].lines if sections else own_lines).append(line)
            continue

        hashes, label, segment = heading.groups()
        sections.append(_Section(level=len(hashes), label=label, segment=segment, lines=[]))

    _reject_skipped_levels(path, sections)

    return "\n".join(own_lines).strip(), _build_tree(sections, parent_key, lang, normative)


def _reject_skipped_levels(path: Path, sections: list[_Section]) -> None:
    previous = 1
    for section in sections:
        if section.level > previous + 1:
            raise PackFormatError(
                f"{path}: heading '{section.label}' jumps from level {previous} to "
                f"{section.level}. Clause depth follows heading depth, so levels cannot be skipped"
            )
        previous = section.level


def _build_tree(
    sections: list[_Section], parent_key: str, lang: str, normative: bool
) -> tuple[Clause, ...]:
    roots: list[Clause] = []
    open_clauses: list[tuple[_Section, str, list[Clause]]] = []

    def close(down_to: int) -> None:
        while open_clauses and open_clauses[-1][0].level >= down_to:
            section, key, children = open_clauses.pop()
            clause = Clause(
                key=key,
                clause_type=clause_type_for(section.segment),
                label=section.label or None,
                heading=None,
                body_text="\n".join(section.lines).strip(),
                lang=lang,
                normative=normative,
                children=tuple(children),
            )
            siblings = open_clauses[-1][2] if open_clauses else roots
            siblings.append(clause)

    for section in sections:
        close(down_to=section.level)
        parent = open_clauses[-1][1] if open_clauses else parent_key
        open_clauses.append((section, f"{parent}:{section.segment}", []))

    close(down_to=0)
    return tuple(roots)


def read_document(pack_dir: Path, document: PackDocument) -> list[Clause]:
    """Read every clause file in one document, in file name order."""
    directory = pack_dir / document.slug
    if not directory.is_dir():
        raise PackFormatError(
            f"{pack_dir}: pack.yaml lists document '{document.slug}' but {directory} is missing"
        )

    clauses = [
        read_clause_file(path, document_normative=document.normative)
        for path in sorted(directory.glob("*.md"))
    ]
    if len(clauses) != document.expected_clauses:
        raise PackFormatError(
            f"{directory}: pack.yaml expects {document.expected_clauses} clauses, "
            f"found {len(clauses)}. A clause lost between building the pack and "
            "committing it would otherwise be missing from every search."
        )

    for clause in clauses:
        expected_prefix = f"{document.slug}:"
        if not clause.key.startswith(expected_prefix):
            raise PackFormatError(
                f"{directory}: key '{clause.key}' does not start with '{expected_prefix}', "
                "so it would not resolve inside this document"
            )
    return clauses
