"""The token commands, which are the third thing an operator runs.

The one that matters most is `create`: it prints a secret once, and everything
about the design depends on that being the only time it appears.
"""

from __future__ import annotations

from pathlib import Path

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


class TestEnsuringASurfaceCredential:
    """What a container's entrypoint runs, which is where this has to work.

    The command reports after the session has closed, so these also cover the
    reason it has a prefix of its own to print.
    """

    def test_it_writes_a_credential_and_never_prints_one(
        self, instance: None, tmp_path: Path, unique: str
    ) -> None:
        out = tmp_path / "surface-token"

        output = run(
            "token",
            "ensure-surface",
            "--out",
            str(out),
            "--name",
            f"mcp-{unique}",
            "--email",
            f"surface-{unique}@surface.invalid",
        )

        written = out.read_text(encoding="utf-8").strip()
        assert written.startswith("dpol_")
        assert written not in output
        assert out.read_text(encoding="utf-8").strip() == written
        assert "Wrote a surface credential" in output
        assert written[:11] in output

    def test_running_it_again_leaves_the_credential_alone(
        self, instance: None, tmp_path: Path, unique: str
    ) -> None:
        out = tmp_path / "surface-token"
        email = f"surface-{unique}@surface.invalid"
        run("token", "ensure-surface", "--out", str(out), "--email", email)
        written = out.read_text(encoding="utf-8")

        output = run("token", "ensure-surface", "--out", str(out), "--email", email)

        assert "still works" in output
        assert out.read_text(encoding="utf-8") == written

    def test_the_credential_it_writes_is_listed_as_a_trusted_surface(
        self, instance: None, tmp_path: Path, unique: str
    ) -> None:
        out = tmp_path / "surface-token"
        run(
            "token",
            "ensure-surface",
            "--out",
            str(out),
            "--name",
            f"mcp-{unique}",
            "--email",
            f"surface-{unique}@surface.invalid",
        )

        listed = run("token", "list")

        # Exactly one credential works at a time: provisioning a new one
        # supersedes whatever the service account held before.
        rows = [row for row in listed.splitlines() if f"mcp-{unique}" in row]
        active = [row for row in rows if "[active]" in row]
        assert len(active) == 1
        assert "[trusted surface]" in active[0]
