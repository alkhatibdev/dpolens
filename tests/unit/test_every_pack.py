"""Every pack in the repository, read the way an instance reads it.

A pack's pull request adds folders and nothing else, so these are the checks it has to pass:
its files hold what its `pack.yaml` says, its licensing fields are filled in, and the
questions that measure its search exist in the law's own language and in English, each
expecting a clause the pack has.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dpolens.engine.evals.run import read_questions
from dpolens.engine.packs.format import read_document, read_pack_metadata, read_translations

REPO = Path(__file__).resolve().parents[2]
PACKS = sorted(path.parent for path in (REPO / "packs").glob("*/pack.yaml"))


def test_the_repository_carries_its_packs() -> None:
    """A pattern that matched nothing would pass every test below without checking a thing."""
    assert {"gdpr", "uae-pdpl"} <= {path.name for path in PACKS}


@pytest.mark.parametrize("pack_dir", PACKS, ids=lambda path: path.name)
def test_a_pack_holds_what_its_metadata_says(pack_dir: Path) -> None:
    pack = read_pack_metadata(pack_dir)

    assert pack.slug == pack_dir.name
    for document in pack.documents:
        read_translations(pack_dir, document, pack, read_document(pack_dir, document))


@pytest.mark.parametrize("pack_dir", PACKS, ids=lambda path: path.name)
def test_a_pack_is_asked_in_its_language_and_in_english(pack_dir: Path) -> None:
    pack = read_pack_metadata(pack_dir)
    keys = {
        clause.key
        for document in pack.documents
        for top in read_document(pack_dir, document)
        for clause in top.walk()
    }
    languages = [""] if pack.authoritative_language == "en" else ["", ".en"]

    for kind in ("tuning", "held_out"):
        for language in languages:
            name = f"{kind}{language}.yaml"
            questions = read_questions(REPO / "evals" / pack.slug / name)
            expected = {key for question in questions for key in question.expected_keys}
            assert expected <= keys, f"{name} expects what {pack.slug} lacks: {expected - keys}"
