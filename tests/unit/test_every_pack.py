"""Every pack in the repository, read the way an instance reads it.

A pack's pull request adds folders and nothing else, so these are the checks it has to pass:
its files hold what its `pack.yaml` says, its licensing fields are filled in, its short name is
no other pack's, and the questions that measure its search exist in the law's own language and
in English, each expecting a clause the pack has.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from dpolens.engine.evals.run import read_questions
from dpolens.engine.packs.format import (
    PackMetadata,
    read_document,
    read_pack_metadata,
    read_translations,
)

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
    languages = dict.fromkeys([pack.authoritative_language, "en"])

    for kind in ("tuning", "held_out"):
        for language in languages:
            name = f"{kind}.{language}.yaml"
            questions = read_questions(REPO / "evals" / pack.slug / name)
            expected = {key for question in questions for key in question.expected_keys}
            assert expected <= keys, f"{name} expects what {pack.slug} lacks: {expected - keys}"


def shared_short_names(packs: list[PackMetadata]) -> list[str]:
    """Each short name two packs share in a language, which a reader could not tell apart."""
    named: dict[tuple[str, str], str] = {}
    shared = []
    for pack in packs:
        for lang, name in pack.short_name.items():
            first = named.setdefault((lang, name.casefold()), pack.slug)
            if first != pack.slug:
                shared.append(f"{first} and {pack.slug} are both {name!r} in {lang}")
    return shared


def test_no_two_packs_share_a_short_name() -> None:
    """A short name names the place wherever an abbreviation is shared: UAE PDPL, Saudi PDPL."""
    assert shared_short_names([read_pack_metadata(pack_dir) for pack_dir in PACKS]) == []


def test_a_short_name_two_packs_share_is_found() -> None:
    uae = read_pack_metadata(REPO / "packs" / "uae-pdpl")
    saudi = replace(uae, slug="sa-pdpl", short_name={"ar": "نظام حماية البيانات", "en": "Uae pdpl"})

    assert shared_short_names([uae, saudi]) == ["uae-pdpl and sa-pdpl are both 'Uae pdpl' in en"]
