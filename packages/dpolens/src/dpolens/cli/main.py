"""Entry point for the `dpolens` command."""

from __future__ import annotations

from typing import Annotated, Any

import typer
from typer.core import TyperGroup

from dpolens import __version__
from dpolens.cli import (
    clause,
    evals,
    governance,
    index,
    init,
    laws,
    model,
    pack,
    policy,
    queries,
    role,
    search,
    token,
    user,
    worker,
)
from dpolens.cli.ask import Asking
from dpolens.engine.auth.catalog import StalePermission
from dpolens.engine.auth.passwords import NoPasswordAllowed, WeakPassword
from dpolens.engine.auth.roles import DuplicateRole, RoleInUse, UnknownPermission
from dpolens.engine.auth.surface import SurfaceOwnerIsAPerson
from dpolens.engine.auth.tokens import (
    AmbiguousPrefix,
    OwnerCannotHoldTokens,
    PermissionsExceedOwner,
    TokenNotFound,
    TokenRejected,
    UnknownToken,
)
from dpolens.engine.auth.users import (
    DuplicateEmail,
    LockoutRefused,
    RoleNotFound,
    UserErased,
    UserNotFound,
)
from dpolens.engine.documents.read import ClauseNotFound
from dpolens.engine.instance import MissingInstanceRow
from dpolens.engine.logs.export import ExportRefused, MalformedExport
from dpolens.engine.originals import OriginalsUnwritable, OriginalUnavailable
from dpolens.engine.packs.archive import ArchiveError
from dpolens.engine.packs.format import PackFormatError
from dpolens.engine.packs.releases import ReleaseError as PackReleaseError
from dpolens.engine.packs.selection import (
    EmptySelection,
    NothingSelected,
    NotSelected,
    UnknownLaw,
)
from dpolens.engine.policies.blocks import UnreadablePolicy
from dpolens.engine.policies.fixing import CannotFix
from dpolens.engine.policies.library import SameVersion
from dpolens.engine.policies.store import (
    BadSlug,
    DraftExists,
    EffectiveDateTooEarly,
    FlagNotFound,
    FlagsOpen,
    LabelTaken,
    MatchRefused,
    NoClause,
    NoDraft,
    NoMatch,
    PolicyExists,
    PolicyNotFound,
)
from dpolens.engine.session import DatabaseUnavailable, MissingExtension, NotMigrated

# Problems a person can act on: printed as one line, without a traceback.
EXPECTED = (
    DatabaseUnavailable,
    MissingExtension,
    NotMigrated,
    MissingInstanceRow,
    ClauseNotFound,
    PackFormatError,
    ArchiveError,
    PackReleaseError,
    StalePermission,
    UserNotFound,
    DuplicateEmail,
    RoleNotFound,
    LockoutRefused,
    UserErased,
    DuplicateRole,
    RoleInUse,
    UnknownPermission,
    ExportRefused,
    MalformedExport,
    PermissionsExceedOwner,
    OwnerCannotHoldTokens,
    TokenNotFound,
    AmbiguousPrefix,
    TokenRejected,
    UnknownToken,
    SurfaceOwnerIsAPerson,
    UnknownLaw,
    NotSelected,
    NothingSelected,
    WeakPassword,
    NoPasswordAllowed,
    EmptySelection,
    UnreadablePolicy,
    PolicyNotFound,
    PolicyExists,
    DraftExists,
    NoDraft,
    FlagsOpen,
    FlagNotFound,
    NoMatch,
    NoClause,
    MatchRefused,
    CannotFix,
    SameVersion,
    EffectiveDateTooEarly,
    LabelTaken,
    BadSlug,
    OriginalUnavailable,
    OriginalsUnwritable,
)


class ReportingGroup(TyperGroup):
    """Report an expected failure as one line, from wherever a command was run.

    Every command shares this, so none of them has to remember to catch the
    failure it can produce, and the message a person sees in a terminal is the
    message a test asserts on.
    """

    def invoke(self, ctx: Any) -> Any:
        try:
            return super().invoke(ctx)
        except EXPECTED as problem:
            typer.secho(str(problem), fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from problem


app = typer.Typer(
    cls=ReportingGroup,
    name="dpolens",
    help="Grounds AI coding assistants in your organisation's policies and the law.",
    no_args_is_help=True,
)


app.command(name="init")(init.run)
app.add_typer(pack.app)
app.add_typer(laws.app)
app.add_typer(policy.app)
app.add_typer(clause.app)
app.add_typer(user.app)
app.add_typer(role.app)
app.add_typer(token.app)
app.add_typer(governance.app)
app.add_typer(queries.app)
app.add_typer(index.app)
app.add_typer(model.app)
app.add_typer(evals.app)
app.command(name="search", cls=Asking)(search.run)
app.command(name="worker")(worker.run)


def _print_version(asked: bool) -> None:
    if asked:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def cli(
    show_version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_print_version,
            is_eager=True,
            help="Print the DPOLens version and exit.",
        ),
    ] = False,
) -> None:
    """Commands are grouped noun then verb: `dpolens pack load`, `dpolens clause show`."""


@app.command()
def version() -> None:
    """Print the DPOLens version."""
    typer.echo(__version__)


def main() -> None:
    # A backstop for anything raised outside a command's own invocation; the
    # group above is what reports a failure inside one.
    try:
        app()
    except EXPECTED as problem:
        typer.secho(str(problem), fg=typer.colors.RED, err=True)
        raise SystemExit(1) from problem
