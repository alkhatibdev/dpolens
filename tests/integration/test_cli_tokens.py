"""The token commands, which are the third thing an operator runs.

The one that matters most is `create`: it prints a secret once, and everything
about the design depends on that being the only time it appears.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from dpolens.cli.main import app
from dpolens.engine.auth import permissions as catalog

pytestmark = pytest.mark.integration

runner = CliRunner()


@pytest.fixture
def instance(monkeypatch: pytest.MonkeyPatch, committed_database_url: str) -> None:
    monkeypatch.setenv("DPOLENS_DATABASE_URL", committed_database_url)


def run(*arguments: str) -> str:
    result = runner.invoke(app, list(arguments))
    assert result.exit_code == 0, result.output
    return result.output


def failing(*arguments: str) -> str:
    result = runner.invoke(app, list(arguments))
    assert result.exit_code == 1, result.output
    return result.output


def a_developer(unique: str, suffix: str = "") -> str:
    email = f"token-dev{suffix}-{unique}@example.com"
    run("user", "create", "--email", email, "--name", "Token Dev", "--role", "Developer")
    return email


def token_from(output: str) -> str:
    return next(line.strip() for line in output.splitlines() if line.strip().startswith("dpol_"))


def test_creating_a_token_prints_it_once_and_says_so(instance: None, unique: str) -> None:
    email = a_developer(unique)

    output = run(
        "token",
        "create",
        "--email",
        email,
        "--name",
        "laptop",
        "--permission",
        catalog.DOCUMENTS_READ,
    )
    token = token_from(output)

    assert token.startswith("dpol_")
    assert "only time the token is shown" in output
    assert catalog.DOCUMENTS_READ in output

    # And never again, in the listing or anywhere else.
    listed = run("token", "list", "--email", email)
    assert token not in listed
    assert token[:11] in listed
    assert "laptop" in listed
    assert "[active]" in listed


def test_a_permission_the_owner_lacks_is_refused_by_name(instance: None, unique: str) -> None:
    email = a_developer(unique)

    output = failing(
        "token",
        "create",
        "--email",
        email,
        "--name",
        "too much",
        "--permission",
        catalog.QUERIES_READ_ALL,
    )

    assert catalog.QUERIES_READ_ALL in output
    assert email in output


def test_a_permission_outside_the_catalog_is_refused_with_the_catalog(
    instance: None, unique: str
) -> None:
    email = a_developer(unique)

    output = failing(
        "token", "create", "--email", email, "--name", "wrong", "--permission", "documents.destroy"
    )

    assert "documents.destroy" in output
    assert catalog.DOCUMENTS_READ in output


def test_a_token_can_be_revoked_by_its_prefix(instance: None, unique: str) -> None:
    email = a_developer(unique)
    created = run(
        "token",
        "create",
        "--email",
        email,
        "--name",
        "laptop",
        "--permission",
        catalog.DOCUMENTS_READ,
    )
    prefix = token_from(created)[:11]

    revoked = run("token", "revoke", prefix)
    assert "revoked" in revoked
    assert "[revoked]" in run("token", "list", "--email", email)

    # Again, because an operator who is not sure should not be punished for asking.
    assert "revoked" in run("token", "revoke", prefix)


def test_an_unknown_prefix_says_where_to_look(instance: None) -> None:
    output = failing("token", "revoke", "dpol_zzzzzz")
    assert "dpolens token list" in output


def test_a_trusted_surface_token_is_labelled(instance: None, unique: str) -> None:
    """The flag exists for the MCP server, and a person reading the list should see it."""
    email = f"surface-{unique}@example.com"
    run(
        "user",
        "create",
        "--email",
        email,
        "--name",
        "MCP server",
        "--role",
        "Developer",
        "--service",
    )

    created = run(
        "token",
        "create",
        "--email",
        email,
        "--name",
        "mcp",
        "--permission",
        catalog.DOCUMENTS_READ,
        "--trusted-surface",
    )
    assert "may act on behalf of other users" in created
    assert "[trusted surface]" in run("token", "list", "--email", email)


def test_an_expiring_token_says_when(instance: None, unique: str) -> None:
    email = a_developer(unique)

    created = run(
        "token",
        "create",
        "--email",
        email,
        "--name",
        "temporary",
        "--expires-in-days",
        "30",
    )

    assert "expires:" in created
    assert "when revoked" not in created


def test_a_token_with_no_permissions_says_it_can_do_nothing(instance: None, unique: str) -> None:
    email = a_developer(unique)

    created = run("token", "create", "--email", email, "--name", "empty")

    assert "can do nothing" in created
