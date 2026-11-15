"""A law measured beside the others, as an organisation that selected several searches.

Both real packs are loaded and nothing is embedded: keyword search needs no vectors, and it
is enough to see which laws a run reaches.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from dpolens.cli.main import app
from dpolens.engine.embedding import Embedder, get_model
from dpolens.engine.evals import read_questions, run_set
from dpolens.engine.packs.load import load_pack

pytestmark = pytest.mark.integration

REPO = Path(__file__).parents[2]
TUNING = REPO / "evals" / "uae-pdpl" / "tuning.en.yaml"
KEYWORD = "keyword+normative"


@pytest.fixture(scope="session")
def embedder() -> Iterator[Embedder]:
    with Embedder(get_model("e5-small")) as loaded:
        yield loaded


@pytest.fixture(scope="module")
def both_laws(engine: Engine, truncate_corpus: Callable[[], None]) -> Iterator[Session]:
    with Session(engine) as prepared:
        load_pack(prepared, REPO / "packs" / "gdpr")
        load_pack(prepared, REPO / "packs" / "uae-pdpl")
        prepared.commit()
        yield prepared

    truncate_corpus()


def laws_reached(returned: tuple[str, ...]) -> set[str]:
    return {key.split(":", 1)[0] for key in returned}


def test_a_run_for_a_pack_reaches_its_law_alone(both_laws: Session, embedder: Embedder) -> None:
    run = run_set(both_laws, embedder, read_questions(TUNING), KEYWORD, pack="uae-pdpl")

    assert run.beside == ()
    assert {law for outcome in run.outcomes for law in laws_reached(outcome.returned)} == {
        "uae-pdpl"
    }


def test_beside_every_law_a_run_reaches_them_all_and_says_which(
    both_laws: Session, embedder: Embedder
) -> None:
    questions = read_questions(TUNING)

    run = run_set(
        both_laws,
        embedder,
        questions,
        KEYWORD,
        pack="uae-pdpl",
        question_set="tuning.en",
        every_law=True,
    )

    assert (run.beside, run.name) == (("gdpr",), "tuning.en beside gdpr")
    assert {law for outcome in run.outcomes for law in laws_reached(outcome.returned)} == {
        "gdpr",
        "uae-pdpl",
    }
    assert [outcome.expected for outcome in run.outcomes] == [
        question.expected_keys for question in questions
    ]


def test_the_command_keeps_such_a_run_as_a_set_of_its_own(
    both_laws: Session, migrated: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kept beside the run of the law alone, the two are two sets, so one folder holds both
    and a change is judged on each."""
    monkeypatch.chdir(REPO)
    monkeypatch.setenv("DPOLENS_DATABASE_URL", migrated)
    runner = CliRunner()
    asked_for = ["--pack", "uae-pdpl", "--set", "tuning.en", "--config", KEYWORD]
    kept_in = tmp_path / "kept"
    alone, beside = kept_in / "alone.json", kept_in / "beside.json"

    ran_alone = runner.invoke(app, ["evals", "run", *asked_for, "--outcomes", str(alone)])
    ran = runner.invoke(app, ["evals", "run", *asked_for, "--every-law", "--outcomes", str(beside)])
    compared = runner.invoke(app, ["evals", "compare", str(kept_in), str(kept_in)])

    assert (ran_alone.exit_code, ran.exit_code) == (0, 0), ran.output
    assert "uae-pdpl tuning.en beside gdpr: 58 questions" in ran.output
    kept = json.loads(beside.read_text(encoding="utf-8"))
    assert [asked["question_set"] for asked in kept["sets"]] == ["tuning.en beside gdpr"]
    assert compared.exit_code == 0, compared.output
    assert "uae-pdpl tuning.en: 58 questions" in compared.output
    assert "uae-pdpl tuning.en beside gdpr: 58 questions" in compared.output
