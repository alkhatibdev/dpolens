"""Roles and the permission catalog they are made from.

Reading roles needs `roles.manage` or `users.manage`, since giving someone a role
means knowing what it allows. Changing them needs `roles.manage`.

A role is read with its revision as an `ETag`, and a change may send it back in
`If-Match`. A change made against an older revision is refused with `412` and
names who changed it and when. The dashboard always sends it; a change without
one is made, last write winning, so a script need not read first.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel, Field

from dpolens.api import problems
from dpolens.api.dependencies import Caller, Opened, actor_of, requires, requires_any
from dpolens.engine.auth import listing
from dpolens.engine.auth import permissions as catalog
from dpolens.engine.auth.models import Role
from dpolens.engine.auth.roles import (
    DuplicateRole,
    RoleInUse,
    StaleRole,
    UnknownPermission,
    create_role,
    delete_role,
    edit_role,
    get_role_by_id,
)
from dpolens.engine.auth.tokens import Authenticated
from dpolens.engine.auth.users import LockoutRefused, RoleNotFound

router = APIRouter(prefix="/v1", tags=["roles"], responses=problems.responses(401, 403, 429))

Reader = Annotated[Authenticated, Depends(requires_any(catalog.ROLES_MANAGE, catalog.USERS_MANAGE))]
Editor = Annotated[Authenticated, Depends(requires(catalog.ROLES_MANAGE))]
Kind = Literal["person", "service_account"]
Status = Literal["active", "deactivated", "erased"]


class Permission(BaseModel):
    key: str
    description: str


class Catalog(BaseModel):
    """Every permission this build defines. Roles are made from these and nothing else."""

    permissions: list[Permission]


class Holder(BaseModel):
    id: str
    display_name: str
    kind: Kind
    status: Status


class RoleDocument(BaseModel):
    id: str
    name: str
    description: str
    is_seeded: bool = Field(description="Created with the instance. It is an ordinary role")
    permissions: list[str]
    holders: list[Holder]
    revision: int = Field(description="Goes up with every change. Send it back in `If-Match`")
    created_at: datetime
    updated_at: datetime
    updated_by: str | None = Field(
        description="Who changed it last, or null for a change made on the command line"
    )

    @classmethod
    def of(cls, row: listing.RoleRow) -> RoleDocument:
        role = row.role
        return cls(
            id=str(role.id),
            name=role.name,
            description=role.description,
            is_seeded=role.is_seeded,
            permissions=sorted(role.permission_keys()),
            holders=[
                Holder(
                    id=str(user.id),
                    display_name=user.display_name,
                    kind=cast(Kind, user.kind),
                    status=cast(Status, user.status),
                )
                for user in row.holders
            ],
            revision=role.revision,
            created_at=role.created_at,
            updated_at=role.updated_at,
            updated_by=role.updated_by.display_name if role.updated_by else None,
        )


class Roles(BaseModel):
    roles: list[RoleDocument]


class NewRole(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    permissions: list[str] = Field(default_factory=list, max_length=len(catalog.PERMISSIONS))


class RoleChange(BaseModel):
    """Any of the three. Permissions, when sent, are the whole new set."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] | None = Field(default=None, max_length=len(catalog.PERMISSIONS))


def _etag(role: Role) -> str:
    return f'"{role.revision}"'


def _expected(if_match: str | None) -> int | None:
    """The revision an `If-Match` names, or None when it names none to check."""
    if if_match is None or if_match.strip() == "*":
        return None
    value = if_match.strip().removeprefix("W/").strip('"')
    if not value.isdigit():
        raise problems.invalid_request("If-Match carries the role's revision, as its ETag gave it")
    return int(value)


def _role(opened: Opened, role_id: uuid.UUID, *, for_update: bool = False) -> Role:
    try:
        return get_role_by_id(opened, role_id, for_update=for_update)
    except RoleNotFound as missing:
        raise problems.not_found(str(missing)) from missing


@router.get("/permissions", summary="List the permissions roles are made from")
def list_permissions(who: Caller) -> Catalog:
    assert who  # any signed-in caller: the catalog is the same on every instance
    return Catalog(
        permissions=[
            Permission(key=key, description=description)
            for key, description in catalog.PERMISSIONS.items()
        ]
    )


@router.get("/roles", summary="List the roles, with who holds each")
def list_roles(who: Reader, opened: Opened) -> Roles:
    assert who
    return Roles(roles=[RoleDocument.of(row) for row in listing.roles(opened)])


@router.post(
    "/roles", status_code=201, summary="Create a role", responses=problems.responses(400, 409)
)
def add_role(body: NewRole, who: Editor, opened: Opened, response: Response) -> RoleDocument:
    try:
        role = create_role(
            opened,
            name=body.name.strip(),
            description=body.description.strip(),
            permissions=tuple(sorted(set(body.permissions))),
            actor=actor_of(who),
        )
    except DuplicateRole as duplicate:
        raise problems.already_exists(str(duplicate)) from duplicate
    except UnknownPermission as unknown:
        raise problems.invalid_request(str(unknown)) from unknown
    response.headers["ETag"] = _etag(role)
    return RoleDocument.of(listing.role(opened, role))


@router.get("/roles/{role_id}", summary="Read one role", responses=problems.responses(404))
def read_role(role_id: uuid.UUID, who: Reader, opened: Opened, response: Response) -> RoleDocument:
    assert who
    role = _role(opened, role_id)
    response.headers["ETag"] = _etag(role)
    return RoleDocument.of(listing.role(opened, role))


@router.patch(
    "/roles/{role_id}",
    summary="Rename a role or change what it allows",
    responses=problems.responses(400, 404, 409, 412),
)
def change_role(
    role_id: uuid.UUID,
    body: RoleChange,
    who: Editor,
    opened: Opened,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> RoleDocument:
    role = _role(opened, role_id, for_update=True)
    try:
        edit_role(
            opened,
            role=role,
            actor=actor_of(who),
            expected_revision=_expected(if_match),
            name=body.name.strip() if body.name is not None else None,
            description=body.description.strip() if body.description is not None else None,
            permissions=body.permissions,
        )
    except StaleRole as stale:
        changed = stale.role
        raise problems.edit_conflict(
            revision=changed.revision,
            updated_at=changed.updated_at.isoformat(),
            updated_by=changed.updated_by.display_name if changed.updated_by else None,
        ) from stale
    except DuplicateRole as duplicate:
        raise problems.already_exists(str(duplicate)) from duplicate
    except UnknownPermission as unknown:
        raise problems.invalid_request(str(unknown)) from unknown
    except LockoutRefused as refused:
        raise problems.lockout_refused(str(refused)) from refused
    response.headers["ETag"] = _etag(role)
    return RoleDocument.of(listing.role(opened, role))


@router.delete(
    "/roles/{role_id}",
    status_code=204,
    summary="Delete a role nobody holds",
    response_class=Response,
    responses=problems.responses(404, 409),
)
def remove_role(role_id: uuid.UUID, who: Editor, opened: Opened) -> Response:
    role = _role(opened, role_id, for_update=True)
    try:
        delete_role(opened, role_name=role.name, actor=actor_of(who))
    except RoleInUse as in_use:
        raise problems.role_in_use([user.display_name for user in in_use.holders]) from in_use
    except LockoutRefused as refused:
        raise problems.lockout_refused(str(refused)) from refused
    return Response(status_code=204)
