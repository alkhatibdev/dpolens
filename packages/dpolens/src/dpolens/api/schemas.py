"""What the API returns, which is the part that is hard to change later.

Every clause carries what it takes to check it: the text as it stands, the key a
citation uses, where it sits, whether it obliges anyone, which version it came
from and when that version took effect, and for a law, which pack, whose law it
is, where the text was taken from and how far it has been checked.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from dpolens.engine.documents.read import (
    ClauseDetail,
    ClauseView,
    DocumentDetail,
    DocumentSummary,
    OutlineItem,
)
from dpolens.engine.search.engine import SearchResult


class Clause(BaseModel):
    key: str = Field(description="The canonical key a citation points at")
    clause_type: str
    label: str | None = Field(description="The numbering the law itself uses, such as 1. or (a)")
    heading: str | None
    text: str = Field(description="The clause as it stands, verbatim")
    lang: str
    is_authoritative: bool = Field(
        description="Whether this language is the one that prevails in law"
    )
    authoritative_language: str | None = Field(
        default=None,
        description="For a law, the language whose text prevails where its texts disagree. "
        "Null for an organisation's own policy",
    )
    is_normative: bool = Field(
        description="False for text that explains without obliging, such as a recital"
    )
    depth: int
    document_title: str
    document_slug: str
    version_label: str | None
    effective_date: date
    pack_slug: str | None = Field(description="Null for an organisation's own policy")
    jurisdiction: str | None
    trust_tier: str | None = Field(
        description="verified when a named maintainer checked the pack against the official "
        "source, community when it has passed validation only, null for a policy"
    )
    source_url: str | None

    @classmethod
    def of(cls, view: ClauseView) -> Clause:
        return cls(**vars(view))


class CrossReference(BaseModel):
    key: str
    text: str = Field(description="The words in the clause that pointed at it")


class Result(BaseModel):
    clause: Clause
    score: float
    breadcrumb: list[Clause] = Field(description="Where the clause sits, outermost first")
    cross_references: list[CrossReference]
    expanded: list[Clause] = Field(
        default_factory=list, description="Siblings or the parent, when the request asked"
    )
    ranks: dict[str, int] | None = Field(
        default=None,
        description=(
            "Where each retriever placed this clause, when the request asked to explain. "
            "A debugging aid whose meaning changes when the fusion rule does"
        ),
    )

    @classmethod
    def of(cls, found: SearchResult, *, explain: bool) -> Result:
        return cls(
            clause=Clause.of(found.clause),
            score=found.score,
            breadcrumb=[Clause.of(view) for view in found.breadcrumb],
            cross_references=[
                CrossReference(key=key, text=text) for key, text in found.cross_references
            ],
            expanded=[Clause.of(view) for view in found.expanded],
            ranks=dict(found.ranks) if explain else None,
        )


class Results(BaseModel):
    results: list[Result]


class ClauseInContext(BaseModel):
    clause: Clause
    breadcrumb: list[Clause]
    children: list[Clause]
    cross_references: list[CrossReference]

    @classmethod
    def of(cls, detail: ClauseDetail) -> ClauseInContext:
        return cls(
            clause=Clause.of(detail.clause),
            breadcrumb=[Clause.of(view) for view in detail.breadcrumb],
            children=[Clause.of(view) for view in detail.children],
            cross_references=[
                CrossReference(key=key, text=text) for key, text in detail.cross_references
            ],
        )


class Document(BaseModel):
    slug: str
    title: str
    kind: str = Field(description="law or org_policy")
    version_label: str | None
    effective_date: date
    clauses: int
    languages: list[str]
    pack_slug: str | None
    jurisdiction: str | None
    trust_tier: str | None
    source_url: str | None

    @classmethod
    def of(cls, summary: DocumentSummary) -> Document:
        return cls(**{**vars(summary), "languages": list(summary.languages)})


class Documents(BaseModel):
    documents: list[Document]
    total: int = Field(description="How many documents are in force, ignoring limit and offset")
    limit: int
    offset: int


class OutlineEntry(BaseModel):
    """What a top-level clause is, without what it says.

    The text is absent on purpose: an outline that carried it would return whole
    documents for anything whose top level holds real text, such as recitals.
    Read the words with the clause routes.
    """

    key: str
    clause_type: str
    label: str | None
    heading: str | None
    is_normative: bool
    children: int = Field(description="How many clauses sit directly beneath this one")

    @classmethod
    def of(cls, item: OutlineItem) -> OutlineEntry:
        return cls(**vars(item))


class DocumentInDetail(BaseModel):
    document: Document
    outline: list[OutlineEntry] = Field(
        description="The top level only, without text. Read further with a clause key"
    )

    @classmethod
    def of(cls, detail: DocumentDetail) -> DocumentInDetail:
        return cls(
            document=Document.of(detail.summary),
            outline=[OutlineEntry.of(item) for item in detail.outline],
        )
