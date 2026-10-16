"""An organisation's own policies: uploaded as drafts, reviewed, published, archived.

An upload sends the file itself as the request body, with its name in `filename`, and is parsed
at once: an unreadable file is refused in the same response. A draft is never searched. Its
flags are what the parser could not settle; publishing waits until every one is settled, makes
the version immutable, and queues the job that embeds it. Uploading, reviewing and discarding
take `documents.upload`; publishing and archiving take `documents.publish`, and either opens the
list of policies and their drafts.

A draft is read with its revision as an `ETag`, and every change may send it back in `If-Match`.
A change made against an older revision is refused with `412`, naming who changed the draft and
when, so two people reviewing one draft never undo each other. A change without it is made.

How a clause was read can be fixed without changing a word: split where a second rule begins,
merged with the clause before it, made text or a heading, moved under the clause before it or out
a level. Keys follow from where each clause ends up, by the rules a parse uses.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal, cast
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, Header, Query, Response
from pydantic import BaseModel, Field

from dpolens.api import problems
from dpolens.api.dependencies import (
    Caller,
    Configured,
    Opened,
    actor_of,
    expected_revision,
    requires,
    requires_any,
)
from dpolens.engine.auth import permissions as catalog
from dpolens.engine.auth.tokens import Authenticated
from dpolens.engine.originals import Directory, OriginalUnavailable
from dpolens.engine.policies import store
from dpolens.engine.policies.blocks import UnreadablePolicy
from dpolens.engine.policies.fixing import CannotFix

router = APIRouter(
    prefix="/v1/policies", tags=["policies"], responses=problems.responses(401, 403, 429)
)

Uploader = Annotated[Authenticated, Depends(requires(catalog.DOCUMENTS_UPLOAD))]
Publisher = Annotated[Authenticated, Depends(requires(catalog.DOCUMENTS_PUBLISH))]
Reviewer = Annotated[
    Authenticated,
    Depends(requires_any(catalog.DOCUMENTS_UPLOAD, catalog.DOCUMENTS_PUBLISH)),
]
IfMatch = Annotated[
    str | None,
    Header(description="The draft's revision, as its ETag gave it. A change made since is refused"),
]
Layer = Literal["native_structure", "typography", "numbering", "reviewer"]
Edit = Literal["split", "merge", "make-text", "make-heading", "move-under", "move-out"]
Fixed = Literal["split", "merged", "made-text", "made-heading", "moved-under", "moved-out"]
Resolution = Literal[
    "match-rejected", "split", "merged", "made-text", "made-heading", "moved-under", "moved-out"
]
Change = Literal["added", "modified", "moved", "unchanged"]
Status = Literal["draft", "published", "discarded"]
Indexing = Literal["todo", "doing", "succeeded", "failed"]
FlagKind = Literal["coverage_gap", "numbering_gap", "low_confidence_boundary", "unmatched_key"]
Place = Literal["body", "cell", "text box", "contents", "front matter"]
Reason = Literal["title", "front matter", "contents", "text box", "repeated table"]

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


class EarlierClause(BaseModel):
    key: str
    label: str | None
    heading: str | None
    text: str


class SplitPlace(BaseModel):
    at: int = Field(description="Where the second part begins, as a split's `at` names it")
    label: str | None = Field(description="The number the second part starts with, its label")


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
            "its typography, a number written into its text, or a reviewer who fixed it"
        )
    )
    change: Change | None = Field(
        description="Against the version before: added, modified, moved or unchanged"
    )
    continues: str | None = Field(description="The key of the clause it continues")
    earlier: EarlierClause | None = Field(
        description="That clause as the version before has it, when this one is renumbered or "
        "reworded"
    )
    fixed: Fixed | None = Field(
        default=None,
        description="What a reviewer last did to where it begins or how deep it sits",
    )
    fixes: list[Edit] = Field(
        default_factory=list, description="The fixes that can be made to it where it sits"
    )
    splits: list[SplitPlace] = Field(
        default_factory=list, description="Where in its text it can be split"
    )
    children: list[DraftClause]


class FlagSuggestion(BaseModel):
    """The fix the parser would make, which `POST /draft/edits` makes when sent back."""

    edit: Edit
    key: str = Field(description="The clause it applies to, which may not be the flag's own")
    at: int | None = Field(
        description="For a split, where in that clause's text the second part begins"
    )


class FlagOut(BaseModel):
    position: int = Field(description="Its place in the draft's list, which names it")
    kind: FlagKind
    key: str | None
    detail: str = Field(description="What to check, in a sentence")
    accepted_by: str | None = Field(description="Who accepted it as read")
    accepted_at: datetime | None
    resolved_by: str | None = Field(description="Who made the change that settled it")
    resolved_at: datetime | None
    resolution: Resolution | None = Field(
        description="The change that settled it: match-rejected, when the clause was said to be "
        "a different rule from the one it was matched to, or the fix a reviewer made to it"
    )
    resolution_key: str | None = Field(
        default=None,
        description="The clause the fix named: what it went under or into, or a split's second "
        "part",
    )
    paragraph: int | None = Field(
        description="The paragraph of the file it is about, as the file view numbers them"
    )
    suggestion: FlagSuggestion | None = Field(
        default=None,
        description="The fix the parser would make, while the flag is open and it can be made",
    )


class Removed(BaseModel):
    key: str
    heading: str | None
    text: str


class SetAside(BaseModel):
    reason: Reason
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
    revision: int = Field(description="Goes up with every change. Send it back in `If-Match`")
    updated_at: datetime | None
    updated_by: str | None = Field(
        description="Who changed it last, or null for a change made on the command line"
    )
    next_label: str = Field(
        description="The label it is published with: the one given, or the next number free"
    )


class DraftFixed(PolicyDraft):
    clause: str = Field(
        description="The key the clause has now: its own, or for a merge the clause it went into"
    )


class ScheduledVersion(BaseModel):
    label: str
    effective_date: date


class DraftReview(BaseModel):
    flags: int = Field(description="Every flag the draft has")
    open: int = Field(description="The flags still to settle before it can be published")
    uploaded_by: str | None
    uploaded_at: datetime
    next_label: str = Field(description="The label it is published with")


class LastChange(BaseModel):
    by: str | None = Field(description="A person's name, or null on the command line")
    at: datetime


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
    in_force_number: int | None = Field(
        description="The number of the version in force, which names its original file"
    )
    next_label: str = Field(
        description="The label a new version is published with, unless it is given one"
    )
    sample: bool = Field(description="The made-up policy a new instance starts with")
    scheduled: ScheduledVersion | None = Field(
        description="The next published version, when it takes effect later"
    )
    review: DraftReview | None = Field(description="The open draft's review, if there is one")
    last_change: LastChange | None = Field(
        description="Who last uploaded, reviewed, published or archived it, and when"
    )


class FileParagraph(BaseModel):
    position: int = Field(description="Its place among the file's paragraphs")
    text: str
    place: Place
    heading: int | None = Field(description="Its level, 1 the highest, when it is a heading")
    title: bool = Field(description="The file marks it as the document's title")
    label: str | None = Field(description="The number the file's own list puts before it")
    bold: bool
    table: int | None = Field(description="Which table it is in, from 0, with its row and cell")
    row: int | None
    cell: int | None
    header: bool = Field(description="Its row is the table's header")
    clause: str | None = Field(description="The key of the clause it went to")
    clauses: list[str] = Field(
        default_factory=list,
        description="Every clause that holds part of it: two once a clause is split inside it",
    )
    set_aside: Reason | None = Field(description="Why it is in no clause, when it is in none")


class PolicyFile(BaseModel):
    """A version's file as it was read, beside which its clauses are reviewed."""

    slug: str
    number: int
    status: Status
    source: OriginalFile
    paragraphs: list[FileParagraph] = Field(
        description="Every paragraph with text, in the file's order"
    )


class DraftDetails(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    effective_date: date | None = None
    version_label: str | None = Field(default=None, max_length=100)


class FlagsToAccept(BaseModel):
    positions: list[int] = Field(min_length=1, max_length=1000)


class Fix(BaseModel):
    edit: Edit = Field(
        description=(
            "split it where a second rule begins, merge it with the clause before it, make a "
            "heading text or text a heading, or move it under the clause before it or out a level"
        )
    )
    key: str = Field(min_length=1, max_length=200, description="The clause to fix")
    at: int | None = Field(
        default=None,
        ge=0,
        description=(
            "For a split, where in the clause's text the second part begins: where a sentence "
            "or a paragraph does, or a number after a semicolon or a colon"
        ),
    )


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
        fixed=cast(Fixed | None, clause.fixed),
        fixes=list(clause.fixes),
        splits=[SplitPlace(at=at, label=label) for at, label in clause.splits],
        earlier=(
            EarlierClause(
                key=clause.earlier.key,
                label=clause.earlier.label,
                heading=clause.earlier.heading,
                text=clause.earlier.text,
            )
            if clause.earlier
            else None
        ),
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
                resolved_by=flag.resolved_by,
                resolved_at=flag.resolved_at,
                resolution=cast(Resolution | None, flag.resolution),
                resolution_key=flag.resolution_key,
                paragraph=flag.paragraph,
                suggestion=(
                    FlagSuggestion(
                        edit=flag.suggestion.edit, key=flag.suggestion.key, at=flag.suggestion.at
                    )
                    if flag.suggestion
                    else None
                ),
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
        revision=view.revision,
        updated_at=view.updated_at,
        updated_by=view.updated_by,
        next_label=view.next_label,
    )


def _reviewed(view: store.DraftView, response: Response) -> PolicyDraft:
    """A draft, with its revision as the ETag a change sends back."""
    response.headers["ETag"] = f'"{view.revision}"'
    return _draft(view)


def _summary(found: store.PolicySummary) -> PolicySummary:
    review = found.review
    return PolicySummary(
        slug=found.slug,
        title=found.title,
        status=cast(Literal["active", "archived"], found.status),
        in_force=found.in_force,
        in_force_since=found.in_force_since,
        published=found.published,
        draft=found.draft,
        indexing=cast(Indexing | None, found.indexing),
        in_force_number=found.in_force_number,
        next_label=found.next_label,
        sample=found.sample,
        scheduled=(
            ScheduledVersion(
                label=found.scheduled.label, effective_date=found.scheduled.effective_date
            )
            if found.scheduled
            else None
        ),
        review=(
            DraftReview(
                flags=review.flags,
                open=review.open,
                uploaded_by=review.uploaded_by,
                uploaded_at=review.uploaded_at,
                next_label=review.next_label,
            )
            if review
            else None
        ),
        last_change=(
            LastChange(by=found.last_change.by, at=found.last_change.at)
            if found.last_change
            else None
        ),
    )


def _may_see(who: Authenticated, status: str) -> None:
    """A published version is anyone's who may read the library. A draft, or one thrown away,
    is only for those who review and publish policies."""
    if status == "published":
        if not who.may(catalog.DOCUMENTS_READ):
            raise problems.permission_required(catalog.DOCUMENTS_READ)
    elif not (who.may(catalog.DOCUMENTS_UPLOAD) or who.may(catalog.DOCUMENTS_PUBLISH)):
        raise problems.permission_required_any(
            (catalog.DOCUMENTS_UPLOAD, catalog.DOCUMENTS_PUBLISH)
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
        case store.NoMatch():
            return problems.no_match(detail)
        case store.NoClause():
            return problems.no_clause(detail)
        case CannotFix():
            return problems.fix_refused(detail)
        case store.StaleDraft():
            return problems.edit_conflict(
                revision=failure.revision,
                updated_at=failure.updated_at.isoformat() if failure.updated_at else "",
                updated_by=failure.updated_by,
            )
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
    store.NoMatch,
    store.NoClause,
    CannotFix,
    store.StaleDraft,
    store.EffectiveDateTooEarly,
    store.LabelTaken,
    store.BadSlug,
    UnreadablePolicy,
    OriginalUnavailable,
)


@router.get("", summary="Every organisation policy, with its version in force and any draft")
def list_all(who: Reviewer, opened: Opened) -> list[PolicySummary]:
    return [_summary(found) for found in store.list_policies(opened)]


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
    response: Response,
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
    return _reviewed(view, response)


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
    response: Response,
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
    return _reviewed(view, response)


@router.get(
    "/{slug}/draft",
    summary="A policy's draft: its clauses, its flags, and what changed",
    responses=problems.responses(404),
)
def read_draft(slug: str, who: Reviewer, opened: Opened, response: Response) -> PolicyDraft:
    try:
        return _reviewed(store.read_draft(opened, slug), response)
    except REFUSALS as failure:
        raise _refused(failure) from failure


@router.patch(
    "/{slug}/draft",
    summary="Change a draft's title, effective date or version label",
    responses=problems.responses(400, 404, 412),
)
def edit_draft(
    slug: str,
    body: DraftDetails,
    who: Uploader,
    opened: Opened,
    response: Response,
    if_match: IfMatch = None,
) -> PolicyDraft:
    try:
        view = store.edit_draft(
            opened,
            slug,
            actor=actor_of(who),
            title=body.title,
            effective_date=body.effective_date,
            version_label=body.version_label,
            expected_revision=expected_revision(if_match, "draft"),
        )
    except REFUSALS as failure:
        raise _refused(failure) from failure
    return _reviewed(view, response)


@router.post(
    "/{slug}/draft/flags/accept",
    summary="Accept flags as read, by their place in the draft's list",
    responses=problems.responses(400, 404, 412),
)
def accept(
    slug: str,
    body: FlagsToAccept,
    who: Uploader,
    opened: Opened,
    response: Response,
    if_match: IfMatch = None,
) -> PolicyDraft:
    try:
        view = store.accept_flags(
            opened,
            slug,
            body.positions,
            actor=actor_of(who),
            expected_revision=expected_revision(if_match, "draft"),
        )
    except REFUSALS as failure:
        raise _refused(failure) from failure
    return _reviewed(view, response)


@router.post(
    "/{slug}/draft/matches/{key}/reject",
    summary="Say a clause is a different rule from the one it was matched to",
    description=(
        "The clause becomes new, and the clause of the version before that it was matched to "
        "becomes removed, so that a citation of that clause says its rule was removed. The flag "
        "that asked about the match is resolved by the change."
    ),
    responses=problems.responses(400, 404, 412),
)
def reject_match(
    slug: str,
    key: str,
    who: Uploader,
    opened: Opened,
    response: Response,
    if_match: IfMatch = None,
) -> PolicyDraft:
    try:
        view = store.reject_match(
            opened,
            slug,
            key,
            actor=actor_of(who),
            expected_revision=expected_revision(if_match, "draft"),
        )
    except REFUSALS as failure:
        raise _refused(failure) from failure
    return _reviewed(view, response)


@router.post(
    "/{slug}/draft/edits",
    summary="Fix how a clause was read, without changing a word",
    description=(
        "Split a clause where a second rule begins, merge it with the clause before it, make a "
        "heading text or text a heading, or move it under the clause before it or out a level. "
        "Keys follow from where each clause ends up, by the rules a parse uses, and each clause "
        "the fix moved or reshaped takes the layer `reviewer`. An open flag on the clause is "
        "resolved by the fix. The numbering checks run again, so a numbering flag the fix makes "
        "untrue is resolved and a new finding is a new flag; for a new version, the clauses the "
        "fix rewords are matched again."
    ),
    responses=problems.responses(400, 404, 409, 412),
)
def fix(
    slug: str,
    body: Fix,
    who: Uploader,
    opened: Opened,
    response: Response,
    if_match: IfMatch = None,
) -> DraftFixed:
    try:
        fixed = store.fix_clause(
            opened,
            slug,
            body.edit,
            body.key,
            actor=actor_of(who),
            at=body.at,
            expected_revision=expected_revision(if_match, "draft"),
        )
    except REFUSALS as failure:
        raise _refused(failure) from failure
    return DraftFixed(**_reviewed(fixed.draft, response).model_dump(), clause=fixed.clause)


@router.post(
    "/{slug}/draft/publish",
    summary="Publish the draft once every flag is settled",
    responses=problems.responses(400, 404, 409, 412),
)
def publish(slug: str, who: Publisher, opened: Opened, if_match: IfMatch = None) -> PolicyVersion:
    try:
        return _version(
            store.publish(
                opened,
                slug,
                actor=actor_of(who),
                expected_revision=expected_revision(if_match, "draft"),
            )
        )
    except REFUSALS as failure:
        raise _refused(failure) from failure


@router.delete(
    "/{slug}/draft",
    status_code=204,
    summary="Discard the draft",
    responses=problems.responses(400, 404, 412),
)
def discard(slug: str, who: Uploader, opened: Opened, if_match: IfMatch = None) -> Response:
    try:
        store.discard(
            opened,
            slug,
            actor=actor_of(who),
            expected_revision=expected_revision(if_match, "draft"),
        )
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
    "/{slug}/versions/{number}/file",
    summary="A version's file as it was read, paragraph by paragraph, beside its clauses",
    description=(
        "Every paragraph with text, in the file's order, with what it looked like, the clause "
        "it went to, or why it was set aside. A published version's takes `documents.read`; a "
        "draft's, or a discarded one's, takes `documents.upload` or `documents.publish`."
    ),
    responses=problems.responses(404, 500),
)
def read_as_read(
    slug: str, number: int, who: Caller, opened: Opened, originals: Originals
) -> PolicyFile:
    try:
        _may_see(who, store.version_status(opened, slug, number))
        view = store.file_as_read(opened, originals, slug, number)
    except REFUSALS as failure:
        raise _refused(failure) from failure
    return PolicyFile(
        slug=view.slug,
        number=view.number,
        status=cast(Status, view.status),
        source=OriginalFile(name=view.name, format=view.format, size=view.size),
        paragraphs=[
            FileParagraph(
                position=found.line.position,
                text=found.line.text,
                place=found.line.place,
                heading=found.line.heading,
                title=found.line.title,
                label=found.line.label,
                bold=found.line.bold,
                table=found.line.table,
                row=found.line.row,
                cell=found.line.cell,
                header=found.line.header,
                clause=found.clause,
                clauses=list(found.clauses),
                set_aside=cast(Reason | None, found.set_aside),
            )
            for found in view.lines
        ],
    )


@router.get(
    "/{slug}/versions/{number}/original",
    summary="A version's original file, checked against the hash it was stored with",
    description=(
        "A published version's takes `documents.read`; a draft's, or a discarded one's, takes "
        "`documents.upload` or `documents.publish`."
    ),
    response_class=Response,
    responses={
        200: {"content": {"application/octet-stream": {}}, "description": "The file"},
        **problems.responses(404, 500),
    },
)
def download(slug: str, number: int, who: Caller, opened: Opened, originals: Originals) -> Response:
    try:
        _may_see(who, store.version_status(opened, slug, number))
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
