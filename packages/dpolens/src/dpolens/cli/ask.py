"""Asking a person at a terminal for what a command was not given.

Run in a terminal, a command asks for each required input it is missing, and picks
from a list with the arrow keys and space. Run from a script, with no terminal, it
fails as it always did, naming the flag, so nothing waits for an answer that will
never come. Flags work the same either way.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from typing import Any

import questionary
import typer
from typer.core import TyperCommand

from dpolens.engine.auth.passwords import MIN_LENGTH, WeakPassword, check_strength


def interactive() -> bool:
    """A person at a terminal, rather than a script or a pipe."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def _answered(answer: Any) -> Any:
    # questionary answers None when the person gives up with Ctrl-C.
    if answer is None:
        raise typer.Abort()
    return answer


def text(label: str) -> str:
    """One line of text, which cannot be left empty."""
    answer = questionary.text(
        f"{label}:", validate=lambda typed: bool(typed.strip()) or "This one is needed"
    ).ask()
    return str(_answered(answer)).strip()


def secret(label: str, *, fault: Callable[[str], str | None] = lambda _: None) -> str:
    """A password, typed twice and shown neither time. `fault` says what is wrong with
    one, or nothing, so it is asked again rather than refused once everything else is done."""
    while True:
        first = str(_answered(questionary.password(f"{label}:").ask()))
        wrong = fault(first)
        if wrong:
            typer.secho(f"{wrong[0].upper()}{wrong[1:]}. Once more.", fg=typer.colors.YELLOW)
            continue
        again = str(_answered(questionary.password("The same again:").ask()))
        if first == again:
            return first
        typer.secho("The two did not match. Once more.", fg=typer.colors.YELLOW)


def _weakness(password: str) -> str | None:
    try:
        check_strength(password)
    except WeakPassword as weak:
        return str(weak)
    return None


def password() -> str:
    """A new password for the dashboard, asked again until the instance will take it."""
    return secret(
        f"A password for the dashboard, at least {MIN_LENGTH} characters", fault=_weakness
    )


def checklist(
    label: str,
    choices: Sequence[tuple[str, str]],
    *,
    checked: Sequence[str] = (),
    at_least_one: bool = False,
) -> list[str]:
    """Some of a list, each choice a value and what to call it, picked with space."""
    answer = questionary.checkbox(
        f"{label}:",
        choices=[
            questionary.Choice(title, value=value, checked=value in checked)
            for value, title in choices
        ],
        instruction="(arrow keys to move, space to pick, enter when done)",
        validate=lambda picked: (bool(picked) or "Pick at least one") if at_least_one else True,
    ).ask()
    return [str(value) for value in _answered(answer)]


def needed(value: str | None, *, flag: str, label: str) -> str:
    """A value a command needs only in some cases, asked for when it is one of them."""
    if value:
        return value
    if interactive():
        return text(label)
    raise typer.BadParameter("needed, and there is no terminal to ask in", param_hint=f"'{flag}'")


def _missing(value: Any) -> bool:
    return value is None or value == () or value == []


class Asking(TyperCommand):
    """A command that asks for each required input it was not given, in a terminal.

    Click is told every input is optional for the parse, so a missing one comes back
    empty instead of failing, and is then asked for in the order the command lists
    its inputs. Without a terminal nothing changes, and Click refuses as before.
    """

    def parse_args(self, ctx: Any, args: list[str]) -> list[str]:
        if not interactive():
            return super().parse_args(ctx, args)
        required = [param for param in self.params if param.required]
        for param in required:
            param.required = False
        try:
            rest = super().parse_args(ctx, args)
        finally:
            for param in required:
                param.required = True
        for param in required:
            if param.name and _missing(ctx.params.get(param.name)):
                label = getattr(param, "help", None) or param.name.replace("_", " ")
                answer = text(label)
                given = [answer] if param.multiple or param.nargs != 1 else answer
                ctx.params[param.name] = param.process_value(ctx, given)
        return rest
