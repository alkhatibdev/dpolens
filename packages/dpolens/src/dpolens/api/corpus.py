"""The routes a surface actually uses: search, one clause, and documents.

Each handler authenticates through its dependency, calls one engine function and
returns. Anything here that built a query would have leaked upward.

Search is a POST rather than a GET on purpose. A question in a query string is
written to the access log of every proxy in front of the instance, which would
undo the redaction the query log performs two tables away, through infrastructure
this project does not control.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query, Request
from pydantic import BaseModel, Field

from dpolens.api import problems
from dpolens.api.dependencies import Configured, Delegated, Embedding, Opened, Reader
from dpolens.api.logging import logged, surface_of
from dpolens.api.schemas import (
    Clause,
    ClauseInContext,
    Document,
    DocumentInDetail,
    Documents,
    Result,
    Results,
)
from dpolens.engine.documents.read import (
    ClauseNotFound,
    get_clause,
    get_document,
    get_subtree,
    list_documents,
)
from dpolens.engine.logs.queries import Returned
from dpolens.engine.search.engine import search

router = APIRouter(prefix="/v1", tags=["corpus"])

MAX_QUERY = 1000
"""Longer than any question, and short enough that nobody can spend this
instance's CPU by asking it to embed a megabyte."""


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=MAX_QUERY, description="The question, in words")
    limit: int = Field(default=10, ge=1, le=50)
    lang: str = Field(default="en", max_length=20)
    expand: Literal["none", "siblings", "parent"] = Field(
        default="none", description="Also return the siblings, or the parent, of each hit"
    )
    as_of: date | None = Field(
        default=None,
        description="Read the corpus as it stood on this date, to cite what was in force then",
    )
    include_explanatory: bool = Field(
        default=False,
        description=(
            "Include text that explains without obliging, such as a recital. Off by default, "
            "because such text reads more like a question than the article that creates the duty"
        ),
    )
    explain: bool = Field(
        default=False, description="Include each retriever's ranking, for debugging"
    )


@router.post("/search", summary="Find the clauses that answer a question")
def run_search(
    request: Request,
    body: SearchRequest,
    who: Reader,
    opened: Opened,
    embedder: Embedding,
    settings: Configured,
    delegated: Delegated,
) -> Results:
    with logged(
        request,
        who,
        settings,
        operation="search",
        surface=surface_of(delegated),
        query=body.query,
    ) as asked:
        found = search(
            opened,
            embedder,
            body.query,
            limit=body.limit,
            lang=body.lang,
            expand=body.expand,
            as_of=body.as_of,
            normative_only=not body.include_explanatory,
        )
        asked.found([Returned.of(result.clause) for result in found])

    return Results(results=[Result.of(result, explain=body.explain) for result in found])


@router.get("/clauses/{key}", summary="Read one clause by its canonical key")
def read_clause(
    request: Request,
    who: Reader,
    opened: Opened,
    settings: Configured,
    delegated: Delegated,
    key: Annotated[str, Path(description="A canonical key, such as gdpr:art-17:para-1")],
    lang: Annotated[str | None, Query(max_length=20)] = None,
    as_of: Annotated[date | None, Query()] = None,
) -> ClauseInContext:
    with logged(
        request,
        who,
        settings,
        operation="get_clause",
        surface=surface_of(delegated),
        target=key,
    ) as asked:
        try:
            detail = get_clause(opened, key, lang=lang, as_of=as_of)
        except ClauseNotFound as missing:
            asked.status = "no_match"
            raise problems.not_found(str(missing)) from missing
        asked.found([Returned.of(detail.clause)])

    return ClauseInContext.of(detail)


@router.get("/clauses/{key}/subtree", summary="Read a clause and everything beneath it")
def read_subtree(
    request: Request,
    who: Reader,
    opened: Opened,
    settings: Configured,
    delegated: Delegated,
    key: Annotated[str, Path(description="A canonical key, such as gdpr:art-17")],
    lang: Annotated[str | None, Query(max_length=20)] = None,
    as_of: Annotated[date | None, Query()] = None,
) -> list[Clause]:
    """What an assistant wants once it has the top hit: the whole article, in order."""
    with logged(
        request,
        who,
        settings,
        operation="get_subtree",
        surface=surface_of(delegated),
        target=key,
    ) as asked:
        try:
            branch = get_subtree(opened, key, lang=lang, as_of=as_of)
        except ClauseNotFound as missing:
            asked.status = "no_match"
            raise problems.not_found(str(missing)) from missing
        asked.found([Returned.of(view) for view in branch])

    return [Clause.of(view) for view in branch]


@router.get("/documents", summary="List the documents in force")
def list_corpus(
    request: Request,
    who: Reader,
    opened: Opened,
    settings: Configured,
    delegated: Delegated,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    as_of: Annotated[date | None, Query()] = None,
) -> Documents:
    with logged(
        request, who, settings, operation="list_documents", surface=surface_of(delegated)
    ) as asked:
        documents, total = list_documents(opened, limit=limit, offset=offset, as_of=as_of)
        asked.status = "ok" if documents else "no_match"

    return Documents(
        documents=[Document.of(summary) for summary in documents],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/documents/{slug}", summary="One document and its top-level structure")
def read_document(
    request: Request,
    who: Reader,
    opened: Opened,
    settings: Configured,
    delegated: Delegated,
    slug: Annotated[str, Path(description="The document's slug, such as gdpr")],
    as_of: Annotated[date | None, Query()] = None,
) -> DocumentInDetail:
    with logged(
        request,
        who,
        settings,
        operation="get_document",
        surface=surface_of(delegated),
        target=slug,
    ) as asked:
        try:
            detail = get_document(opened, slug, as_of=as_of)
        except ClauseNotFound as missing:
            asked.status = "no_match"
            raise problems.not_found(str(missing)) from missing
        asked.status = "ok"

    return DocumentInDetail.of(detail)
