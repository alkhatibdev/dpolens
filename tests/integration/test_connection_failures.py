"""When the database will not take a connection, the reason comes back in words.

Setup is the first thing a new instance runs, and a driver's traceback is where
most people stop reading. Each test is one way a connection fails against a
real server, and the line a person reads instead.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util import CommandError
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from typer.testing import CliRunner

from dpolens.cli.main import app
from dpolens.engine.session import DatabaseUnavailable, connect

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).parents[2]
AHEAD = "dpolens_ahead"

runner = CliRunner()


def _changed(database_url: str, **parts: Any) -> str:
    return make_url(database_url).set(**parts).render_as_string(hide_password=False)


def _refusal(url: str) -> str:
    engine = create_engine(url)
    try:
        with pytest.raises(DatabaseUnavailable) as raised:
            connect(engine)
    finally:
        engine.dispose()
    return str(raised.value)


def test_a_wrong_password_is_named_with_why_it_changed(database_url: str) -> None:
    owner = make_url(database_url).username

    said = _refusal(_changed(database_url, password="not-the-password"))

    assert f"refused the password for {owner}" in said
    assert "when it creates the role" in said
    assert "ALTER ROLE" in said


def test_a_role_that_does_not_exist_is_refused_the_same_way(database_url: str) -> None:
    said = _refusal(_changed(database_url, username="nobody_here", password="anything"))

    assert "refused the password for nobody_here" in said
    assert "a role that does not exist" in said


def test_a_missing_database_is_named(database_url: str) -> None:
    said = _refusal(_changed(database_url, database="no_such_database"))

    assert 'has no database named "no_such_database"' in said


def test_a_port_with_nothing_on_it_says_nothing_answered(database_url: str) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    said = _refusal(_changed(database_url, host="127.0.0.1", port=port))

    assert f"nothing answered at 127.0.0.1:{port}" in said


def test_a_host_with_no_address_is_named(database_url: str) -> None:
    said = _refusal(_changed(database_url, host="no-such-host.invalid"))

    assert 'the database host "no-such-host.invalid" has no address' in said


def test_a_reason_not_recognised_is_passed_on_as_the_server_gave_it(database_url: str) -> None:
    url = make_url(database_url).update_query_dict({"sslmode": "require"})

    said = _refusal(url.render_as_string(hide_password=False))

    assert said.startswith("could not connect to the database at")
    assert "SSL" in said


def test_a_command_prints_the_reason_without_a_traceback(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DPOLENS_DATABASE_URL", _changed(database_url, password="not-the-password"))

    result = runner.invoke(app, ["laws", "list"])

    assert result.exit_code == 1, result.output
    assert "refused the password" in result.output
    assert "Traceback" not in result.output


def test_setup_ends_with_the_reason_in_one_line(database_url: str) -> None:
    """The migration setup runs first, from the environment, as Compose starts it."""
    wrong = _changed(database_url, password="not-the-password")
    environment = {name: value for name, value in os.environ.items() if "DPOLENS_" not in name}
    environment |= {"DPOLENS_DATABASE_URL": wrong, "DPOLENS_MIGRATION_DATABASE_URL": wrong}

    finished = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    # Alembic prints its verdict to standard output and logs it to standard
    # error, and a container's log shows both.
    assert finished.returncode != 0
    assert finished.stdout.splitlines()[-1].startswith("FAILED: the database at")
    assert "Traceback" not in finished.stdout + finished.stderr


@pytest.fixture
def ahead_of_the_code(database_url: str) -> Iterator[Config]:
    """A database a later version migrated, to a revision this one does not have."""
    server = create_engine(database_url, isolation_level="AUTOCOMMIT")
    url = _changed(database_url, database=AHEAD)
    try:
        with server.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{AHEAD}"'))
            connection.execute(text(f'CREATE DATABASE "{AHEAD}"'))
        database = create_engine(url)
        with database.begin() as connection:
            connection.execute(text("CREATE TABLE alembic_version (version_num varchar(32))"))
            connection.execute(text("INSERT INTO alembic_version VALUES ('9999')"))
        database.dispose()

        config = Config(str(REPO_ROOT / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", url)
        yield config

        with server.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{AHEAD}" WITH (FORCE)'))
    finally:
        server.dispose()


def test_a_database_a_later_version_migrated_says_so(ahead_of_the_code: Config) -> None:
    with pytest.raises(CommandError, match=r"revision 9999.*a later version set it up"):
        command.upgrade(ahead_of_the_code, "head")


def test_such_a_database_can_still_be_stamped(ahead_of_the_code: Config) -> None:
    """`alembic stamp --purge` is how such a database is put right, so it still runs."""
    command.stamp(ahead_of_the_code, "head", purge=True)

    database = create_engine(ahead_of_the_code.get_main_option("sqlalchemy.url") or "")
    with database.connect() as connection:
        stamped = connection.scalar(text("SELECT version_num FROM alembic_version"))
    database.dispose()
    assert stamped == ScriptDirectory.from_config(ahead_of_the_code).get_current_head()
