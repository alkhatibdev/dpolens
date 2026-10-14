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
from dpolens.engine.packs.selection import UnknownLaw, scope_for
from dpolens.engine.search import SEARCHABLE_LANGUAGES
from dpolens.engine.search.engine import search

router = APIRouter(
    prefix="/v1",
    tags=["corpus"],
    # Every route here authenticates, so every route can fail these ways.
    responses=problems.responses(401, 403, 429),
)

MAX_QUERY = 1000
"""Longer than any question, and short enough that nobody can spend this
instance's CPU by asking it to embed a megabyte."""


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=MAX_QUERY, description="The question, in words")
    limit: int = Field(default=10, ge=1, le=50)
    lang: str | None = Field(
        default=None,
        max_length=20,
        description=(
            "The language of the question, en or ar. Left out, it is read from the letters the "
            "question is written in. Each clause comes back in it where the clause has text in "
            "it, and otherwise in the language that prevails"
        ),
    )
    laws: list[Annotated[str, Field(max_length=100)]] | None = Field(
        default=None,
        max_length=20,
        description=(
            "The laws to search, by slug, such as gdpr or uae-pdpl. Left out, the "
            "organisation's selected laws, or every loaded law until it has chosen. A law "
            "outside the selection comes back with in_selected_laws false"
        ),
    )
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
    # Refused before the log, like any other request this instance cannot read.
    if body.lang is not None and body.lang not in SEARCHABLE_LANGUAGES:
        raise problems.unsupported_language(body.lang, SEARCHABLE_LANGUAGES)
    try:
        scope = scope_for(opened, body.laws)
    except UnknownLaw as unknown:
        raise problems.unknown_law(unknown.unknown, unknown.loaded) from unknown

    with logged(
        request,
        who,
        settings,
        operation="search",
        surface=surface_of(delegated, who),
        query=body.query,
    ) as asked:
        asked.scope = "other" if scope.outside_selection else "selected"
        found = search(
            opened,
            embedder,
            body.query,
            limit=body.limit,
            lang=body.lang,
            expand=body.expand,
            as_of=body.as_of,
            normative_only=not body.include_explanatory,
            scope=scope,
        )
        asked.found([Returned.of(result.clause) for result in found])

    return Results(
        laws=list(scope.laws),
        results=[Result.of(result, explain=body.explain) for result in found],
    )


@router.get(
    "/clauses/{key}",
    summary="Read one clause by its canonical key",
    responses=problems.responses(404),
)
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
        surface=surface_of(delegated, who),
        target=key,
    ) as asked:
        try:
            detail = get_clause(opened, key, lang=lang, as_of=as_of)
        except ClauseNotFound as missing:
            asked.status = "no_match"
            raise problems.not_found(str(missing)) from missing
        asked.found([Returned.of(detail.clause)])

    return ClauseInContext.of(detail)


@router.get(
    "/clauses/{key}/subtree",
    summary="Read a clause and everything beneath it",
    responses=problems.responses(404),
)
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
        surface=surface_of(delegated, who),
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
        request, who, settings, operation="list_documents", surface=surface_of(delegated, who)
    ) as asked:
        documents, total = list_documents(opened, limit=limit, offset=offset, as_of=as_of)
        scope = scope_for(opened)
        asked.status = "ok" if documents else "no_match"

    return Documents(
        documents=[
            Document.of(summary, in_selected_laws=scope.is_selected(summary.pack_slug))
            for summary in documents
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/documents/{slug}",
    summary="One document and its top-level structure",
    responses=problems.responses(404),
)
def read_document(
    request: Request,
    who: Reader,
    opened: Opened,
    settings: Configured,
    delegated: Delegated,
    slug: Annotated[str, Path(description="The document's slug, such as gdpr")],
    as_of: Annotated[date | None, Query()] = None,
    lang: Annotated[
        str | None,
        Query(description="Name the outline's clauses in this language where they have text in it"),
    ] = None,
) -> DocumentInDetail:
    with logged(
        request,
        who,
        settings,
        operation="get_document",
        surface=surface_of(delegated, who),
        target=slug,
    ) as asked:
        try:
            detail = get_document(opened, slug, as_of=as_of, lang=lang)
        except ClauseNotFound as missing:
            asked.status = "no_match"
            raise problems.not_found(str(missing)) from missing
        asked.status = "ok"

    selected = scope_for(opened).is_selected(detail.summary.pack_slug)
    return DocumentInDetail.of(detail, in_selected_laws=selected)
