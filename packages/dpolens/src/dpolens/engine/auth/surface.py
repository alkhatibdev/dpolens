"""The credential a surface presents, provisioned without anybody copying it.

A surface such as the MCP server cannot reach the database, so it cannot mint
anything for itself. The instance mints one credential for it and writes it to a
file both processes can read, and nothing prints it: a credential in a container
log is a credential in a screenshot, an issue thread and a log aggregator.

The credential carries no permissions at all. What a surface is trusted with is
naming the person it acts for, and the permissions that apply to a call are that
person's token intersected with their roles, so a permission here would grant
nothing and would mislead whoever read it next.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from dpolens.engine.auth.models import PersonalAccessToken, User
from dpolens.engine.auth.tokens import (
    TokenRejected,
    UnknownToken,
    authenticate,
    mint,
    revoke_token,
)
from dpolens.engine.auth.users import UserNotFound, create_user, get_user
from dpolens.engine.logs.governance import Actor

SURFACE_EMAIL = "mcp@surface.invalid"
"""The service account the MCP server's credential belongs to.

`.invalid` is reserved by RFC 2606 and resolves nowhere, which is the point: a
service account is not a person and must never look like one in a list of users.
"""

SURFACE_NAME = "mcp"


class SurfaceOwnerIsAPerson(Exception):
    """That address belongs to a person, and a surface credential is not theirs."""


@dataclass(frozen=True)
class Provisioned:
    """What `ensure_surface` did, for a command that has to say so.

    `prefix` is a plain string rather than something read back from `token`,
    because the command that reports this runs after the session has closed and
    an ORM row cannot be read there.
    """

    token: PersonalAccessToken
    path: Path
    minted: bool
    prefix: str


def ensure_surface(
    session: Session,
    *,
    path: Path,
    actor: Actor,
    email: str = SURFACE_EMAIL,
    name: str = SURFACE_NAME,
) -> Provisioned:
    """Make sure `path` holds a working surface credential, minting one if not.

    Safe to run on every start. A credential that still authenticates is left
    alone, so an instance that restarts keeps the credential its surfaces are
    already using.
    """
    presented = _read(path)
    if presented is not None:
        existing = _usable_surface(session, presented)
        if existing is not None:
            return Provisioned(token=existing, path=path, minted=False, prefix=existing.prefix)

    owner = _service_account(session, email=email, actor=actor)

    # The old secret cannot be recovered from the database, so a file that no
    # longer holds a working one leaves its token unusable. Revoking it keeps
    # exactly one credential that works, which is what `token list` should show.
    for superseded in _tokens_of(session, owner):
        revoke_token(session, superseded, actor=actor)

    row, secret = mint(
        session,
        email=owner.email,
        name=name,
        permissions=(),
        actor=actor,
        trusted_surface=True,
    )
    _write(path, secret)
    return Provisioned(token=row, path=path, minted=True, prefix=row.prefix)


def _read(path: Path) -> str | None:
    """What the file holds, or nothing when there is no file to read."""
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    return content.strip() or None


def _write(path: Path, secret: str) -> None:
    """Write the credential so no reader ever sees half of one.

    Written to a neighbouring name and renamed, because a surface may be waiting
    on this file and a partial read is a token that does not work. The mode is
    set as the file is created rather than afterwards: between the two there is a
    moment when anybody on the host can read it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(f".{path.name}.pending")
    descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(secret + "\n")
    os.replace(pending, path)


def _usable_surface(session: Session, presented: str) -> PersonalAccessToken | None:
    """The row behind a token that still works and may act for other people."""
    try:
        who = authenticate(session, presented)
    except UnknownToken, TokenRejected:
        return None
    return who.token if who.token.trusted_surface else None


def _service_account(session: Session, *, email: str, actor: Actor) -> User:
    try:
        owner = get_user(session, email)
    except UserNotFound:
        return create_user(
            session,
            email=email,
            display_name="MCP server",
            actor=actor,
            kind="service_account",
        )

    if owner.kind != "service_account":
        raise SurfaceOwnerIsAPerson(
            f"{owner.email} belongs to a person, so a surface credential cannot be "
            "created for it. Name a service account instead."
        )
    return owner


def _tokens_of(session: Session, owner: User) -> list[PersonalAccessToken]:
    """The service account's own tokens that still work, newest last."""
    return list(
        session.scalars(
            select(PersonalAccessToken)
            .where(
                PersonalAccessToken.user_id == owner.id,
                PersonalAccessToken.revoked_at.is_(None),
            )
            .order_by(PersonalAccessToken.created_at)
        ).all()
    )
