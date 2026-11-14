"""`dpolens evals compare`, on outcomes files written by hand: it reads no database."""

from __future__ import annotations

import json
from pathlib import Path

import click
from typer.testing import CliRunner, Result

from dpolens.cli.main import app

runner = CliRunner()
BORDERS = str.maketrans(dict.fromkeys("│╭╮╰╯─", " "))


def said(result: Result) -> str:
    """The output on one line, without the colour and borders CI draws an error in."""
    return " ".join(click.unstyle(result.output).translate(BORDERS).split())


def outcomes(path: Path, pack: str, places: dict[str, int | None]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "pack": pack,
                "sets": [
                    {
                        "question_set": "tuning.en",
                        "questions": [
                            {"id": question, "topic": question, "place": place}
                            for question, place in places.items()
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def all_at(place: int | None) -> dict[str, int | None]:
    return {f"topic-{number}": place for number in range(20)}


def test_a_clear_gain_is_kept(tmp_path: Path) -> None:
    before = outcomes(tmp_path / "before.json", "law", all_at(None))
    after = outcomes(tmp_path / "after.json", "law", all_at(1))

    result = runner.invoke(app, ["evals", "compare", str(before), str(after)])

    assert result.exit_code == 0, result.output
    assert "law tuning.en: 20 questions hits at five 0 to 20" in said(result)
    assert "By topic at five: 20 found, 0 lost" in said(result)
    assert said(result).endswith("Kept.")


def test_the_same_run_twice_is_no_gain(tmp_path: Path) -> None:
    before = outcomes(tmp_path / "before.json", "law", all_at(3))

    result = runner.invoke(app, ["evals", "compare", str(before), str(before)])

    assert result.exit_code == 0, result.output
    assert "No gain: the right clauses sit no higher than before." in said(result)
    assert said(result).endswith("Not kept.")


def test_a_folder_holds_one_file_for_each_law(tmp_path: Path) -> None:
    outcomes(tmp_path / "before" / "first.json", "first", all_at(None))
    outcomes(tmp_path / "before" / "second.json", "second", all_at(None))
    outcomes(tmp_path / "after" / "first.json", "first", all_at(1))
    outcomes(tmp_path / "after" / "second.json", "second", all_at(2))

    result = runner.invoke(
        app, ["evals", "compare", str(tmp_path / "before"), str(tmp_path / "after")]
    )

    assert result.exit_code == 0, result.output
    assert "All: 40 questions on 40 topics hits at five 0 to 40" in said(result)


def test_runs_over_different_questions_are_refused(tmp_path: Path) -> None:
    before = outcomes(tmp_path / "before.json", "law", {"a": 1, "b": 2})
    after = outcomes(tmp_path / "after.json", "law", {"a": 1})

    result = runner.invoke(app, ["evals", "compare", str(before), str(after)])

    assert result.exit_code == 2
    assert "the two runs do not ask the same questions" in said(result)


def test_a_file_that_is_not_an_outcomes_file_is_named(tmp_path: Path) -> None:
    other = tmp_path / "results.json"
    other.write_text('{"pack": "law", "runs": []}', encoding="utf-8")

    result = runner.invoke(app, ["evals", "compare", str(other), str(other)])

    assert result.exit_code == 2
    assert "results.json is not an outcomes file" in said(result)
