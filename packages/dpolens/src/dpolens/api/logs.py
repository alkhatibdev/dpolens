"""The two logs, read: the questions people asked, and every change made to the instance.

The questions log follows the query log's promise. Someone with `queries.read_own`
sees their own questions; `queries.read_all` sees everybody's with names hidden;
`queries.read_identities` may ask for names, and every such look is written to the
governance log before a name leaves the instance. The governance log needs
`governance.read`, and is read with the names its ids stand for.
"""

from __future__ import annotations

import base64
import csv
import io
import json
import uuid
import zipfile
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from dpolens.api import problems
from dpolens.api.dependencies import Configured, Opened, actor_of, requires, requires_any
from dpolens.engine.auth import permissions as catalog
from dpolens.engine.auth.models import PersonalAccessToken, User
from dpolens.engine.auth.tokens import Authenticated
from dpolens.engine.logs import governance_view, reading
from dpolens.engine.logs.export import export_files
from dpolens.engine.logs.governance import verify
from dpolens.engine.session import session_from

router = APIRouter(prefix="/v1", tags=["logs"], responses=problems.responses(401, 403, 429))

QuestionReader = Annotated[
    Authenticated,
    Depends(requires_any(catalog.QUERIES_READ_ALL, catalog.QUERIES_READ_OWN)),
]
GovernanceReader = Annotated[Authenticated, Depends(requires(catalog.GOVERNANCE_READ))]

Surface = Literal["dashboard", "mcp", "api", "slack", "github_action"]
Status = Literal["ok", "no_match", "refused", "error"]
Operation = Literal["search", "get_clause", "get_subtree", "list_documents", "get_document", "ask"]
Kind = Literal["person", "service_account"]
UserStatus = Literal["active", "deactivated", "erased"]
Category = Literal[
    "sign_ins", "people", "roles", "tokens", "laws", "policies", "questions", "exports"
]

CATEGORIES: dict[str, tuple[str, ...]] = {
    "sign_ins": ("session.",),
    "people": ("user.",),
    "roles": ("role.",),
    "tokens": ("pat.",),
    "laws": ("laws.",),
    "policies": ("document.",),
    "questions": ("query_log.",),
    "exports": ("governance_log.",),
}


# The questions log -------------------------------------------------------------


class Step(BaseModel):
    label: str | None
    heading: str | None


class ClauseName(BaseModel):
    """A clause as a citation names it, in the language it was returned in."""

    key: str
    document_title: str
    document_slug: str
    pack_slug: str | None = Field(description="The law's pack, or null for a policy")
    version_label: str | None
    lang: str
    trail: list[Step] = Field(description="Label and heading, outermost first, down to it")

    @classmethod
    def of(cls, name: reading.ClauseName) -> ClauseName:
        return cls(
            key=name.key,
            document_title=name.document_title,
            document_slug=name.document_slug,
            pack_slug=name.pack_slug,
            version_label=name.version_label,
            lang=name.lang,
            trail=[Step(label=label, heading=heading) for label, heading in name.trail],
        )


class Returned(BaseModel):
    rank: int
    clause: ClauseName


class Asker(BaseModel):
    id: str
    display_name: str
    email: str
    kind: Kind


class Question(BaseModel):
    id: str
    created_at: datetime
    expires_at: datetime | None = Field(
        description=(
            "When the instance deletes it, the day it was asked plus the retention, or null "
            "when questions are kept"
        )
    )
    surface: Surface
    operation: Operation
    question: str = Field(description="As stored: personal data replaced by placeholders")
    target: str | None = Field(description="The key or slug read, for a read rather than a search")
    status: Status
    scope: Literal["selected", "other"] | None
    redaction_count: int
    redaction_types: list[str]
    results: list[Returned]
    asker: Asker | None = Field(description="Only when names were asked for, and allowed")

    @classmethod
    def of(cls, logged: reading.LoggedQuestion, *, retention_days: int | None) -> Question:
        asker = logged.asker
        return cls(
            id=str(logged.id),
            created_at=logged.created_at,
            expires_at=(
                logged.created_at + timedelta(days=retention_days) if retention_days else None
            ),
            surface=cast(Surface, logged.surface),
            operation=cast(Operation, logged.operation),
            question=logged.query,
            target=logged.target,
            status=cast(Status, logged.status),
            scope=cast(Literal["selected", "other"] | None, logged.scope),
            redaction_count=logged.redaction_count,
            redaction_types=list(logged.redaction_types),
            results=[
                Returned(rank=result.rank, clause=ClauseName.of(result.name))
                for result in logged.results
            ],
            asker=Asker(
                id=str(asker.id),
                display_name=asker.display_name,
                email=asker.email,
                kind=cast(Kind, asker.kind),
            )
            if asker
            else None,
        )


class Questions(BaseModel):
    questions: list[Question]
    total: int = Field(description="How many the filter selects in all")
    next: str | None = Field(description="Send as `before` for the next page")
    identities: bool = Field(description="Whether names are in this answer")


def _cursor(value: tuple[datetime, uuid.UUID] | None) -> str | None:
    if value is None:
        return None
    raw = json.dumps([value[0].isoformat(), str(value[1])]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _uncursor(value: str | None) -> tuple[datetime, uuid.UUID] | None:
    if not value:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        when, ident = json.loads(base64.urlsafe_b64decode(padded))
        return datetime.fromisoformat(str(when)), uuid.UUID(str(ident))
    except (ValueError, TypeError) as malformed:
        raise problems.invalid_request("`before` is not a cursor this log gave out") from malformed


def _filter(
    who: Authenticated,
    *,
    since: datetime | None,
    until: datetime | None,
    surface: list[Surface] | None,
    status: list[Status] | None,
    operation: list[Operation] | None,
    document: str | None,
    q: str | None,
    asked_by: str | None,
) -> reading.QuestionFilter:
    return reading.QuestionFilter(
        since=since,
        until=until,
        surfaces=tuple(surface or ()),
        statuses=tuple(status or ()),
        operations=tuple(operation or ("search",)),
        document=document,
        text=q.strip() if q and q.strip() else None,
        # Somebody who may read only their own questions gets only their own, whatever they ask.
        only_user=None if who.may(catalog.QUERIES_READ_ALL) else who.user.id,
        asked_by=asked_by.strip() if asked_by and asked_by.strip() else None,
    )


def _may_name(who: Authenticated, identities: bool) -> bool:
    if identities and not who.may(catalog.QUERIES_READ_IDENTITIES):
        raise problems.permission_required(catalog.QUERIES_READ_IDENTITIES)
    return identities


class QuestionParameters:
    """The filter both the page and the export take, declared once."""

    def __init__(
        self,
        since: Annotated[datetime | None, Query()] = None,
        until: Annotated[datetime | None, Query()] = None,
        surface: Annotated[list[Surface] | None, Query()] = None,
        status: Annotated[list[Status] | None, Query()] = None,
        operation: Annotated[
            list[Operation] | None, Query(description="Left out, searches only")
        ] = None,
        document: Annotated[str | None, Query(max_length=200)] = None,
        q: Annotated[str | None, Query(max_length=200, description="Words in the question")] = None,
        asked_by: Annotated[
            str | None,
            Query(max_length=200, description="Words in the asker's name or email address"),
        ] = None,
        identities: Annotated[
            bool,
            Query(description="Include who asked. Needs queries.read_identities, and is logged"),
        ] = False,
    ) -> None:
        self.since = since
        self.until = until
        self.surface = surface
        self.status = status
        self.operation = operation
        self.document = document
        self.q = q
        self.asked_by = asked_by
        self.identities = identities

    def filter(self, who: Authenticated) -> reading.QuestionFilter:
        return _filter(
            who,
            since=self.since,
            until=self.until,
            surface=self.surface,
            status=self.status,
            operation=self.operation,
            document=self.document,
            q=self.q,
            asked_by=self.asked_by if self.identities else None,
        )


Parameters = Annotated[QuestionParameters, Depends()]


@router.get("/queries", summary="Read the questions log", responses=problems.responses(400))
def list_questions(
    request: Request,
    who: QuestionReader,
    opened: Opened,
    settings: Configured,
    given: Parameters,
    before: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> Questions:
    identities = _may_name(who, given.identities)
    found = given.filter(who)
    page = reading.page_of_questions(
        opened, found, limit=limit, before=_uncursor(before), identities=identities
    )
    if identities and page.questions:
        # In a session of its own, committed before the names are handed over.
        with session_from(request.app.state.engine) as own:
            reading.record_identities_viewed(
                own,
                actor=actor_of(who),
                found=found,
                entry_ids=[question.id for question in page.questions],
            )
    return Questions(
        questions=[
            Question.of(question, retention_days=settings.query_log_retention_days)
            for question in page.questions
        ],
        total=page.total,
        next=_cursor(page.next_cursor),
        identities=identities,
    )


def _no_later_than(given: datetime | None, now: datetime) -> datetime:
    if given is None:
        return now
    return min(given if given.tzinfo else given.replace(tzinfo=UTC), now)


def _safe(value: str) -> str:
    """A cell a spreadsheet will show as text, never run as a formula."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


def _csv_rows(engine: Any, found: reading.QuestionFilter, identities: bool) -> Iterator[str]:
    header = [
        "time_utc",
        "surface",
        "operation",
        "question",
        "target",
        "status",
        "scope",
        "redactions",
        "first_result",
        "results",
    ]
    if identities:
        header += ["asker", "asker_email"]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    yield buffer.getvalue()
    with session_from(engine) as own:
        for question in reading.all_questions(own, found, identities=identities):
            buffer.seek(0)
            buffer.truncate()
            row = [
                question.created_at.astimezone(UTC).isoformat(),
                question.surface,
                question.operation,
                _safe(question.query),
                _safe(question.target or ""),
                question.status,
                question.scope or "",
                str(question.redaction_count),
                question.results[0].name.key if question.results else "",
                str(len(question.results)),
            ]
            if identities:
                row += [
                    _safe(question.asker.display_name) if question.asker else "",
                    _safe(question.asker.email) if question.asker else "",
                ]
            writer.writerow(row)
            yield buffer.getvalue()


@router.get(
    "/queries/export",
    summary="Download the questions the filter selects, as CSV",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/csv": {}}}, **problems.responses(400)},
)
def export_questions(
    request: Request, who: QuestionReader, opened: Opened, given: Parameters
) -> StreamingResponse:
    identities = _may_name(who, given.identities)
    found = given.filter(who)
    if identities:
        # The file ends where its record is written, so no question asked in between
        # leaves with a name the record does not count.
        found = replace(found, until=_no_later_than(found.until, datetime.now(UTC)))
        total = reading.page_of_questions(opened, found, limit=1).total
        if total:
            with session_from(request.app.state.engine) as own:
                reading.record_identities_viewed(
                    own, actor=actor_of(who), found=found, exported=total
                )
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    return StreamingResponse(
        _csv_rows(request.app.state.engine, found, identities),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="dpolens-questions-{stamp}.csv"'},
    )


# The governance log -------------------------------------------------------------


class PersonRef(BaseModel):
    id: str
    display_name: str
    email: str
    kind: Kind
    status: UserStatus

    @classmethod
    def of(cls, user: User) -> PersonRef:
        return cls(
            id=str(user.id),
            display_name=user.display_name,
            email=user.email,
            kind=cast(Kind, user.kind),
            status=cast(UserStatus, user.status),
        )


class TokenRef(BaseModel):
    id: str
    name: str
    prefix: str
    owner: str = Field(description="The owner's name")

    @classmethod
    def of(cls, token: PersonalAccessToken) -> TokenRef:
        return cls(
            id=str(token.id), name=token.name, prefix=token.prefix, owner=token.owner.display_name
        )


class Entry(BaseModel):
    seq: int
    occurred_at: datetime
    action: str
    target_type: str
    target_id: str
    details: dict[str, Any] = Field(description="As stored, the before and after of the change")
    entry_hash: str
    prev_hash: str
    actor: PersonRef | None = Field(
        description="Who acted. Null for the command line or the instance"
    )
    actor_token: TokenRef | None
    target_user: PersonRef | None
    target_token: TokenRef | None

    @classmethod
    def of(cls, view: governance_view.EntryView) -> Entry:
        return cls(
            seq=view.seq,
            occurred_at=view.occurred_at,
            action=view.action,
            target_type=view.target_type,
            target_id=view.target_id,
            details=view.details,
            entry_hash=view.entry_hash,
            prev_hash=view.prev_hash,
            actor=PersonRef.of(view.actor) if view.actor else None,
            actor_token=TokenRef.of(view.actor_token) if view.actor_token else None,
            target_user=PersonRef.of(view.target_user) if view.target_user else None,
            target_token=TokenRef.of(view.target_token) if view.target_token else None,
        )


class Entries(BaseModel):
    entries: list[Entry]
    total: int
    next: int | None = Field(description="Send as `before` for the next page")


class Actors(BaseModel):
    people: list[PersonRef]


class Verification(BaseModel):
    """The chain, recomputed now."""

    ok: bool
    entries: int
    first_broken_seq: int | None
    reason: str | None
    out_of_order: list[int]
    anchored_to_genesis: bool
    checked_at: datetime


@router.get("/governance/entries", summary="Read the governance log")
def list_entries(
    who: GovernanceReader,
    opened: Opened,
    actor: Annotated[uuid.UUID | None, Query()] = None,
    category: Annotated[list[Category] | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    before: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> Entries:
    assert who
    found = governance_view.EntryFilter(
        actor_id=actor,
        actions=tuple(prefix for name in category or () for prefix in CATEGORIES[name]),
        since=since,
        until=until,
        text=q.strip() if q and q.strip() else None,
    )
    page = governance_view.page_of_entries(opened, found, limit=limit, before=before)
    return Entries(
        entries=[Entry.of(view) for view in page.entries], total=page.total, next=page.next_before
    )


@router.get("/governance/actors", summary="Everyone who appears in the log as having acted")
def list_actors(who: GovernanceReader, opened: Opened) -> Actors:
    assert who
    return Actors(people=[PersonRef.of(user) for user in governance_view.actors(opened)])


@router.get("/governance/verification", summary="Recompute the chain and say whether it holds")
def check_chain(who: GovernanceReader, opened: Opened) -> Verification:
    assert who
    report = verify(opened)
    return Verification(
        ok=report.ok,
        entries=report.entries,
        first_broken_seq=report.first_broken_seq,
        reason=report.reason,
        out_of_order=list(report.out_of_order),
        anchored_to_genesis=report.anchored_to_genesis,
        checked_at=datetime.now(UTC),
    )


@router.post(
    "/governance/exports",
    summary="Export the log for an auditor, as a zip of three files",
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}}},
)
def export_log(
    request: Request,
    who: GovernanceReader,
    from_seq: Annotated[int | None, Query(ge=1)] = None,
    to_seq: Annotated[int | None, Query(ge=1)] = None,
) -> Response:
    """The files `dpolens governance export` writes. The export is recorded in the log,
    in a session of its own, so the record is kept before the file is handed over."""
    with session_from(request.app.state.engine) as own:
        files = export_files(own, actor=actor_of(who), from_seq=from_seq, to_seq=to_seq)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, content in files.items():
            bundle.writestr(name, content)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    return Response(
        content=archive.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="dpolens-governance-{stamp}.zip"'},
    )
