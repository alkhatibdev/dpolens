"""`dpolens --version`, which an upgrade checks, prints the version and nothing else."""

from __future__ import annotations

from typer.testing import CliRunner

from dpolens import __version__
from dpolens.cli.main import app

runner = CliRunner()


def test_the_option_prints_the_version_and_stops() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0, result.output
    assert result.output == f"{__version__}\n"


def test_the_option_and_the_command_say_the_same() -> None:
    assert runner.invoke(app, ["version"]).output == runner.invoke(app, ["--version"]).output
