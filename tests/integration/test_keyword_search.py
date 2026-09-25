"""BM25 keyword retrieval over the real GDPR pack."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from dpolens.engine.packs.load import load_pack
from dpolens.engine.search import UnsupportedLanguage, keyword_search
from dpolens.engine.search.keyword import Candidate
from dpolens.engine.session import MissingExtension, NotMigrated, check_extensions

pytestmark = pytest.mark.integration

GDPR_PACK = Path(__file__).parents[2] / "packs" / "gdpr"


@pytest.fixture
def loaded(session: Session) -> Session:
    load_pack(session, GDPR_PACK)
    session.commit()
    return session


def keys(results: list[Candidate]) -> list[str]:
    return [candidate.key for candidate in results]


def test_finds_the_article_by_its_own_words(loaded: Session) -> None:
    results = keyword_search(loaded, "right to erasure", limit=10)

    assert "gdpr:art-17" in keys(results)[:5]


def test_finds_a_definition_by_its_defined_term(loaded: Session) -> None:
    """Article 4's points are what a keyword ranker should be best at."""
    results = keyword_search(loaded, "pseudonymisation means the processing", limit=10)

    assert "gdpr:art-4:pt-5" in keys(results)[:3]


def test_scores_descend(loaded: Session) -> None:
    results = keyword_search(loaded, "personal data breach notification", limit=20)
    scores = [candidate.score for candidate in results]

    assert scores == sorted(scores, reverse=True)
    assert all(score > 0 for score in scores), "scores are flipped to higher is better"


def test_ranks_are_positions(loaded: Session) -> None:
    results = keyword_search(loaded, "consent", limit=5)

    assert [candidate.rank for candidate in results] == [1, 2, 3, 4, 5]


def test_returns_nothing_for_words_the_corpus_does_not_have(loaded: Session) -> None:
    assert keyword_search(loaded, "kubernetes sidecar helm", limit=10) == []


def test_a_language_without_an_index_is_refused(loaded: Session) -> None:
    """Arabic gets its own index when the PDPL pack lands, not a silent empty result."""
    with pytest.raises(UnsupportedLanguage, match="no BM25 index"):
        keyword_search(loaded, "محو البيانات", lang="ar")


def test_the_extension_check_passes_on_the_dpolens_image(engine: Engine) -> None:
    check_extensions(engine)


def test_a_server_without_the_extension_is_refused() -> None:
    """An instance that cannot rank properly should refuse to start, not degrade."""
    from unittest.mock import MagicMock

    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    # Created, then available: the server offers only pgvector.
    connection.scalars.return_value.all.side_effect = [["vector"], ["vector"]]

    with pytest.raises(MissingExtension, match="does not offer pg_textsearch"):
        check_extensions(engine)


def test_a_database_that_has_not_been_migrated_says_so() -> None:
    """The right fix here is the migrations, not a different image."""
    from unittest.mock import MagicMock

    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.scalars.return_value.all.side_effect = [[], ["vector", "pg_textsearch"]]

    with pytest.raises(NotMigrated, match="alembic upgrade head"):
        check_extensions(engine)
