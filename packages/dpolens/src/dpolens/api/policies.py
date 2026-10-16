"""An organisation's own policies: uploaded as drafts, reviewed, published, archived.

An upload sends the file itself as the request body, with its name in `filename`, and is parsed
at once: an unreadable file is refused in the same response. A draft is never searched. Its
flags are what the parser could not settle; publishing waits until every one is accepted, makes
the version immutable, and queues the job that embeds it. Uploading, reviewing and discarding
take `documents.upload`; publishing and archiving take `documents.publish`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal, cast
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, Query, Response
from pydantic import BaseModel, Field

from dpolens.api import problems
from dpolens.api.dependencies import Configured, Opened, actor_of, requires
from dpolens.engine.auth import permissions as catalog
from dpolens.engine.auth.tokens import Authenticated
from dpolens.engine.originals import Directory, OriginalUnavailable
from dpolens.engine.policies import store
from dpolens.engine.policies.blocks import UnreadablePolicy

router = APIRouter(
    prefix="/v1/policies", tags=["policies"], responses=problems.responses(401, 403, 429)
)

Uploader = Annotated[Authenticated, Depends(requires(catalog.DOCUMENTS_UPLOAD))]
Publisher = Annotated[Authenticated, Depends(requires(catalog.DOCUMENTS_PUBLISH))]
Reader = Annotated[Authenticated, Depends(requires(catalog.DOCUMENTS_READ))]
Layer = Literal["native_structure", "typography", "numbering"]
Change = Literal["added", "modified", "moved", "unchanged"]
Status = Literal["draft", "published", "discarded"]
Indexing = Literal["todo", "doing", "succeeded", "failed"]
FlagKind = Literal["coverage_gap", "numbering_gap", "low_confidence_boundary", "unmatched_key"]

FileBody = Annotated[
    bytes,
    Body(
        media_type="application/octet-stream",
        description="The policy file itself: a Word (.docx) or Markdown (.md) file",
    ),
]
Filename = Annotated[
    str,
    Query(
        min_length=1,
        max_length=255,
        description="The file's name, whose extension says whether it is Word or Markdown",
    ),
]


class OriginalFile(BaseModel):
    name: str | None = Field(description="The uploaded file's name")
    format: str | None = Field(description="docx or markdown")
    size: int | None = Field(description="In bytes")


class PolicyVersion(BaseModel):
    slug: str
    title: str
    number: int = Field(description="The version's number among this policy's uploads")
    label: str | None = Field(description="The label citations show, set when it is published")
    status: Status
    effective_date: date = Field(description="The day it takes effect, once published")
    source: OriginalFile
    created_at: datetime
    created_by: str | None = Field(description="Who uploaded it; empty from the command line")
    published_at: datetime | None
    published_by: str | None
    indexing: Indexing | None = Field(
        description=(
            "Once published, whether its clauses are embedded yet, so that searching by "
            "meaning finds them. Searching by words finds them at once"
        )
    )


class DraftClause(BaseModel):
    key: str
    kind: str = Field(description="section, paragraph, list, table or row")
    label: str | None = Field(description="The number the document shows for it")
    heading: str | None
    text: str
    lang: str
    layer: Layer | None = Field(
        description=(
            "What decided where it begins and how deep it sits: the file's own structure, "
            "its typography, or a number written into its text"
        )
    )
    change: Change | None = Field(
        description="Against the version before: added, modified, moved or unchanged"
    )
    continues: str | None = Field(description="The key of the clause it continues")
    children: list[DraftClause]


class FlagOut(BaseModel):
    position: int = Field(description="Its place in the draft's list, which names it")
    kind: FlagKind
    key: str | None
    detail: str = Field(description="What to check, in a sentence")
    accepted_by: str | None
    accepted_at: datetime | None


class Removed(BaseModel):
    key: str
    heading: str | None
    text: str


class SetAside(BaseModel):
    reason: Literal["title", "front matter", "contents", "text box", "repeated table"]
    text: str


class Coverage(BaseModel):
    characters: int = Field(description="Every character of text in the file")
    in_clauses: int
    set_aside: int
    missed: int = Field(description="Characters the reader could not take, which is a flag")


class PolicyDraft(BaseModel):
    version: PolicyVersion
    clauses: list[DraftClause]
    flags: list[FlagOut]
    coverage: Coverage
    set_aside: list[SetAside] = Field(description="Text kept but in no clause, never searched")
    notices: list[str] = Field(description="What the file itself said, such as tracked changes")
    previous: str | None = Field(description="The label of the version it was matched to")
    removed: list[Removed] = Field(description="Clauses of that version nothing continues")
    changes: dict[str, int] = Field(
        description="How many clauses were added, modified, moved, unchanged and removed"
    )


class PolicySummary(BaseModel):
    slug: str
    title: str
    status: Literal["active", "archived"]
    in_force: str | None = Field(description="The label of the version in force today")
    in_force_since: date | None
    published: int = Field(description="How many versions have been published")
    draft: int | None = Field(description="The open draft's number, if there is one")
    indexing: Indexing | None = Field(
        description=(
            "Whether the latest published version's clauses are embedded yet, so that searching "
            "by meaning finds them"
        )
    )


class DraftDetails(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    effective_date: date | None = None
    version_label: str | None = Field(default=None, max_length=100)


class FlagsToAccept(BaseModel):
    positions: list[int] = Field(min_length=1, max_length=1000)


def originals_of(settings: Configured) -> Directory:
    return Directory(settings.originals_dir)


Originals = Annotated[Directory, Depends(originals_of)]


def _version(view: store.VersionView) -> PolicyVersion:
    return PolicyVersion(
        slug=view.slug,
        title=view.title,
        number=view.number,
        label=view.label,
        status=cast(Status, view.status),
        effective_date=view.effective_date,
        source=OriginalFile(
            name=view.source_name, format=view.source_format, size=view.source_size
        ),
        created_at=view.created_at,
        created_by=view.created_by,
        published_at=view.published_at,
        published_by=view.published_by,
        indexing=cast(Indexing | None, view.indexing),
    )


def _clause(clause: store.DraftClause) -> DraftClause:
    return DraftClause(
        key=clause.key,
        kind=clause.kind,
        label=clause.label,
        heading=clause.heading,
        text=clause.text,
        lang=clause.lang,
        layer=cast(Layer | None, clause.layer),
        change=cast(Change | None, clause.change),
        continues=clause.continues,
        children=[_clause(child) for child in clause.children],
    )


def _draft(view: store.DraftView) -> PolicyDraft:
    checks: dict[str, Any] = view.checks
    return PolicyDraft(
        version=_version(view.version),
        clauses=[_clause(clause) for clause in view.clauses],
        flags=[
            FlagOut(
                position=flag.position,
                kind=cast(FlagKind, flag.kind),
                key=flag.key,
                detail=flag.detail,
                accepted_by=flag.accepted_by,
                accepted_at=flag.accepted_at,
            )
            for flag in view.flags
        ],
        coverage=Coverage(**checks.get("coverage", {})),
        set_aside=[
            SetAside(reason=block["reason"], text=block["text"])
            for block in checks.get("set_aside", [])
        ],
        notices=list(checks.get("notices", [])),
        previous=view.previous,
        removed=[
            Removed(key=gone["key"] or "", heading=gone["heading"], text=gone["text"] or "")
            for gone in view.removed
        ],
        changes=view.changes,
    )


def attachment(name: str, fallback: str) -> str:
    """A download's file name. A name in plain ASCII goes as it is. Any other, such as one in
    Arabic, goes in RFC 6266's `filename*`, with `fallback` for a client that cannot read it."""
    plain = name.isascii() and name.isprintable() and not any(c in name for c in '"\\')
    if plain:
        return f'attachment; filename="{name}"'
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(name, safe='')}"


def _refused(failure: Exception) -> problems.Problem:
    """The engine's refusals, each as the problem a client branches on."""
    detail = str(failure)
    match failure:
        case store.PolicyNotFound():
            return problems.policy_not_found(detail)
        case store.PolicyExists():
            return problems.policy_exists(detail)
        case store.DraftExists():
            return problems.draft_exists(detail, failure.version)
        case store.NoDraft():
            return problems.no_draft(detail)
        case store.FlagsOpen():
            return problems.flags_open(detail, failure.positions)
        case store.FlagNotFound():
            return problems.flag_not_found(detail)
        case store.EffectiveDateTooEarly():
            return problems.effective_date_too_early(detail)
        case store.LabelTaken():
            return problems.version_label_taken(detail)
        case store.BadSlug():
            return problems.bad_slug(detail)
        case UnreadablePolicy():
            return problems.unreadable_policy(detail)
        case OriginalUnavailable():
            return problems.original_unavailable(detail)
    raise failure


REFUSALS = (
    store.PolicyNotFound,
    store.PolicyExists,
    store.DraftExists,
    store.NoDraft,
    store.FlagsOpen,
    store.FlagNotFound,
    store.EffectiveDateTooEarly,
    store.LabelTaken,
    store.BadSlug,
    UnreadablePolicy,
    OriginalUnavailable,
)


@router.get("", summary="Every organisation policy, with its version in force and any draft")
def list_all(who: Uploader, opened: Opened) -> list[PolicySummary]:
    return [
        PolicySummary(
            slug=found.slug,
            title=found.title,
            status=cast(Literal["active", "archived"], found.status),
            in_force=found.in_force,
            in_force_since=found.in_force_since,
            published=found.published,
            draft=found.draft,
            indexing=cast(Indexing | None, found.indexing),
        )
        for found in store.list_policies(opened)
    ]


@router.post(
    "",
    status_code=201,
    summary="Upload a new policy, which becomes its first draft",
    responses=problems.responses(409, 422),
)
def upload_new(
    content: FileBody,
    filename: Filename,
    who: Uploader,
    opened: Opened,
    originals: Originals,
    slug: Annotated[
        str | None,
        Query(description="The slug every key starts with; from the file name if left out"),
    ] = None,
    title: Annotated[str | None, Query(max_length=300)] = None,
    effective_date: Annotated[
        date | None, Query(description="When it takes effect; today if left out")
    ] = None,
    version_label: Annotated[str | None, Query(max_length=100)] = None,
) -> PolicyDraft:
    try:
        view = store.upload_policy(
            opened,
            originals,
            content,
            filename,
            actor=actor_of(who),
            slug=slug,
            title=title,
            effective_date=effective_date,
            version_label=version_label,
        )
    except REFUSALS as failure:
        raise _refused(failure) from failure
    return _draft(view)


@router.post(
    "/{slug}/versions",
    status_code=201,
    summary="Upload a new version of a policy, matched to the version before it",
    responses=problems.responses(404, 409, 422),
)
def upload_new_version(
    slug: str,
    content: FileBody,
    filename: Filename,
    who: Uploader,
    opened: Opened,
    originals: Originals,
    effective_date: Annotated[date | None, Query()] = None,
    version_label: Annotated[str | None, Query(max_length=100)] = None,
    replace: Annotated[
        bool, Query(description="Discard the policy's open draft and use this upload instead")
    ] = False,
) -> PolicyDraft:
    try:
        view = store.upload_version(
            opened,
            originals,
            slug,
            content,
            filename,
            actor=actor_of(who),
            effective_date=effective_date,
            version_label=version_label,
            replace=replace,
        )
    except REFUSALS as failure:
        raise _refused(failure) from failure
    return _draft(view)


@router.get(
    "/{slug}/draft",
    summary="A policy's draft: its clauses, its flags, and what changed",
    responses=problems.responses(404),
)
def read_draft(slug: str, who: Uploader, opened: Opened) -> PolicyDraft:
    try:
        return _draft(store.read_draft(opened, slug))
    except REFUSALS as failure:
        raise _refused(failure) from failure


@router.patch(
    "/{slug}/draft",
    summary="Change a draft's title, effective date or version label",
    responses=problems.responses(404),
)
def edit_draft(slug: str, body: DraftDetails, who: Uploader, opened: Opened) -> PolicyDraft:
    try:
        view = store.edit_draft(
            opened,
            slug,
            actor=actor_of(who),
            title=body.title,
            effective_date=body.effective_date,
            version_label=body.version_label,
        )
    except REFUSALS as failure:
        raise _refused(failure) from failure
    return _draft(view)


@router.post(
    "/{slug}/draft/flags/accept",
    summary="Accept flags, by their place in the draft's list",
    responses=problems.responses(404),
)
def accept(slug: str, body: FlagsToAccept, who: Uploader, opened: Opened) -> PolicyDraft:
    try:
        return _draft(store.accept_flags(opened, slug, body.positions, actor=actor_of(who)))
    except REFUSALS as failure:
        raise _refused(failure) from failure


@router.post(
    "/{slug}/draft/publish",
    summary="Publish the draft once every flag is accepted",
    responses=problems.responses(404, 409),
)
def publish(slug: str, who: Publisher, opened: Opened) -> PolicyVersion:
    try:
        return _version(store.publish(opened, slug, actor=actor_of(who)))
    except REFUSALS as failure:
        raise _refused(failure) from failure


@router.delete(
    "/{slug}/draft",
    status_code=204,
    summary="Discard the draft",
    responses=problems.responses(404),
)
def discard(slug: str, who: Uploader, opened: Opened) -> Response:
    try:
        store.discard(opened, slug, actor=actor_of(who))
    except REFUSALS as failure:
        raise _refused(failure) from failure
    return Response(status_code=204)


@router.post(
    "/{slug}/archive",
    status_code=204,
    summary="Archive a policy: nothing searches it, and its clauses still read by key",
    responses=problems.responses(404),
)
def archive(slug: str, who: Publisher, opened: Opened) -> Response:
    try:
        store.archive(opened, slug, actor=actor_of(who))
    except REFUSALS as failure:
        raise _refused(failure) from failure
    return Response(status_code=204)


@router.get(
    "/{slug}/versions/{number}/original",
    summary="A version's original file, checked against the hash it was stored with",
    response_class=Response,
    responses={
        200: {"content": {"application/octet-stream": {}}, "description": "The file"},
        **problems.responses(404, 500),
    },
)
def download(slug: str, number: int, who: Reader, opened: Opened, originals: Originals) -> Response:
    try:
        data, name, form = store.original(opened, originals, slug, number)
    except REFUSALS as failure:
        raise _refused(failure) from failure
    media = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if form == "docx"
        else "text/markdown; charset=utf-8"
    )
    fallback = f"{slug}-{number}.{'docx' if form == 'docx' else 'md'}"
    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": attachment(name, fallback)},
    )
