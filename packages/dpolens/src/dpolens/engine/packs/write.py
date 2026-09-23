"""Writing clauses out as pack files, and checking nothing was lost."""

from __future__ import annotations

from pathlib import Path

import yaml

from dpolens.engine.documents import references
from dpolens.engine.packs.format import Clause


class CoverageError(Exception):
    """Text in the source did not end up in exactly one clause."""


def render(clause: Clause, links: dict[str, list[references.Reference]]) -> str:
    """Render one clause and its children as a pack file."""
    front: dict[str, object] = {"key": clause.key, "lang": clause.lang}
    if clause.label:
        front["label"] = clause.label
    if clause.heading:
        front["title"] = clause.heading
    if not clause.normative:
        front["normative"] = False

    entries: list[dict[str, str]] = []
    for stated_by in clause.walk():
        for reference in links.get(stated_by.key, []):
            entry = {"key": reference.target_key, "text": reference.raw_text}
            if stated_by.key != clause.key:
                entry["from"] = stated_by.key
            entries.append(entry)
    if entries:
        front["cross_references"] = entries

    body = [clause.body_text] if clause.body_text else []
    for child in clause.children:
        body.extend(_render_child(child, links, depth=2))

    matter = yaml.safe_dump(front, allow_unicode=True, sort_keys=False, width=88).strip()
    return f"---\n{matter}\n---\n\n" + "\n\n".join(body).strip() + "\n"


def _render_child(
    clause: Clause, links: dict[str, list[references.Reference]], depth: int
) -> list[str]:
    segment = clause.key.rsplit(":", 1)[-1]
    # A subparagraph or a dash item has no number of its own, so the heading
    # carries only the key segment.
    marker = "#" * depth
    label = f" {clause.label}" if clause.label else ""
    lines = [f"{marker}{label} {{#{segment}}}"]
    if clause.body_text:
        lines.append(clause.body_text)
    for child in clause.children:
        lines.extend(_render_child(child, links, depth + 1))
    return lines


def link_clauses(
    clauses: list[Clause], document_slug: str, tradition: str = "eu_law"
) -> tuple[dict[str, list[references.Reference]], list[tuple[str, references.Reference]]]:
    """Resolve every reference in a document against the keys it actually has.

    Returns the links to store, and the references that point nowhere. The
    second list is not a warning to ignore: a reference that does not resolve
    means the text cites something the document does not contain.
    """
    known = {found.key for clause in clauses for found in clause.walk()}
    links: dict[str, list[references.Reference]] = {}
    dangling: list[tuple[str, references.Reference]] = []

    for clause in clauses:
        for found in clause.walk():
            resolution = references.resolve(
                references.extract(found.body_text, document_slug, tradition), known
            )
            if resolution.resolved:
                # Keyed by the clause whose text states the reference, not by the
                # file it happens to live in: a point that cites Article 6(1) is
                # what refers to it, and what a reader of that point needs.
                links.setdefault(found.key, []).extend(resolution.resolved)
            dangling.extend((found.key, reference) for reference in resolution.unresolved)

    for key, stored in links.items():
        links[key] = sorted(set(stored), key=lambda reference: reference.target_key)
    return links, dangling


def write_document(directory: Path, clauses: list[Clause], document_slug: str) -> int:
    """Write one file per clause, named after its last key segment."""
    links, _ = link_clauses(clauses, document_slug)
    directory.mkdir(parents=True, exist_ok=True)
    for clause in clauses:
        name = clause.key.rsplit(":", 1)[-1]
        (directory / f"{name}.md").write_text(render(clause, links), encoding="utf-8")
    return len(clauses)


def check_coverage(source_text: str, clause: Clause) -> None:
    """Every character of the source has to land in exactly one clause.

    Whitespace is ignored, because a pack file lays the text out differently. A
    silently dropped paragraph is the worst failure this project can have, since
    nothing downstream can detect a clause that is simply absent.
    """
    stored = "".join(
        part
        for found in clause.walk()
        for part in (found.label or "", found.heading or "", found.body_text)
    )
    expected = _squash(source_text)
    actual = _squash(stored)
    if expected == actual:
        return

    position = _first_difference(expected, actual)
    raise CoverageError(
        f"{clause.key}: the pack file does not carry the source text exactly. "
        f"First difference at character {position}: "
        f"source has {expected[position : position + 60]!r}, "
        f"pack has {actual[position : position + 60]!r}"
    )


def _squash(text: str) -> str:
    return "".join(text.split())


def _first_difference(expected: str, actual: str) -> int:
    for position, (left, right) in enumerate(zip(expected, actual, strict=False)):
        if left != right:
            return position
    return min(len(expected), len(actual))
