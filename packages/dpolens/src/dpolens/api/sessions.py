"""Signing in to the dashboard, through the same API every other surface uses.

A sign-in sets a cookie the page's scripts cannot read and another site cannot
send. Everything after it is an ordinary call to the API, made with that cookie
instead of a token, so the dashboard can do nothing a token could not.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from dpolens.api import problems
from dpolens.api.dependencies import (
    PLAIN_HTTP_SESSION_COOKIE,
    SESSION_COOKIE,
    Caller,
    Configured,
    Opened,
    browser_uses_https,
    check_same_origin,
    lifetimes_of,
    session_cookie_name,
)
from dpolens.api.limits import SignInThrottle
from dpolens.engine.auth.models import DashboardSession
from dpolens.engine.auth.passwords import MAX_LENGTH
from dpolens.engine.auth.sessions import SignInRefused, record_refusal, sign_in, sign_out
from dpolens.engine.auth.users import normalise_email
from dpolens.engine.session import session_from
from dpolens.settings import Settings
from dpolens.telemetry import get_logger

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])

telemetry = get_logger(__name__)


class SignIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=MAX_LENGTH)


class Account(BaseModel):
    email: str
    display_name: str
    roles: list[str]


class SignedIn(BaseModel):
    """Who is signed in, what they may do, and when the session ends."""

    account: Account
    permissions: list[str] = Field(description="What this session may do right now")
    expires_at: datetime = Field(description="When the session ends however much it is used")
    idle_minutes: int = Field(description="Minutes without a request after which it ends sooner")

    @classmethod
    def of(cls, row: DashboardSession, settings: Settings) -> SignedIn:
        user = row.user
        return cls(
            account=Account(
                email=user.email,
                display_name=user.display_name,
                roles=[role.name for role in user.roles],
            ),
            permissions=sorted(user.effective_permissions()),
            expires_at=row.expires_at,
            idle_minutes=settings.session_idle_minutes,
        )


@router.post(
    "",
    status_code=201,
    summary="Sign in to the dashboard",
    responses=problems.responses(401, 403, 429),
)
def start(
    request: Request, body: SignIn, response: Response, opened: Opened, settings: Configured
) -> SignedIn:
    check_same_origin(request)
    throttle: SignInThrottle = request.app.state.sign_in_throttle
    address = normalise_email(body.email)
    wait = throttle.wait(address)
    if wait is not None:
        raise problems.too_many_attempts(wait)

    try:
        row, secret = sign_in(
            opened, email=body.email, password=body.password, lifetimes=lifetimes_of(settings)
        )
    except SignInRefused as refused:
        throttle.failed(address)
        # In a session of its own: the request is about to fail and roll back, and
        # the record of somebody trying an account's password has to outlive that.
        with session_from(request.app.state.engine) as own:
            record_refusal(own, refused)
        telemetry.info("session.refused", reason=refused.reason)
        raise problems.sign_in_refused() from refused

    throttle.succeeded(address)
    secure = browser_uses_https(request)
    response.set_cookie(
        session_cookie_name(secure),
        secret,
        max_age=settings.session_lifetime_hours * 3600,
        path="/",
        secure=secure,
        httponly=True,
        samesite="strict",
    )
    return SignedIn.of(row, settings)


@router.get(
    "/current",
    summary="Who is signed in",
    responses=problems.responses(401, 403, 429),
)
def current(who: Caller, settings: Configured) -> SignedIn:
    if who.session is None:
        raise problems.unauthenticated("this route is about a dashboard session, not a token")
    return SignedIn.of(who.session, settings)


@router.delete(
    "/current",
    status_code=204,
    summary="Sign out",
    response_class=Response,
    responses=problems.responses(401, 403, 429),
)
def end(who: Caller, opened: Opened) -> Response:
    if who.session is None:
        raise problems.unauthenticated("this route is about a dashboard session, not a token")
    sign_out(opened, who.session)
    response = Response(status_code=204)
    for name, secure in ((SESSION_COOKIE, True), (PLAIN_HTTP_SESSION_COOKIE, False)):
        response.delete_cookie(name, path="/", secure=secure, httponly=True, samesite="strict")
    return response
