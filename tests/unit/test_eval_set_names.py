"""Which question sets a name means: one language of a set, or every language it is asked in."""

from __future__ import annotations

from pathlib import Path

import pytest

from dpolens.engine.evals import EvalSetError, sets_named


@pytest.fixture
def sets(tmp_path: Path) -> Path:
    for name in ("tuning.ar", "tuning.en", "held_out.ar", "held_out.en"):
        (tmp_path / f"{name}.yaml").write_text("questions: []\n", encoding="utf-8")
    return tmp_path


def test_a_set_named_with_its_language_is_that_set_alone(sets: Path) -> None:
    assert sets_named(sets, "tuning.ar") == ["tuning.ar"]


def test_a_set_named_without_its_language_is_every_language_it_is_asked_in(sets: Path) -> None:
    assert sets_named(sets, "held_out") == ["held_out.ar", "held_out.en"]


def test_a_name_no_set_has_is_refused(sets: Path) -> None:
    with pytest.raises(EvalSetError, match="holds no set named held-out"):
        sets_named(sets, "held-out")
