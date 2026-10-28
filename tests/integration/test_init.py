"""`dpolens init`: the first administrator, their password and the laws that apply, doing
only what is still missing.

Each test has a database of its own, because what init does depends on whether
anybody can manage the instance yet, and every other module makes somebody who can.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import click
import pytest
from sqlalchemy import create_engine, select
from typer.testing import CliRunner, Result

from dpolens.cli import ask
from dpolens.cli.main import app
from dpolens.engine.auth.models import User
from dpolens.engine.auth.passwords import verify
from dpolens.engine.packs.selection import selected_laws
from dpolens.engine.session import session_from

pytestmark = pytest.mark.integration

runner = CliRunner()
PACKS = Path(__file__).parents[1] / "fixtures" / "packs"
PASSWORD = "correct horse battery staple"
BORDERS = str.maketrans(dict.fromkeys("│╭╮╰╯─", " "))


def said(result: Result) -> str:
    """The output as the words a person reads, on one line, whatever box CI draws."""
    return " ".join(click.unstyle(result.output).translate(BORDERS).split())


@pytest.fixture
def fresh(
    database_of_its_own: Callable[[str], tuple[str, str]], monkeypatch: pytest.MonkeyPatch
) -> Iterator[str]:
    """A new instance with two laws loaded and nobody to manage it, by its owner's URL."""
    app_url, owner_url = database_of_its_own(f"dpolens_init_{uuid.uuid4().hex[:8]}")
    monkeypatch.setenv("DPOLENS_DATABASE_URL", app_url)
    for pack in ("testlaw", "bilingual"):
        loaded = runner.invoke(app, ["pack", "load", str(PACKS / pack)])
        assert loaded.exit_code == 0, loaded.output
    yield owner_url


def account(owner_url: str, email: str) -> tuple[list[str], str | None] | None:
    """Someone's roles and password hash, or None when nobody has that address."""
    engine = create_engine(owner_url)
    try:
        with session_from(engine) as opened:
            user = opened.scalars(select(User).where(User.email == email)).first()
            if user is None:
                return None
            return [role.name for role in user.roles], user.password_hash
    finally:
        engine.dispose()


def chosen(owner_url: str) -> list[str] | None:
    engine = create_engine(owner_url)
    try:
        with session_from(engine) as opened:
            return selected_laws(opened)
    finally:
        engine.dispose()


def test_from_a_script_it_takes_flags_and_runs_again_without_changing_anything(
    fresh: str,
) -> None:
    first = runner.invoke(
        app,
        [
            "init",
            "--email", "first@example.com",
            "--name", "First Admin",
            "--password-stdin",
            "--law", "testlaw",
        ],
        input=f"{PASSWORD}\n",
    )  # fmt: skip
    again = runner.invoke(app, ["init"])

    assert first.exit_code == 0, first.output
    assert "Created first@example.com" in first.output
    assert "Searches cover testlaw and your organisation's policies." in first.output
    assert (
        "Open the dashboard at http://localhost:8080 and sign in as first@example.com."
        in first.output
    )
    assert "Under Tokens" in first.output
    made = account(fresh, "first@example.com")
    assert made is not None
    assert made[0] == ["Admin"]
    assert verify(made[1], PASSWORD)
    assert chosen(fresh) == ["testlaw"]

    assert again.exit_code == 0, again.output
    assert (
        "This instance is set up: first@example.com can manage it, and searches cover testlaw."
        in again.output
    )
    assert "dpolens user create" in again.output
    assert "dpolens laws select" in again.output


def test_without_a_terminal_a_missing_answer_names_its_flag_and_nothing_is_made(
    fresh: str,
) -> None:
    result = runner.invoke(app, ["init"])

    assert result.exit_code == 2
    assert "'--email'" in said(result)
    assert chosen(fresh) is None


def test_a_short_password_is_refused_and_nothing_is_made(fresh: str) -> None:
    result = runner.invoke(
        app,
        ["init", "--email", "short@example.com", "--name", "Short", "--password-stdin"],
        input="too short\n",
    )

    assert result.exit_code == 1
    assert "at least 12 characters" in said(result)
    assert account(fresh, "short@example.com") is None


def test_in_a_terminal_it_asks_for_what_is_missing(
    fresh: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    answers = iter(["you@example.com", "Your Name"])
    offered: list[list[str]] = []

    def pick(label: str, choices: list[tuple[str, str]], **_: object) -> list[str]:
        offered.append([value for value, _ in choices])
        return ["bilingual"]

    monkeypatch.setattr(ask, "interactive", lambda: True)
    monkeypatch.setattr(ask, "text", lambda label: next(answers))
    monkeypatch.setattr(ask, "password", lambda: PASSWORD)
    monkeypatch.setattr(ask, "checklist", pick)

    result = runner.invoke(app, ["init"])

    assert result.exit_code == 0, result.output
    assert offered == [["bilingual", "testlaw"]]
    made = account(fresh, "you@example.com")
    assert made is not None
    assert verify(made[1], PASSWORD)
    assert chosen(fresh) == ["bilingual"]


def test_with_an_administrator_already_it_asks_only_for_the_laws(
    fresh: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    made = runner.invoke(
        app, ["user", "create", "--email", "boss@example.com", "--name", "Boss", "--role", "Admin"]
    )
    assert made.exit_code == 0, made.output

    result = runner.invoke(app, ["init", "--law", "bilingual"])

    assert result.exit_code == 0, result.output
    assert "Created" not in result.output
    assert "Searches cover bilingual" in result.output
    assert "Open the dashboard at http://localhost:8080." in result.output
    assert chosen(fresh) == ["bilingual"]


def test_on_a_community_version_it_names_the_law_alone_and_no_token(
    fresh: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A community version holds no organisation's policies, and answers anyone without one."""
    monkeypatch.setenv("DPOLENS_COMMUNITY", "true")
    monkeypatch.setenv("DPOLENS_PUBLIC_MCP_URL", "https://mcp.example.com/")

    result = runner.invoke(
        app,
        [
            "init",
            "--email", "operator@example.com",
            "--name", "Operator",
            "--password-stdin",
            "--law", "testlaw",
        ],
        input=f"{PASSWORD}\n",
    )  # fmt: skip

    assert result.exit_code == 0, result.output
    assert "Searches cover testlaw." in result.output
    assert "your organisation's policies" not in result.output
    assert "AI assistants connect to https://mcp.example.com/ with no token." in result.output
    assert "Under Tokens" not in result.output
