"""Every clause of every law the repository ships, read to its end by the search model.

The model reads 512 tokens. A clause longer than that is embedded from its start only, so a
question about its end can find it by its words alone. Where a law divides a long provision, its
pack divides it there too, as the UAE law's definitions are.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from dpolens.engine.embedding import DEFAULT_MODEL, Embedder, get_model
from dpolens.engine.embedding.index import too_long
from dpolens.engine.packs.load import load_pack

pytestmark = pytest.mark.integration

PACKS = Path(__file__).parents[2] / "packs"


@pytest.fixture(scope="module")
def embedder() -> Iterator[Embedder]:
    with Embedder(get_model(DEFAULT_MODEL)) as loaded:
        yield loaded


def test_the_model_reads_every_clause_of_every_shipped_law_to_its_end(
    session: Session, embedder: Embedder
) -> None:
    for pack in sorted(path.parent for path in PACKS.glob("*/pack.yaml")):
        load_pack(session, pack)
    session.commit()

    assert too_long(session, embedder) == []
