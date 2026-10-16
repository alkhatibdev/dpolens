"""Every failure the API reports, in one shape.

RFC 9457 problem details: `type` is the stable identifier a client branches on,
`title` and `status` describe the class of failure, and `detail` is aimed at the
person who has to fix it. There is no separate code field, because `type` is
already that field and two of them would invite clients to match on the wrong
one.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

MEDIA_TYPE = "application/problem+json"
BASE = "/problems/"


class Problem(Exception):
    """A failure with a stable identifier, raised anywhere and rendered once."""

    def __init__(
        self,
        *,
        kind: str,
        title: str,
        status: int,
        detail: str,
        headers: dict[str, str] | None = None,
        **extra: Any,
    ) -> None:
        super().__init__(detail)
        self.kind = kind
        self.title = title
        self.status = status
        self.detail = detail
        self.headers = headers or {}
        self.extra = extra

    def body(self, instance: str) -> dict[str, Any]:
        return {
            "type": BASE + self.kind,
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
            "instance": instance,
            **self.extra,
        }


def render(request: Request, problem: Problem) -> JSONResponse:
    return JSONResponse(
        status_code=problem.status,
        content=problem.body(request.url.path),
        media_type=MEDIA_TYPE,
        headers=problem.headers,
    )


def unauthenticated(detail: str) -> Problem:
    """No usable credential. The header is what a bearer scheme owes a client."""
    return Problem(
        kind="unauthenticated",
        title="Authentication required",
        status=401,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def token_refused(reason: str) -> Problem:
    """A token that exists and may not be used, which is worth naming precisely."""
    return Problem(
        kind="token-refused",
        title="Token refused",
        status=401,
        detail=f"this token was refused because it is {reason.replace('_', ' ')}",
        headers={"WWW-Authenticate": "Bearer"},
        reason=reason,
    )


def permission_required(permission: str) -> Problem:
    return Problem(
        kind="permission-required",
        title="Permission required",
        status=403,
        detail=f"this token does not carry {permission}",
        permission=permission,
    )


def permission_required_any(permissions: Sequence[str]) -> Problem:
    """For a route more than one permission opens. `permission` is the first, so a
    client that reads only that field still gets a key it knows."""
    return Problem(
        kind="permission-required",
        title="Permission required",
        status=403,
        detail=f"this needs one of {', '.join(permissions)}",
        permission=permissions[0],
        permissions=list(permissions),
    )


def delegation_not_permitted() -> Problem:
    return Problem(
        kind="delegation-not-permitted",
        title="Delegation not permitted",
        status=403,
        detail=(
            "this token may not say which user it is acting for. A surface that acts for "
            "other people needs a token created with --trusted-surface"
        ),
    )


def not_found(detail: str) -> Problem:
    return Problem(kind="not-found", title="Not found", status=404, detail=detail)


def invalid_request(detail: str) -> Problem:
    return Problem(kind="invalid-request", title="Invalid request", status=400, detail=detail)


def unsupported_language(lang: str, languages: Sequence[str]) -> Problem:
    """A language with no index here, refused with the ones that have one, so the
    caller can ask again in one of them."""
    return Problem(
        kind="unsupported-language",
        title="Unsupported language",
        status=422,
        detail=f"this instance cannot search in {lang!r}. It searches in: {', '.join(languages)}",
        languages=list(languages),
    )


def unknown_law(unknown: Sequence[str], laws: Sequence[str]) -> Problem:
    """A law that is not loaded, refused with the ones that are, so the caller can
    ask again with one of them."""
    return Problem(
        kind="unknown-law",
        title="Unknown law",
        status=422,
        detail=(
            f"no law loaded here is called {', '.join(unknown)}. "
            f"The loaded laws are: {', '.join(laws) or 'none'}"
        ),
        laws=list(laws),
    )


def too_many_requests(retry_after: int) -> Problem:
    """`Retry-After` is the standard field, and the only one a client should learn.

    The IETF RateLimit fields are still a draft whose syntax can change, so
    nothing here emits them yet.
    """
    return Problem(
        kind="too-many-requests",
        title="Too many requests",
        status=429,
        detail=f"this credential has spent its quota for the minute. Try again in {retry_after}s",
        headers={"Retry-After": str(retry_after)},
    )


def sign_in_refused() -> Problem:
    """One answer for a wrong password and an unknown address, so it names neither."""
    return Problem(
        kind="sign-in-refused",
        title="Sign-in refused",
        status=401,
        detail="that email and password do not match an account",
        headers={"WWW-Authenticate": "Bearer"},
    )


def too_many_attempts(retry_after: int) -> Problem:
    return Problem(
        kind="too-many-attempts",
        title="Too many attempts",
        status=429,
        detail=f"too many failed sign-ins for that address. Try again in {retry_after}s",
        headers={"Retry-After": str(retry_after)},
    )


def session_ended(reason: str) -> Problem:
    """A dashboard session that no longer works. `reason` lets the page say why:
    `expired`, `idle`, `owner_inactive` or `unknown`."""
    return Problem(
        kind="session-ended",
        title="Signed out",
        status=401,
        detail="the session has ended, so sign in again",
        headers={"WWW-Authenticate": "Bearer"},
        reason=reason,
    )


def cross_site_request() -> Problem:
    return Problem(
        kind="cross-site-request",
        title="Not from the dashboard",
        status=403,
        detail="a request carrying the session cookie has to come from the dashboard's own pages",
    )


def not_ready(detail: str) -> Problem:
    return Problem(kind="not-ready", title="Not ready", status=503, detail=detail)


def session_required() -> Problem:
    """For what only a person at the dashboard may do, such as making a token."""
    return Problem(
        kind="session-required",
        title="Dashboard only",
        status=403,
        detail="this is done from a dashboard session, not with a token",
    )


def already_exists(detail: str) -> Problem:
    return Problem(kind="already-exists", title="Already exists", status=409, detail=detail)


def lockout_refused(detail: str) -> Problem:
    """The change would leave nobody able to manage roles, so it is not made."""
    return Problem(
        kind="lockout-refused", title="Somebody must keep this", status=409, detail=detail
    )


def role_in_use(holders: Sequence[str]) -> Problem:
    """A role people hold, which they must lose before it can go. `holders` names them."""
    return Problem(
        kind="role-in-use",
        title="Role in use",
        status=409,
        detail="the role is held, so take it from everyone first",
        holders=list(holders),
    )


def edit_conflict(*, revision: int, updated_at: str, updated_by: str | None) -> Problem:
    """A save made against a revision somebody else has since changed.

    It names who changed it and when, so the page can say so in words rather
    than asking the person to reload and guess what moved.
    """
    return Problem(
        kind="edit-conflict",
        title="Changed by someone else",
        status=412,
        detail="this changed after it was read, so the change was not saved",
        revision=revision,
        updated_at=updated_at,
        updated_by=updated_by,
    )


def sign_in_link_unusable() -> Problem:
    """One answer for a link that never existed, was used, or ran out."""
    return Problem(
        kind="sign-in-link-unusable",
        title="Link no longer works",
        status=410,
        detail="this sign-in link has been used or has run out",
    )


def weak_password(detail: str) -> Problem:
    return Problem(kind="weak-password", title="Password not accepted", status=422, detail=detail)


def wrong_password() -> Problem:
    """The current password, given to change it, does not match.

    Not a 401: the session is fine, and a page that signs out on every 401 would
    throw its person out for a typo.
    """
    return Problem(
        kind="wrong-password",
        title="Wrong password",
        status=403,
        detail="that is not the current password",
    )


def policy_not_found(detail: str) -> Problem:
    return Problem(kind="policy-not-found", title="No such policy", status=404, detail=detail)


def policy_exists(detail: str) -> Problem:
    return Problem(kind="policy-exists", title="Slug taken", status=409, detail=detail)


def draft_exists(detail: str, version: int) -> Problem:
    """One draft per policy. `version` names the draft there is, which a client can discard,
    or replace with the upload by asking again with `replace=true`."""
    return Problem(
        kind="draft-exists", title="A draft is open", status=409, detail=detail, version=version
    )


def no_draft(detail: str) -> Problem:
    return Problem(kind="no-draft", title="No draft", status=404, detail=detail)


def flags_open(detail: str, positions: Sequence[int]) -> Problem:
    """Publishing waits for every flag. `flags` lists the open ones by their place."""
    return Problem(
        kind="flags-open",
        title="Flags to settle",
        status=409,
        detail=detail,
        flags=list(positions),
    )


def flag_not_found(detail: str) -> Problem:
    return Problem(kind="flag-not-found", title="No such flag", status=404, detail=detail)


def no_match(detail: str) -> Problem:
    """The draft has no clause by that key, or the clause continues none of the version before."""
    return Problem(kind="no-match", title="No such match", status=404, detail=detail)


def no_clause(detail: str) -> Problem:
    return Problem(kind="no-clause", title="No such clause", status=404, detail=detail)


def fix_refused(detail: str) -> Problem:
    """A fix that cannot be made to that clause as the draft stands, with why."""
    return Problem(kind="fix-refused", title="That fix cannot be made", status=409, detail=detail)


def effective_date_too_early(detail: str) -> Problem:
    """A new version takes effect after the version published before it."""
    return Problem(
        kind="effective-date-too-early", title="Effective date too early", status=409, detail=detail
    )


def version_label_taken(detail: str) -> Problem:
    return Problem(kind="version-label-taken", title="Label taken", status=409, detail=detail)


def too_large(limit: int) -> Problem:
    """Refused before the body is read, so a large one costs the instance nothing."""
    return Problem(
        kind="too-large",
        title="Request too large",
        status=413,
        detail=f"the request body is larger than {limit // (1024 * 1024)} MB",
    )


def unreadable_policy(detail: str) -> Problem:
    """The file cannot be read as a policy, with what to do about it."""
    return Problem(kind="unreadable-policy", title="Unreadable policy", status=422, detail=detail)


def bad_slug(detail: str) -> Problem:
    return Problem(kind="bad-slug", title="Unusable slug", status=422, detail=detail)


def original_unavailable(detail: str) -> Problem:
    """The stored file is missing or no longer matches its hash: an error, never a download."""
    return Problem(
        kind="original-unavailable", title="Original unavailable", status=500, detail=detail
    )


class ProblemDocument(BaseModel):
    """The error shape, declared so the specification carries it.

    A client branches on `type`. `title` and `status` say what class of failure it
    is, and `detail` is written for whoever has to fix it. Some problems add a
    field of their own, such as the permission a token is missing.
    """

    type: str = Field(description="Stable identifier for this kind of failure")
    title: str
    status: int
    detail: str
    instance: str = Field(description="The path that produced it")


TITLES = {
    400: "The request does not make sense",
    401: "No usable credential",
    403: "The credential may not do this",
    404: "No such clause or document",
    409: "The change conflicts with what is there",
    410: "The link has been used or has run out",
    412: "Somebody changed it after it was read",
    413: "The request body is larger than the instance accepts",
    422: "The request body or parameters are not valid",
    429: "The credential has spent its quota for the minute, or too many sign-ins failed",
    500: "A stored original file is missing or has changed",
    503: "The instance is not ready",
}


def responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """What a route says it can fail with, in the specification."""
    return {
        status: {
            "model": ProblemDocument,
            "description": TITLES[status],
            "content": {MEDIA_TYPE: {"schema": {"$ref": "#/components/schemas/ProblemDocument"}}},
        }
        for status in statuses
    }
