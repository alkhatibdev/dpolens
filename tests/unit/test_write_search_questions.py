"""Writing one article's search questions again, in place of its old ones in the law's file."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import write_search_questions as writer  # noqa: E402

HEADER = "# Search questions for Test Law.\n"
WRITER = "claude-sonnet-5-5"
CHECKER = "claude-opus-5-5"


def article(key: str, *clauses: tuple[str, str]) -> dict[str, Any]:
    return {
        "key": key,
        "law": ("Test Law", "The Test Law"),
        "heading": {"en": ""},
        "clauses": [{"key": clause, "text": {"en": words}} for clause, words in clauses],
    }


def law_file(questions: Path) -> dict[str, Any]:
    write_prompt, check_prompt = writer.prompts()
    body = {
        "pack": "testlaw",
        "written_by": [WRITER],
        "checked_by": [CHECKER],
        "written_on": "2026-11-07",
        "write_prompt": write_prompt,
        "check_prompt": check_prompt,
        "clauses": [
            {"key": "testlaw:art-1", "text": "0123456789abcdef", "en": ["What is data?"], "ar": []},
            {"key": "testlaw:art-2", "text": "fedcba9876543210", "en": ["Who decides?"], "ar": []},
        ],
    }
    writer.dump(questions / "testlaw.yaml", HEADER, body)
    return body


def written_again(work: Path, chosen: dict[str, Any], model: str = WRITER) -> None:
    for folder in ("written", "checked"):
        (work / folder).mkdir(parents=True, exist_ok=True)
    keys = [clause["key"] for clause in chosen["clauses"]]
    written = {
        "model": model,
        "clauses": [{"key": key, "en": ["A?", "B?"], "ar": []} for key in keys],
    }
    checked = {
        "model": CHECKER,
        "clauses": [{"key": key, "en": [True, False], "ar": []} for key in keys],
    }
    name = writer.saved_as(chosen)
    (work / "written" / name).write_text(json.dumps(written), encoding="utf-8")
    (work / "checked" / name).write_text(json.dumps(checked), encoding="utf-8")


@pytest.fixture
def questions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "search-questions"
    folder.mkdir()
    monkeypatch.setattr(writer, "QUESTIONS", folder)
    monkeypatch.setattr(writer, "REPO", tmp_path)
    return folder


def test_an_article_written_again_takes_the_place_of_its_old_questions(
    questions: Path, tmp_path: Path
) -> None:
    before = law_file(questions)
    every = [
        article(
            "testlaw:art-1",
            ("testlaw:art-1", "In this Law:"),
            ("testlaw:art-1:def-data", "Data: Any."),
        ),
        article("testlaw:art-2", ("testlaw:art-2", "The controller decides.")),
    ]
    written_again(tmp_path / "work", every[0])

    out = writer.rewrite("testlaw", every, [every[0]], tmp_path / "work")
    after = yaml.safe_load(out.read_text(encoding="utf-8"))

    assert [entry["key"] for entry in after["clauses"]] == [
        "testlaw:art-1",
        "testlaw:art-1:def-data",
        "testlaw:art-2",
    ]
    assert after["clauses"][1]["en"] == ["A?"]
    assert after["clauses"][2] == before["clauses"][1]
    assert after["written_on"] == "2026-11-07"
    assert out.read_text(encoding="utf-8").startswith(f"{HEADER}# Written again on ")


def test_an_article_written_by_another_model_is_refused(questions: Path, tmp_path: Path) -> None:
    law_file(questions)
    chosen = article("testlaw:art-1", ("testlaw:art-1", "In this Law:"))
    written_again(tmp_path / "work", chosen, model="another-model")

    with pytest.raises(SystemExit, match="write the whole law again"):
        writer.rewrite("testlaw", [chosen], [chosen], tmp_path / "work")
