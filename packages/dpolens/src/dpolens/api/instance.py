"""What a signed-in person needs to know about the instance itself.

The MCP server's URL is a setting rather than something the dashboard works out,
because behind a proxy or on another port nothing on the page can know it.

The settings are read here and changed nowhere. Most are fixed when the instance starts, so
changing one is a change to its environment and a restart. Whether searches use the search
questions is changed with `dpolens search-questions`, which the governance log records.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from dpolens import __version__
from dpolens.api import problems
from dpolens.api.dependencies import Caller, Configured, Opened, requires
from dpolens.api.limits import SIGN_IN_FAILURES, SIGN_IN_WINDOW
from dpolens.engine.auth import permissions as catalog
from dpolens.engine.auth.tokens import Authenticated
from dpolens.engine.instance import this_instance
from dpolens.engine.logs.redaction import BUILT_IN
from dpolens.engine.search.questions import loaded_files, questions_on

router = APIRouter(prefix="/v1", tags=["instance"], responses=problems.responses(401, 403, 429))

SettingsReader = Annotated[Authenticated, Depends(requires(catalog.SETTINGS_MANAGE))]


class Instance(BaseModel):
    version: str
    mcp_url: str = Field(description="The MCP server's URL, for an AI assistant's configuration")


@router.get("/instance", summary="The version, and where AI assistants connect")
def describe(who: Caller, settings: Configured) -> Instance:
    assert who  # any signed-in caller
    return Instance(version=__version__, mcp_url=settings.public_mcp_url)


class QuestionsLogSettings(BaseModel):
    retention_days: int | None = Field(
        description=(
            "How many days a question is kept before it is deleted, counted from the day it "
            "was asked, or null when questions are kept"
        )
    )
    redacted: list[str] = Field(
        description="What every instance takes out of a question before storing it"
    )
    added_patterns: list[str] = Field(
        description="The names of the patterns this instance takes out as well"
    )


class SignInSettings(BaseModel):
    idle_minutes: int = Field(description="How long a session may go unused before it ends")
    lifetime_hours: int = Field(description="How long a session lasts at most")
    wrong_passwords: int = Field(
        description="Wrong passwords for one email address before it has to wait"
    )
    wrong_password_window_minutes: int


class AssistantSettings(BaseModel):
    mcp_url: str = Field(description="The MCP server's URL as AI assistants reach it")
    requests_per_minute: int = Field(
        description="Requests one token may make each minute, counted in each API worker"
    )


class SearchQuestionsLaw(BaseModel):
    law: str = Field(description="The law's slug")
    short_name: str = Field(description="What people call the law, in English")
    questions: int = Field(description="How many questions the law's file holds")
    current: int = Field(
        description=(
            "How many sit beside the words they were written for, and so are used. The rest "
            "wait to be written again for words that have changed"
        )
    )
    written_by: str = Field(description="The models that wrote them")
    checked_by: str = Field(description="The models that checked them")
    written_on: date


class SearchQuestionsSettings(BaseModel):
    on: bool = Field(
        description=(
            "Whether searches use the search questions, which only reorder the clauses a "
            "search found and are never returned. Changed with `dpolens search-questions on` "
            "or `off`, which the governance log records"
        )
    )
    laws: list[SearchQuestionsLaw]


class InstanceFacts(BaseModel):
    version: str
    id: str
    created_at: datetime = Field(description="When the instance was set up")


class InstanceSettings(BaseModel):
    questions_log: QuestionsLogSettings
    sign_in: SignInSettings
    assistants: AssistantSettings
    search_questions: SearchQuestionsSettings
    ai_provider: str | None = Field(
        description=(
            "The service an answer is written with. Null: none is used, search runs on "
            "this instance's own model, and nothing anybody asks is sent elsewhere"
        )
    )
    instance: InstanceFacts


@router.get("/settings", summary="How this instance is set up")
def read_settings(who: SettingsReader, settings: Configured, opened: Opened) -> InstanceSettings:
    assert who
    row = this_instance(opened)
    return InstanceSettings(
        questions_log=QuestionsLogSettings(
            retention_days=settings.query_log_retention_days,
            redacted=[name for name, _ in BUILT_IN],
            added_patterns=sorted(settings.redaction_patterns),
        ),
        sign_in=SignInSettings(
            idle_minutes=settings.session_idle_minutes,
            lifetime_hours=settings.session_lifetime_hours,
            wrong_passwords=SIGN_IN_FAILURES,
            wrong_password_window_minutes=SIGN_IN_WINDOW // 60,
        ),
        assistants=AssistantSettings(
            mcp_url=settings.public_mcp_url,
            requests_per_minute=settings.rate_limit_per_minute,
        ),
        search_questions=SearchQuestionsSettings(
            on=questions_on(opened),
            laws=[
                SearchQuestionsLaw(
                    law=file.pack,
                    short_name=file.short_name,
                    questions=file.questions,
                    current=file.current,
                    written_by=file.written_by,
                    checked_by=file.checked_by,
                    written_on=file.written_on,
                )
                for file in loaded_files(opened)
            ],
        ),
        ai_provider=None,
        instance=InstanceFacts(version=__version__, id=str(row.id), created_at=row.created_at),
    )
