"""The commands an operator runs on a fresh instance, in the order they run them.

These go through Typer rather than calling the engine, because the quickstart in
the README is these commands and their output.
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
    """Point the CLI at its own database, as `DPOLENS_DATABASE_URL` does.

    Its own, because these commands commit and the governance log cannot be
    emptied afterwards.
    """
    monkeypatch.setenv("DPOLENS_DATABASE_URL", committed_database_url)


def run(*arguments: str) -> str:
    result = runner.invoke(app, list(arguments))
    assert result.exit_code == 0, result.output
    return result.output


def failing(*arguments: str) -> str:
    result = runner.invoke(app, list(arguments))
    assert result.exit_code == 1, result.output
    return result.output


def test_the_quickstart_creates_an_administrator(instance: None, unique: str) -> None:
    email = f"cli-admin-{unique}@example.com"

    created = run("user", "create", "--email", email, "--name", "First Admin", "--role", "Admin")
    assert email in created
    assert "person" in created

    listed = run("user", "list")
    assert email in listed
    assert "Admin" in listed
    assert email in run("user", "admins")


def test_the_seeded_roles_are_there_on_first_use(instance: None) -> None:
    listed = run("role", "list")
    for name in catalog.SEEDED_ROLES:
        assert name in listed
    assert catalog.GOVERNANCE_READ in listed


def test_the_permission_catalog_can_be_printed(instance: None) -> None:
    """An operator inventing a role needs to know what the words are."""
    listed = run("role", "permissions")
    for key in catalog.PERMISSIONS:
        assert key in listed


def test_a_role_can_be_invented_and_filled(instance: None, unique: str) -> None:
    name = f"Legal-{unique}"
    run("role", "create", name, "--permission", catalog.DOCUMENTS_READ)
    granted = run("role", "grant", name, catalog.QUERIES_READ_ALL)

    assert catalog.QUERIES_READ_ALL in granted
    assert catalog.DOCUMENTS_READ in granted

    revoked = run("role", "revoke", name, catalog.QUERIES_READ_ALL)
    assert catalog.QUERIES_READ_ALL not in revoked


def test_an_unknown_permission_is_refused_with_the_catalog(instance: None, unique: str) -> None:
    output = failing("role", "create", f"Wrong-{unique}", "--permission", "documents.destroy")
    assert "documents.destroy" in output
    assert catalog.DOCUMENTS_READ in output


def test_the_last_administrator_cannot_be_demoted_from_the_command_line(
    instance: None, unique: str
) -> None:
    """The guard lives in the engine, so the CLI is bound by it too."""
    email = f"cli-only-admin-{unique}@example.com"
    run("user", "create", "--email", email, "--name", "Only Admin", "--role", "Admin")

    # The guard asks about the instance rather than about one user, so the
    # instance is reduced to a single administrator before the refusal is tested.
    for other in run("user", "admins").split():
        if other != email:
            run("user", "revoke", other, "Admin")
    assert run("user", "admins").split() == [email]

    output = failing("user", "revoke", email, "Admin")
    assert catalog.ROLES_MANAGE in output

    # Still there, and still an administrator.
    assert run("user", "admins").split() == [email]


def test_a_second_administrator_makes_the_first_removable(instance: None, unique: str) -> None:
    first = f"cli-first-{unique}@example.com"
    second = f"cli-second-{unique}@example.com"
    run("user", "create", "--email", first, "--name", "First", "--role", "Admin")
    run("user", "create", "--email", second, "--name", "Second", "--role", "Admin")

    run("user", "revoke", first, "Admin")

    admins = run("user", "admins")
    assert second in admins
    assert first not in admins


def test_a_deactivated_user_can_be_let_back_in(instance: None, unique: str) -> None:
    keeper = f"cli-keeper-{unique}@example.com"
    leaver = f"cli-leaver-{unique}@example.com"
    run("user", "create", "--email", keeper, "--name", "Keeper", "--role", "Admin")
    run("user", "create", "--email", leaver, "--name", "Leaver", "--role", "DPO")

    assert "deactivated" in run("user", "deactivate", leaver)
    assert "[deactivated]" in run("user", "list")

    assert "active again" in run("user", "activate", leaver)
    listed = run("user", "list")
    assert f"{leaver}  [active]" in listed
    assert "DPO" in listed


def test_the_governance_log_records_what_the_commands_did(instance: None, unique: str) -> None:
    email = f"cli-logged-{unique}@example.com"
    run("user", "create", "--email", email, "--name", "Logged", "--role", "Developer")

    entries = run("governance", "list", "--limit", "200")
    assert "user.created" in entries
    assert '"via":"cli"' in entries
    assert "os_user" in entries
    assert email not in entries, "the log names a user by id, never by address"


def test_the_log_verifies_and_exports(instance: None, tmp_path: Path, unique: str) -> None:
    run("user", "create", "--email", f"cli-export-{unique}@example.com", "--name", "Exporter")

    verified = run("governance", "verify")
    assert "Verified" in verified
    assert "can change the governance log" not in verified

    out = tmp_path / "export"
    written = run("governance", "export", str(out))
    assert "Verified from the files alone" in written
    assert "Verified" in run("governance", "verify", "--export", str(out))


def test_verify_says_when_the_connection_could_edit_the_log(
    monkeypatch: pytest.MonkeyPatch, migrated: str
) -> None:
    """Connecting as the owner is allowed, and the operator is told what it costs.

    Verification proves the rows have not been edited. Whether they could be is a
    separate question, and a log nobody can edit is the whole claim.
    """
    monkeypatch.setenv("DPOLENS_DATABASE_URL", migrated)

    output = run("governance", "verify")

    assert "Verified" in output
    assert "can change the governance log" in output


def test_an_export_will_not_overwrite_an_existing_one(instance: None, tmp_path: Path) -> None:
    out = tmp_path / "export"
    run("governance", "export", str(out))

    result = runner.invoke(app, ["governance", "export", str(out)])
    assert result.exit_code == 1
    assert "not empty" in result.output
