"""Asking for what a command was not given: in a terminal it asks, from a script it
refuses as it always did, naming the flag."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

import click
import pytest
import typer
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from typer.testing import CliRunner, Result

from dpolens.cli import ask
from dpolens.cli.ask import Asking

runner = CliRunner()
app = typer.Typer()
BORDERS = str.maketrans(dict.fromkeys("│╭╮╰╯─", " "))


def said(result: Result) -> str:
    """The output as the words a person reads, on one line, whatever box CI draws."""
    return " ".join(click.unstyle(result.output).translate(BORDERS).split())


@app.command(cls=Asking)
def visit(
    email: Annotated[str, typer.Option(help="Whose visit")],
    days: Annotated[int, typer.Argument(help="How many days")],
    note: Annotated[str, typer.Option(help="Anything to add")] = "none",
) -> None:
    typer.echo(f"{email} for {days + 1} days, note {note}")


@pytest.fixture
def asked(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """A terminal whose person answers in turn, with the labels they were shown."""
    labels: list[str] = []
    answers = iter(["sara@example.com", "41"])

    def answer(label: str) -> str:
        labels.append(label)
        return next(answers)

    monkeypatch.setattr(ask, "interactive", lambda: True)
    monkeypatch.setattr(ask, "text", answer)
    yield labels


def test_a_script_is_refused_as_before_naming_the_flag() -> None:
    result = runner.invoke(app, ["3"])

    assert result.exit_code == 2
    assert "Missing option '--email'" in said(result)


def test_a_terminal_is_asked_for_each_missing_input_in_order(asked: list[str]) -> None:
    result = runner.invoke(app, [])

    assert result.exit_code == 0, result.output
    assert "sara@example.com for 42 days, note none" in result.output
    assert asked == ["Whose visit", "How many days"]


def test_what_was_given_is_never_asked_for(asked: list[str]) -> None:
    result = runner.invoke(app, ["--email", "omar@example.com", "6"])

    assert result.exit_code == 0, result.output
    assert "omar@example.com for 7 days" in result.output
    assert asked == []


def test_a_value_needed_only_sometimes_names_its_flag_from_a_script() -> None:
    with pytest.raises(typer.BadParameter, match="no terminal"):
        ask.needed(None, flag="--email", label="Email")
    assert ask.needed("sara@example.com", flag="--email", label="Email") == "sara@example.com"


@contextmanager
def typed(keys: str) -> Iterator[None]:
    """A terminal into which these keys have been typed, for the real prompts to read."""
    with create_pipe_input() as typing:
        typing.send_text(keys)
        with create_app_session(input=typing, output=DummyOutput()):
            yield


DOWN = "\x1b[B"
ENTER = "\r"


def test_text_is_read_as_typed_without_the_spaces_around_it() -> None:
    with typed(f"  sara@example.com {ENTER}"):
        assert ask.text("Email") == "sara@example.com"


def test_a_checklist_is_picked_with_the_arrow_keys_and_space() -> None:
    with typed(f" {DOWN} {ENTER}"):
        picked = ask.checklist("Laws", [("gdpr", "GDPR"), ("uae-pdpl", "UAE PDPL")])

    assert picked == ["gdpr", "uae-pdpl"]


def test_what_is_ticked_already_can_be_kept_with_enter() -> None:
    with typed(ENTER):
        picked = ask.checklist(
            "Laws", [("gdpr", "GDPR"), ("uae-pdpl", "UAE PDPL")], checked=["uae-pdpl"]
        )

    assert picked == ["uae-pdpl"]


def test_a_password_too_short_is_asked_for_again() -> None:
    good = "correct horse battery staple"
    with typed(f"too short{ENTER}{good}{ENTER}{good}{ENTER}"):
        assert ask.password() == good
