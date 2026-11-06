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

from datetime import date
from typing import Any

from pydantic import BaseModel, Field

LANGUAGES = {"ar": "Arabic", "en": "English"}
"""Names for the languages packs carry, so a citation says Arabic rather than ar."""


class Coming(BaseModel):
    """The words an amendment gives a clause from a later day."""

    text: str = Field(description="The words as the amendment gives them, word for word")
    in_force_from: str
    set_by: str | None = Field(description="The amendment that brings them")


class Clause(BaseModel):
    """One clause, and what it takes to check it."""

    key: str = Field(description="The canonical key a citation points at")
    citation: str = Field(description="One line naming the clause, its version and its date")
    text: str = Field(description="The clause as it stands, word for word")
    breadcrumb: list[str] = Field(description="Where the clause sits, outermost first")
    obliges: bool = Field(
        description="False for text that explains without obliging, such as a recital"
    )
    document: str = Field(description="The document's title, in the language of the text")
    law: str | None = Field(
        description="What people call the law, such as GDPR. Null for the organisation's policy"
    )
    version: str | None
    in_force: bool = Field(
        description=(
            "Whether this text applies on the day asked about. A provision can be returned "
            "before it starts to apply, so a duty can be prepared for: say so when citing it"
        )
    )
    in_force_from: str | None = Field(
        description="The day this text starts to apply, or null while nothing has set it"
    )
    in_force_until: str | None = Field(
        description="The day it stops applying, when a law or an amendment has set one"
    )
    dates_set_by: str | None = Field(
        default=None,
        description="What set those days, when anything other than the version's date did",
    )
    coming: Coming | None = Field(
        default=None,
        description=(
            "The words an amendment gives this clause from a later day. Mention them when the "
            "answer depends on what will apply then"
        ),
    )
    lang: str
    authoritative: bool = Field(description="Whether this language is the one that prevails in law")
    prevails: str | None = Field(
        default=None,
        description="For a clause shown in translation, the language whose text prevails",
    )
    prevailing_text: str | None = Field(
        default=None,
        description="For a clause shown in translation, the text that prevails, word for word",
    )
    jurisdiction: str | None = Field(description="Null for an organisation's own policy")
    trust_tier: str | None = Field(
        description=(
            "verified when a named maintainer checked the pack against the official source, "
            "community when it passed validation only, null for an organisation's own policy"
        )
    )
    source_url: str | None = Field(description="Where the text was taken from, for a law")
    archived: bool = Field(
        default=False,
        description=(
            "True for a clause of a policy the organisation has archived, which no longer "
            "applies. Say so when citing it"
        ),
    )

    @classmethod
    def of(
        cls,
        clause: dict[str, Any],
        breadcrumb: list[dict[str, Any]] | None = None,
        as_of: date | None = None,
    ) -> Clause:
        trail = [name for view in breadcrumb or [] if (name := _names(view))]
        coming = clause.get("coming")
        return cls(
            key=clause["key"],
            citation=citation_for(clause, trail, as_of),
            text=clause["text"],
            breadcrumb=trail,
            obliges=clause["is_normative"],
            document=clause["document_title"],
            law=clause.get("law_short_name"),
            version=clause["version_label"],
            # An instance older than this server sends no days of its own: its texts apply
            # from their version's date, and never stop.
            in_force=clause.get("in_force", True),
            in_force_from=clause.get("in_force_from", clause["effective_date"]),
            in_force_until=clause.get("in_force_until"),
            dates_set_by=clause.get("dates_set_by"),
            coming=(
                Coming(
                    text=coming["text"],
                    in_force_from=coming["in_force_from"],
                    set_by=coming.get("dates_set_by"),
                )
                if coming
                else None
            ),
            lang=clause["lang"],
            authoritative=clause["is_authoritative"],
            prevails=_prevails(clause),
            prevailing_text=clause.get("authoritative_text") if _prevails(clause) else None,
            jurisdiction=clause["jurisdiction"],
            trust_tier=clause["trust_tier"],
            source_url=clause["source_url"],
            archived=bool(clause.get("archived", False)),
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
    now: str | None = Field(
        default=None,
        description=(
            "For a policy's clause read in a version that is no longer in force, where the "
            "same rule is in the version in force. A policy's keys follow its printed numbers, "
            "so the rule may have another key now"
        ),
    )
    formerly: str | None = Field(
        default=None,
        description="Set when this key named a different rule in the policy's version before",
    )


class Document(BaseModel):
    """One document this instance can cite."""

    slug: str = Field(description="The name to pass to get_document")
    title: str
    law: str | None = Field(
        description="What people call the law, such as GDPR. Null for the organisation's policy"
    )
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
            title=_english(document["title"]),
            law=_english(document["short_name"]) if document.get("short_name") else None,
            kind=document["kind"],
            version=document["version_label"],
            in_force_since=document["effective_date"],
            clauses=document["clauses"],
            languages=list(document["languages"]),
            jurisdiction=_english(document["jurisdiction"]) if document["jurisdiction"] else None,
            trust_tier=document["trust_tier"],
            source_url=document["source_url"],
        )


def _english(by_lang: dict[str, str] | str) -> str:
    """A name in English, which every law has, else the one a policy has in its language. An
    instance older than this server sends the one name it has."""
    if isinstance(by_lang, str):
        return by_lang
    return by_lang.get("en") or next(iter(by_lang.values()))


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


def citation_for(clause: dict[str, Any], trail: list[str], as_of: date | None = None) -> str:
    """One line somebody can check, built from the fields rather than remembered."""
    where = " > ".join([*trail, _names(clause) or clause["key"]])
    version = clause["version_label"] or "unversioned"
    citation = (
        f"{clause['document_title']}, {where} ({clause['key']}), "
        f"version {version}, {_in_force(clause, as_of or date.today())}"
    )
    prevails = _prevails(clause)
    if prevails:
        name = LANGUAGES.get(prevails, prevails)
        citation += f". A translation: where the texts differ, the {name} text prevails"
    return citation


def where_now(now: dict[str, Any]) -> str:
    """Where a policy's rule is in the version in force, as a sentence to pass on."""
    version = f"version {now['version_label']}, in force since {now['effective_date']}"
    if now["key"] is None:
        return f"This rule is not in {version}."
    words = "in new words" if now["changed"] else "word for word"
    if now["moved"]:
        return f"In {version}, this rule is {now['key']}, {words}. Cite that key for it today."
    return f"In {version}, this rule keeps its key, {words}."


def formerly(key: str, before: dict[str, Any]) -> str:
    """What a policy's key named in the version before, as a sentence to pass on."""
    went = f"which is {before['now']} in this version" if before["now"] else "since removed"
    return (
        f"In version {before['version_label']}, {key} was a different rule, {went}. A citation "
        f"of {key} that names version {before['version_label']} means that rule."
    )


def _in_force(clause: dict[str, Any], as_of: date) -> str:
    """When the text applies, as a citation says it."""
    since = clause.get("in_force_from", clause["effective_date"])
    until = clause.get("in_force_until")
    if clause.get("in_force", True):
        return f"in force since {since}" + (f", until {until}" if until else "")
    if until is not None and date.fromisoformat(until) <= as_of:
        return f"no longer in force since {until}"
    if since is None:
        return "not in force yet: no date set"
    return f"in force from {since}" + (f" until {until}" if until else "")


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
