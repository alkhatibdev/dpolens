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
    session_cookie_name,
)
from dpolens.api.limits import SignInThrottle
from dpolens.engine.auth.links import LinkUnusable, redeem, usable_link
from dpolens.engine.auth.models import DashboardSession
from dpolens.engine.auth.passwords import (
    MAX_LENGTH,
    WeakPassword,
    WrongPassword,
    change_own_password,
)
from dpolens.engine.auth.sessions import (
    SignInRefused,
    lifetimes_of,
    record_refusal,
    sign_in,
    sign_out,
)
from dpolens.engine.auth.users import normalise_email
from dpolens.engine.session import session_from
from dpolens.settings import Settings
from dpolens.telemetry import get_logger

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])
links = APIRouter(prefix="/v1/sign-in-links", tags=["sessions"])

telemetry = get_logger(__name__)


class SignIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=MAX_LENGTH)


class Account(BaseModel):
    id: str
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
                id=str(user.id),
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
    _hand_over(request, response, secret, settings)
    return SignedIn.of(row, settings)


def _hand_over(request: Request, response: Response, secret: str, settings: Settings) -> None:
    """Give the browser its session, as a cookie its pages' scripts cannot read."""
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


class FromLink(BaseModel):
    secret: str = Field(max_length=200, description="What follows `#` in the link")
    password: str = Field(max_length=MAX_LENGTH)


@router.post(
    "/from-link",
    status_code=201,
    summary="Choose a password with a sign-in link, and sign in",
    responses=problems.responses(403, 410, 422),
)
def from_link(
    request: Request, body: FromLink, response: Response, opened: Opened, settings: Configured
) -> SignedIn:
    """The link is the credential, so nothing else is asked for, and it is spent here.

    No throttle: the link's secret is 256 random bits, which nobody guesses.
    """
    check_same_origin(request)
    try:
        row, secret = redeem(
            opened, secret=body.secret, password=body.password, lifetimes=lifetimes_of(settings)
        )
    except LinkUnusable as unusable:
        telemetry.info("sign_in_link.refused", reason=unusable.reason)
        raise problems.sign_in_link_unusable() from unusable
    except WeakPassword as weak:
        raise problems.weak_password(str(weak)) from weak
    _hand_over(request, response, secret, settings)
    return SignedIn.of(row, settings)


class PasswordChange(BaseModel):
    current: str = Field(max_length=MAX_LENGTH)
    new: str = Field(max_length=MAX_LENGTH)


@router.put(
    "/current/password",
    status_code=204,
    summary="Change your own password",
    response_class=Response,
    responses=problems.responses(401, 403, 422, 429),
)
def change_password(
    request: Request, body: PasswordChange, who: Caller, opened: Opened
) -> Response:
    """Every other session of the person's ends; this one stays.

    A wrong current password counts against the same throttle as a wrong password
    at sign-in, so this form cannot be used to guess it faster.
    """
    if who.session is None:
        raise problems.session_required()
    throttle: SignInThrottle = request.app.state.sign_in_throttle
    address = who.user.email
    wait = throttle.wait(address)
    if wait is not None:
        raise problems.too_many_attempts(wait)
    try:
        change_own_password(
            opened, user=who.user, current=body.current, new=body.new, keep=who.session
        )
    except WrongPassword as wrong:
        throttle.failed(address)
        raise problems.wrong_password() from wrong
    except WeakPassword as weak:
        raise problems.weak_password(str(weak)) from weak
    throttle.succeeded(address)
    return Response(status_code=204)


class LinkSecret(BaseModel):
    secret: str = Field(max_length=200, description="What follows `#` in the link")


class LinkDetails(BaseModel):
    """Who a sign-in link is for, so the page can greet them before they choose a password."""

    email: str
    display_name: str
    expires_at: datetime


@links.post(
    "/lookup",
    summary="Who a sign-in link is for, without spending it",
    responses=problems.responses(403, 410),
)
def look_up_link(request: Request, body: LinkSecret, opened: Opened) -> LinkDetails:
    check_same_origin(request)
    try:
        row = usable_link(opened, secret=body.secret)
    except LinkUnusable as unusable:
        raise problems.sign_in_link_unusable() from unusable
    return LinkDetails(
        email=row.user.email, display_name=row.user.display_name, expires_at=row.expires_at
    )
