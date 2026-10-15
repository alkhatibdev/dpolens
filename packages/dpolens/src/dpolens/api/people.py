"""People: who can sign in, the roles they hold, and the link that lets them choose a password.

Everything here needs `users.manage`, and two rules sit on top of it. The
lockout guard, in the engine, keeps somebody able to manage roles. And nobody
gains, through somebody else, a permission they do not hold: a role is given,
and a sign-in link is made, only by someone who holds everything it would grant.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from dpolens.api import problems
from dpolens.api.dependencies import Opened, actor_of, requires
from dpolens.engine.auth import listing
from dpolens.engine.auth import permissions as catalog
from dpolens.engine.auth.links import LinkNotAllowed, make_link
from dpolens.engine.auth.models import User
from dpolens.engine.auth.tokens import Authenticated
from dpolens.engine.auth.users import (
    DuplicateEmail,
    LockoutRefused,
    RoleNotFound,
    UserErased,
    UserNotFound,
    activate,
    create_user,
    deactivate,
    get_role,
    get_user_by_id,
    set_roles,
)

router = APIRouter(
    prefix="/v1/users",
    tags=["people"],
    responses=problems.responses(401, 403, 404, 429),
)

Manager = Annotated[Authenticated, Depends(requires(catalog.USERS_MANAGE))]
Kind = Literal["person", "service_account"]
Status = Literal["active", "deactivated", "erased"]


class Person(BaseModel):
    """Someone who can sign in, or a service account that holds tokens."""

    id: str
    email: str
    display_name: str
    kind: Kind
    status: Status
    roles: list[str]
    created_at: datetime
    deactivated_at: datetime | None
    has_password: bool = Field(description="Whether they can sign in with a password today")
    sign_in_link_expires_at: datetime | None = Field(
        description="When their unused sign-in link runs out, if they have one"
    )
    working_tokens: int = Field(description="Tokens not revoked and not expired")
    acts_for_others: bool = Field(
        description="Holds a token trusted to act for others, as the MCP server's account does"
    )

    @classmethod
    def of(cls, row: listing.PersonRow) -> Person:
        user = row.user
        return cls(
            id=str(user.id),
            email=user.email,
            display_name=user.display_name,
            kind=cast(Kind, user.kind),
            status=cast(Status, user.status),
            roles=[role.name for role in user.roles],
            created_at=user.created_at,
            deactivated_at=user.deactivated_at,
            has_password=user.password_hash is not None,
            sign_in_link_expires_at=row.link_expires_at,
            working_tokens=row.working_tokens,
            acts_for_others=row.acts_for_others,
        )


class People(BaseModel):
    people: list[Person]


class NewPerson(BaseModel):
    email: str = Field(max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
    display_name: str = Field(min_length=1, max_length=200)
    roles: list[str] = Field(default_factory=list, max_length=50)


class StatusChange(BaseModel):
    status: Literal["active", "deactivated"]


class RoleSet(BaseModel):
    roles: list[str] = Field(max_length=50)


class SignInLinkMade(BaseModel):
    """A link's secret, shown once. The dashboard's page for it is `/welcome#<secret>`."""

    secret: str
    expires_at: datetime


def _person(opened: Opened, user_id: uuid.UUID) -> User:
    try:
        return get_user_by_id(opened, user_id)
    except UserNotFound as missing:
        raise problems.not_found(str(missing)) from missing


def _may_give(who: Authenticated, permissions: Iterable[str]) -> None:
    """Refuse to pass on a permission the caller does not hold themselves."""
    missing = sorted(set(permissions) - who.permissions)
    if missing:
        raise problems.permission_required(missing[0])


def _roles_given(opened: Opened, names: Iterable[str]) -> set[str]:
    """Every permission the named roles carry, refusing a role that does not exist."""
    carried: set[str] = set()
    for name in names:
        try:
            carried |= get_role(opened, name).permission_keys()
        except RoleNotFound as unknown:
            raise problems.invalid_request(str(unknown)) from unknown
    return carried


@router.get("", summary="List everyone who can sign in or hold a token")
def list_people(who: Manager, opened: Opened) -> People:
    assert who  # the dependency is the authorisation; this keeps it in the signature
    return People(people=[Person.of(row) for row in listing.people(opened)])


@router.post("", status_code=201, summary="Add a person", responses=problems.responses(400, 409))
def add_person(body: NewPerson, who: Manager, opened: Opened) -> Person:
    _may_give(who, _roles_given(opened, body.roles))
    try:
        user = create_user(
            opened,
            email=body.email,
            display_name=body.display_name.strip(),
            actor=actor_of(who),
            roles=tuple(sorted(set(body.roles))),
        )
    except DuplicateEmail as duplicate:
        raise problems.already_exists(str(duplicate)) from duplicate
    return Person.of(listing.person(opened, user))


@router.patch(
    "/{user_id}",
    summary="Deactivate or reactivate someone",
    responses=problems.responses(400, 409),
)
def change_status(user_id: uuid.UUID, body: StatusChange, who: Manager, opened: Opened) -> Person:
    user = _person(opened, user_id)
    try:
        if body.status == "deactivated":
            deactivate(opened, email=user.email, actor=actor_of(who))
        else:
            activate(opened, email=user.email, actor=actor_of(who))
    except LockoutRefused as refused:
        raise problems.lockout_refused(str(refused)) from refused
    except UserErased as erased:
        raise problems.invalid_request(str(erased)) from erased
    return Person.of(listing.person(opened, user))


@router.put(
    "/{user_id}/roles", summary="Set someone's roles", responses=problems.responses(400, 409)
)
def change_roles(user_id: uuid.UUID, body: RoleSet, who: Manager, opened: Opened) -> Person:
    user = _person(opened, user_id)
    added = set(body.roles) - {role.name for role in user.roles}
    _may_give(who, _roles_given(opened, added))
    try:
        set_roles(opened, user=user, role_names=body.roles, actor=actor_of(who))
    except RoleNotFound as unknown:
        raise problems.invalid_request(str(unknown)) from unknown
    except LockoutRefused as refused:
        raise problems.lockout_refused(str(refused)) from refused
    return Person.of(listing.person(opened, user))


@router.post(
    "/{user_id}/sign-in-links",
    status_code=201,
    summary="Make a one-time link for someone to choose a password",
    responses=problems.responses(400),
)
def make_sign_in_link(user_id: uuid.UUID, who: Manager, opened: Opened) -> SignInLinkMade:
    user = _person(opened, user_id)
    # Using the link is taking the account, so it may not reach further than its maker.
    _may_give(who, user.effective_permissions())
    try:
        row, secret = make_link(opened, user=user, actor=actor_of(who))
    except LinkNotAllowed as refused:
        raise problems.invalid_request(str(refused)) from refused
    return SignInLinkMade(secret=secret, expires_at=row.expires_at)
