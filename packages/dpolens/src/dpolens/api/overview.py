"""The Overview, and how often one clause was cited, for anyone who may read every question.

Both count what the query log holds and name nobody: they are what a person with
`queries.read_all` may already see, added up. Days are the reader's own, from
`tz`, so "today" on the page is today where the reader is.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, Field

from dpolens.api import problems
from dpolens.api.dependencies import Opened, requires
from dpolens.api.logs import ClauseName
from dpolens.engine.auth import permissions as catalog
from dpolens.engine.auth.tokens import Authenticated
from dpolens.engine.logs import reading
from dpolens.engine.packs.selection import loaded_laws, scope_for

router = APIRouter(prefix="/v1", tags=["overview"], responses=problems.responses(401, 403, 429))

Reader = Annotated[Authenticated, Depends(requires(catalog.QUERIES_READ_ALL))]
Surface = Literal["dashboard", "mcp", "api", "slack", "github_action"]

Days = Annotated[int, Query(ge=1, le=366, description="How many days, today the last")]
Zone = Annotated[
    str, Query(max_length=64, description="The reader's time zone, such as Asia/Dubai")
]


def _window(days: int, tz: str) -> reading.Window:
    try:
        zone = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as unknown:
        raise problems.invalid_request(
            f"{tz!r} is not a time zone this instance knows"
        ) from unknown
    return reading.Window.ending_today(days, zone)


class DayCount(BaseModel):
    day: date
    assistants: int = Field(description="Asked through the MCP server")
    dashboard: int
    other: int


class Cited(BaseModel):
    clause: ClauseName
    count: int


class Source(BaseModel):
    pack_slug: str | None = Field(
        description="The law's pack, or null for the organisation's policies"
    )
    title: str
    count: int


class Unanswered(BaseModel):
    id: str
    created_at: datetime
    surface: Surface
    question: str


class Law(BaseModel):
    slug: str
    name: str


class Overview(BaseModel):
    days: int
    since: datetime
    until: datetime
    questions: int
    previous_questions: int = Field(description="In the same number of days just before")
    answered: int
    found_nothing: int
    by_day: list[DayCount]
    most_cited: list[Cited] = Field(description="First result of a search, or read by key")
    sources: list[Source] = Field(
        description="Where the first result of an answered search came from"
    )
    unanswered: list[Unanswered] = Field(description="The latest searches that found nothing")
    laws: list[Law] = Field(description="The laws searches cover now")


class ClauseDay(BaseModel):
    day: date
    count: int


class Activity(BaseModel):
    key: str
    days: int
    total: int
    by_day: list[ClauseDay]


@router.get(
    "/overview", summary="What was asked, and what answered it", responses=problems.responses(400)
)
def describe(who: Reader, opened: Opened, days: Days = 7, tz: Zone = "UTC") -> Overview:
    assert who
    week = reading.overview(opened, _window(days, tz))
    selected = set(scope_for(opened).selected)
    return Overview(
        days=week.window.days,
        since=week.window.since,
        until=week.window.until,
        questions=week.questions,
        previous_questions=week.previous,
        answered=week.answered,
        found_nothing=week.found_nothing,
        by_day=[
            DayCount(
                day=day.day, assistants=day.assistants, dashboard=day.dashboard, other=day.other
            )
            for day in week.by_day
        ],
        most_cited=[
            Cited(clause=ClauseName.of(cited.name), count=cited.count) for cited in week.most_cited
        ],
        sources=[
            Source(pack_slug=source.pack_slug, title=source.title, count=source.count)
            for source in week.sources
        ],
        unanswered=[
            Unanswered(
                id=str(question.id),
                created_at=question.created_at,
                surface=cast(Surface, question.surface),
                question=question.query,
            )
            for question in week.unanswered
        ],
        laws=[
            Law(slug=pack.slug, name=pack.name)
            for pack in loaded_laws(opened)
            if pack.slug in selected
        ],
    )


@router.get(
    "/clauses/{key}/activity",
    summary="How often one clause was cited, day by day",
    responses=problems.responses(400),
)
def clause_activity(
    who: Reader,
    opened: Opened,
    key: Annotated[
        str, Path(max_length=200, description="A canonical key, such as gdpr:art-17:para-1")
    ],
    days: Days = 7,
    tz: Zone = "UTC",
) -> Activity:
    assert who
    activity = reading.clause_activity(opened, key, _window(days, tz))
    return Activity(
        key=key,
        days=activity.window.days,
        total=activity.total,
        by_day=[ClauseDay(day=day, count=count) for day, count in activity.by_day],
    )
