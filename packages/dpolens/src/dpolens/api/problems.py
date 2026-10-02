"""Every failure the API reports, in one shape.

RFC 9457 problem details: `type` is the stable identifier a client branches on,
`title` and `status` describe the class of failure, and `detail` is aimed at the
person who has to fix it. There is no separate code field, because `type` is
already that field and two of them would invite clients to match on the wrong
one.
"""

from __future__ import annotations

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


def too_many_requests(retry_after: int) -> Problem:
    """`Retry-After` is the standard field, and the only one a client should learn.

    The IETF RateLimit fields are still a draft whose syntax can change, so
    nothing here emits them yet.
    """
    return Problem(
        kind="too-many-requests",
        title="Too many requests",
        status=429,
        detail=f"this token has spent its quota for the minute. Try again in {retry_after}s",
        headers={"Retry-After": str(retry_after)},
    )


def not_ready(detail: str) -> Problem:
    return Problem(kind="not-ready", title="Not ready", status=503, detail=detail)


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
    422: "The request body or parameters are not valid",
    429: "The token has spent its quota for the minute",
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
