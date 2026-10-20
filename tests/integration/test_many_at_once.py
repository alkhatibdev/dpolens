"""Many searches at once, through the API.

A search holds the request's database connection and writes its question to the log
through a second one, which has to outlive the request if the request fails. Fifteen
connections shared by more requests than could each have two once ended with every
request holding one and waiting for another, until the pool's 30 second timeout
failed them all.

In a database of its own, so its token and its questions appear in no other module's
lists.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from dpolens.api.app import create_app
from dpolens.engine.auth import permissions as catalog
from dpolens.engine.auth.catalog import bootstrap
from dpolens.engine.auth.tokens import mint
from dpolens.engine.auth.users import create_user
from dpolens.engine.embedding import DEFAULT_MODEL, get_model
from dpolens.engine.embedding.encode import Embedder
from dpolens.engine.embedding.index import build_index
from dpolens.engine.logs.governance import Actor
from dpolens.engine.packs.load import load_pack
from dpolens.engine.packs.selection import select_laws
from dpolens.engine.session import session_from
from dpolens.settings import Settings

pytestmark = pytest.mark.integration

ACTOR = Actor(via="cli", identity={"os_user": "tests", "host": "ci"})
TESTLAW = Path(__file__).parents[1] / "fixtures" / "packs" / "testlaw"
AT_ONCE = 40


@pytest.fixture(scope="module")
def own(database_of_its_own: Callable[[str], tuple[str, str]]) -> Iterator[tuple[str, str]]:
    """A searchable database, and a token that may search it."""
    app_url, owner_url = database_of_its_own("dpolens_many_at_once")
    owner = create_engine(owner_url)
    with session_from(owner) as opened:
        bootstrap(opened, actor=ACTOR)
        load_pack(opened, TESTLAW)
        select_laws(opened, ["testlaw"], actor=ACTOR)
        create_user(
            opened,
            email="many@example.com",
            display_name="Many",
            actor=ACTOR,
            roles=(catalog.DEVELOPER,),
        )
        opened.flush()
        _, token = mint(
            opened,
            email="many@example.com",
            name="many",
            permissions=(catalog.DOCUMENTS_READ,),
            actor=ACTOR,
        )
    with Embedder(get_model(DEFAULT_MODEL)) as embedder, session_from(owner) as opened:
        build_index(opened, embedder)
    owner.dispose()
    yield app_url, token


def test_forty_searches_at_once_are_all_answered(own: tuple[str, str]) -> None:
    app_url, token = own
    app = create_app(
        Settings.model_validate({"database_url": app_url, "rate_limit_per_minute": 1000})
    )

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=AT_ONCE) as pool:

        def search(number: int) -> int:
            answer = client.post(
                "/v1/search",
                json={"query": f"personal data {number}"},
                headers={"Authorization": f"Bearer {token}"},
            )
            return answer.status_code

        answered = list(pool.map(search, range(AT_ONCE)))

    assert answered == [200] * AT_ONCE
