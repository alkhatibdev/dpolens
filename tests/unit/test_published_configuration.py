"""The published score describes the search people get.

Each pack's results file names the configuration and model its score was measured
with, and every way of searching uses those unless the person searching asks for
something else. A product that ranked by another rule would publish a number
nobody receives.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from dpolens.api.corpus import SearchRequest
from dpolens.cli import search as command_line
from dpolens.engine.embedding import DEFAULT_MODEL
from dpolens.engine.search import search

REPO = Path(__file__).parents[2]
SCORED = sorted(
    path
    for path in (REPO / "evals" / "results").glob("*.json")
    if (REPO / "packs" / path.stem).is_dir()
)
"""Each law pack's retrieval results. The rest of the directory scores something else."""


@pytest.mark.parametrize("path", SCORED, ids=lambda path: path.stem)
def test_search_runs_what_the_published_score_measured(path: Path) -> None:
    # The first run in a results file is the one its score is published from.
    published = json.loads(path.read_text(encoding="utf-8"))["runs"][0]
    fusion, *modifiers = published["configuration"].split("+")

    assert published["model"] == DEFAULT_MODEL
    assert inspect.signature(search).parameters["fusion"].default.name == fusion
    assert inspect.signature(command_line.run).parameters["fusion"].default == fusion

    # +normative: text that only explains is left out until a search asks for it.
    assert modifiers == ["normative"]
    assert SearchRequest.model_fields["include_explanatory"].default is False
    assert inspect.signature(command_line.run).parameters["include_explanatory"].default is False
