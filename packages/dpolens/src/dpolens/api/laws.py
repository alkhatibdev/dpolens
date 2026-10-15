"""Which laws apply to the organisation, and so what a search covers.

A search covers the selected laws and the organisation's own policies. Until
somebody chooses, every loaded law is searched. Choosing needs `settings.manage`,
and each change is written to the governance log, as it is from the command line.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from dpolens.api import problems
from dpolens.api.dependencies import Opened, actor_of, requires
from dpolens.engine.auth import permissions as catalog
from dpolens.engine.auth.tokens import Authenticated
from dpolens.engine.documents.read import list_laws
from dpolens.engine.logs import governance_view
from dpolens.engine.logs.governance import LAWS_SELECTED, LAWS_SELECTION_CLEARED
from dpolens.engine.packs.selection import (
    UnknownLaw,
    clear_selection,
    select_laws,
    selected_laws,
)
from dpolens.engine.session import EngineSession

router = APIRouter(prefix="/v1", tags=["laws"], responses=problems.responses(401, 403, 429))

Chooser = Annotated[Authenticated, Depends(requires(catalog.SETTINGS_MANAGE))]
TrustTier = Literal["verified", "community"]
Via = Literal["dashboard", "api", "cli"]


class LoadedLaw(BaseModel):
    slug: str
    name: str
    jurisdiction: str
    version: str
    effective_date: date = Field(description="The day the law took effect")
    trust_tier: TrustTier
    authoritative_language: str = Field(description="The language whose text prevails")
    languages: list[str]
    articles: int
    recitals: int
    document: str | None = Field(description="The document that holds its articles, by slug")
    searched: bool = Field(
        description=(
            "Whether a search covers it without naming it: it is selected, or nobody has "
            "chosen and every law is searched"
        )
    )


class LawsChange(BaseModel):
    at: datetime
    cleared: bool = Field(description="Whether the change went back to every law")
    by: str | None = Field(description="Who made it, or null for the command line")
    via: Via


class Laws(BaseModel):
    laws: list[LoadedLaw]
    selected: list[str] | None = Field(
        description="The selected laws by slug, or null while nobody has chosen"
    )
    changed: LawsChange | None = Field(
        description="The latest change to the selection, or null when there has never been one"
    )


class LawSelection(BaseModel):
    laws: list[Annotated[str, Field(max_length=100)]] = Field(
        min_length=1,
        max_length=50,
        description="The laws that apply, by slug. Going back to every law is a DELETE",
    )


def _laws(opened: EngineSession) -> Laws:
    selected = selected_laws(opened)
    latest = governance_view.latest_of(opened, (LAWS_SELECTED, LAWS_SELECTION_CLEARED))
    return Laws(
        laws=[
            LoadedLaw(
                slug=law.slug,
                name=law.name,
                jurisdiction=law.jurisdiction,
                version=law.version,
                effective_date=law.effective_date,
                trust_tier=cast(TrustTier, law.trust_tier),
                authoritative_language=law.authoritative_language,
                languages=list(law.languages),
                articles=law.articles,
                recitals=law.recitals,
                document=law.document,
                searched=selected is None or law.slug in selected,
            )
            for law in list_laws(opened)
        ],
        selected=selected,
        changed=(
            LawsChange(
                at=latest.occurred_at,
                cleared=latest.action == LAWS_SELECTION_CLEARED,
                by=latest.actor.display_name if latest.actor else None,
                via=cast(Via, latest.details.get("via", "cli")),
            )
            if latest
            else None
        ),
    )


@router.get("/laws", summary="The loaded laws, and which of them a search covers")
def list_loaded(who: Chooser, opened: Opened) -> Laws:
    assert who
    return _laws(opened)


@router.put(
    "/laws/selection",
    summary="Choose which laws apply",
    responses=problems.responses(422),
)
def choose(body: LawSelection, who: Chooser, opened: Opened) -> Laws:
    try:
        select_laws(opened, body.laws, actor=actor_of(who))
    except UnknownLaw as unknown:
        raise problems.unknown_law(unknown.unknown, unknown.loaded) from unknown
    return _laws(opened)


@router.delete("/laws/selection", summary="Go back to searching every loaded law")
def clear(who: Chooser, opened: Opened) -> Laws:
    clear_selection(opened, actor=actor_of(who))
    return _laws(opened)
