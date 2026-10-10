"""What a tool hands back.

Each shape carries what it takes to check a claim: the clause word for word, the
key a citation points at, the document and version it came from, and the date
that version took effect. A client application reads these as data, and the
model reads them as the result of the call, so there is one answer rather than
two that can disagree.

`citation` is built here rather than left to the model, because a citation
assembled from remembered fields is how a wrong one gets written.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

LANGUAGES = {"ar": "Arabic", "en": "English"}
"""Names for the languages packs carry, so a citation says Arabic rather than ar."""


class Clause(BaseModel):
    """One clause, and what it takes to check it."""

    key: str = Field(description="The canonical key a citation points at")
    citation: str = Field(description="One line naming the clause, its version and its date")
    text: str = Field(description="The clause as it stands, word for word")
    breadcrumb: list[str] = Field(description="Where the clause sits, outermost first")
    obliges: bool = Field(
        description="False for text that explains without obliging, such as a recital"
    )
    document: str
    version: str | None
    in_force_since: str = Field(description="The date this version took effect")
    lang: str
    authoritative: bool = Field(description="Whether this language is the one that prevails in law")
    prevails: str | None = Field(
        default=None,
        description="For a clause shown in translation, the language whose text prevails",
    )
    jurisdiction: str | None = Field(description="Null for an organisation's own policy")
    trust_tier: str | None = Field(
        description=(
            "verified when a named maintainer checked the pack against the official source, "
            "community when it passed validation only, null for an organisation's own policy"
        )
    )
    source_url: str | None = Field(description="Where the text was taken from, for a law")

    @classmethod
    def of(cls, clause: dict[str, Any], breadcrumb: list[dict[str, Any]] | None = None) -> Clause:
        trail = [name for view in breadcrumb or [] if (name := _names(view))]
        return cls(
            key=clause["key"],
            citation=citation_for(clause, trail),
            text=clause["text"],
            breadcrumb=trail,
            obliges=clause["is_normative"],
            document=clause["document_title"],
            version=clause["version_label"],
            in_force_since=clause["effective_date"],
            lang=clause["lang"],
            authoritative=clause["is_authoritative"],
            prevails=_prevails(clause),
            jurisdiction=clause["jurisdiction"],
            trust_tier=clause["trust_tier"],
            source_url=clause["source_url"],
        )


class Match(Clause):
    """A clause a search returned, with what else it points at."""

    score: float = Field(description="Higher is a better match. Comparable within one search only")
    cross_references: list[str] = Field(
        description="Keys this clause's own words point at, to read with get_clause"
    )


class Found(BaseModel):
    """What a search found, best match first."""

    searched: str = Field(description="What was searched, and as of when")
    results: list[Match]


class ClauseInContext(BaseModel):
    """One clause, where it sits, and what sits beneath it."""

    clause: Clause
    children: list[Clause] = Field(description="The clauses directly beneath this one")
    cross_references: list[str] = Field(description="Keys this clause's own words point at")
    subtree: list[Clause] = Field(
        default_factory=list,
        description="This clause and everything beneath it in reading order, when asked for",
    )


class Document(BaseModel):
    """One document this instance can cite."""

    slug: str = Field(description="The name to pass to get_document")
    title: str
    kind: str = Field(description="law, or org_policy for the organisation's own")
    version: str | None
    in_force_since: str
    clauses: int
    languages: list[str]
    jurisdiction: str | None
    trust_tier: str | None
    source_url: str | None

    @classmethod
    def of(cls, document: dict[str, Any]) -> Document:
        return cls(
            slug=document["slug"],
            title=document["title"],
            kind=document["kind"],
            version=document["version_label"],
            in_force_since=document["effective_date"],
            clauses=document["clauses"],
            languages=list(document["languages"]),
            jurisdiction=document["jurisdiction"],
            trust_tier=document["trust_tier"],
            source_url=document["source_url"],
        )


class Documents(BaseModel):
    """What this instance can cite today."""

    documents: list[Document]
    total: int = Field(description="How many documents are in force, ignoring limit and offset")


class OutlineEntry(BaseModel):
    """What a top-level clause is, without what it says."""

    key: str
    label: str | None = Field(description="The numbering the document itself uses")
    heading: str | None
    obliges: bool
    children: int = Field(description="How many clauses sit directly beneath this one")


class DocumentInDetail(BaseModel):
    """One document and its top level.

    The text is left out on purpose: a document of a thousand clauses does not
    belong in one answer. Read the words with get_clause.
    """

    document: Document
    outline: list[OutlineEntry]


def citation_for(clause: dict[str, Any], trail: list[str]) -> str:
    """One line somebody can check, built from the fields rather than remembered."""
    where = " > ".join([*trail, _names(clause) or clause["key"]])
    version = clause["version_label"] or "unversioned"
    citation = (
        f"{clause['document_title']}, {where} ({clause['key']}), "
        f"version {version}, in force since {clause['effective_date']}"
    )
    prevails = _prevails(clause)
    if prevails:
        name = LANGUAGES.get(prevails, prevails)
        citation += f". A translation: where the texts differ, the {name} text prevails"
    return citation


def _prevails(clause: dict[str, Any]) -> str | None:
    """The language to rely on, when the clause in hand is not in it."""
    if clause.get("is_authoritative", True):
        return None
    language = clause.get("authoritative_language")
    return str(language) if language else None


def _names(view: dict[str, Any]) -> str:
    """What a clause is called: its heading, or the numbering the document uses."""
    heading = (view.get("heading") or "").strip()
    label = (view.get("label") or "").strip().rstrip(".")
    if heading and label:
        return f"{label} {heading}"
    return heading or label
