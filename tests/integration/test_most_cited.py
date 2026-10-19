"""What Most cited counts: each person once a day, only what cited a clause, and only the
laws the organisation selected beside its own policies.

In a database of its own, with every row's time set by hand around a fixed noon, so the
days are the same whenever the tests run.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Engine, create_engine, update

from dpolens.engine.auth.catalog import bootstrap
from dpolens.engine.auth.users import create_user
from dpolens.engine.logs.governance import Actor
from dpolens.engine.logs.models import QueryLogEntry
from dpolens.engine.logs.queries import Returned, record_query
from dpolens.engine.logs.reading import Window, clause_activity, overview
from dpolens.engine.packs.load import load_pack
from dpolens.engine.session import session_from

pytestmark = pytest.mark.integration

ACTOR = Actor(via="cli", identity={"os_user": "tests", "host": "ci"})
PACKS = Path(__file__).parents[1] / "fixtures" / "packs"
NOON = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
WEEK = Window.ending_today(7, ZoneInfo("UTC"), now=NOON)

ARTICLE_5 = "testlaw:art-5:para-1"
ARTICLE_6 = "testlaw:art-6:para-1"
BROWSED = "testlaw:art-6"
UNCHOSEN = "bilingual:art-1"


def first(key: str) -> Returned:
    return Returned(
        key=key,
        lang="en",
        document_slug=key.split(":")[0],
        version_label="2026.1",
        trust_tier="community",
    )


@pytest.fixture(scope="module")
def cited(database_of_its_own: Callable[[str], tuple[str, str]]) -> Iterator[Engine]:
    """Sara asks three times today and once yesterday, Omar searches and browses in the
    dashboard, a script searches three times, and a law nobody chose is cited once."""
    _, owner_url = database_of_its_own("dpolens_most_cited")
    owner = create_engine(owner_url)
    with session_from(owner) as opened:
        bootstrap(opened, actor=ACTOR)
        load_pack(opened, PACKS / "testlaw")
        load_pack(opened, PACKS / "bilingual")
        people = {
            name: create_user(
                opened, email=f"{name}@example.com", display_name=name, actor=ACTOR, kind=kind
            )
            for name, kind in (
                ("sara", "person"),
                ("omar", "person"),
                ("pr-check", "service_account"),
            )
        }
        opened.flush()
        ids = {name: user.id for name, user in people.items()}

    asked = [
        ("sara", "mcp", "search", ARTICLE_5, NOON - timedelta(hours=3)),
        ("sara", "mcp", "search", ARTICLE_5, NOON - timedelta(hours=2)),
        ("sara", "mcp", "get_clause", ARTICLE_5, NOON - timedelta(hours=1)),
        ("sara", "mcp", "search", ARTICLE_5, NOON - timedelta(days=1)),
        ("omar", "dashboard", "search", ARTICLE_5, NOON - timedelta(hours=4)),
        ("omar", "dashboard", "get_clause", BROWSED, NOON - timedelta(hours=4)),
        ("pr-check", "api", "search", ARTICLE_6, NOON - timedelta(hours=5)),
        ("pr-check", "api", "search", ARTICLE_6, NOON - timedelta(hours=6)),
        ("pr-check", "api", "search", ARTICLE_6, NOON - timedelta(hours=7)),
        ("omar", "api", "get_clause", UNCHOSEN, NOON - timedelta(hours=2)),
    ]
    with session_from(owner) as opened:
        for who, surface, operation, key, when in asked:
            searched = operation == "search"
            entry = record_query(
                opened,
                user_id=ids[who],
                pat_id=None,
                surface=surface,
                operation=operation,
                status="ok",
                retention_days=365,
                query="how long can we keep it" if searched else "",
                target=None if searched else key,
                results=[first(key)],
                scope="selected" if searched else None,
            )
            opened.execute(
                update(QueryLogEntry).where(QueryLogEntry.id == entry).values(created_at=when)
            )
    yield owner
    owner.dispose()


def most_cited(owner: Engine, laws: list[str]) -> dict[str, int]:
    with session_from(owner) as opened:
        week = overview(opened, WEEK, laws=laws)
    return {item.name.key: item.count for item in week.most_cited}


def test_each_person_counts_once_a_day_however_often_they_ask(cited: Engine) -> None:
    """Sara's three today make one and yesterday's another; Omar's search from the
    dashboard counts, as any search does."""
    assert most_cited(cited, ["testlaw"])[ARTICLE_5] == 3


def test_a_service_account_counts_like_a_person(cited: Engine) -> None:
    assert most_cited(cited, ["testlaw"])[ARTICLE_6] == 1


def test_reading_a_clause_in_the_dashboard_is_not_citing_it(cited: Engine) -> None:
    assert BROWSED not in most_cited(cited, ["testlaw"])


def test_only_the_organisations_laws_are_listed(cited: Engine) -> None:
    assert UNCHOSEN not in most_cited(cited, ["testlaw"])
    assert most_cited(cited, ["testlaw", "bilingual"])[UNCHOSEN] == 1
    assert most_cited(cited, []) == {}


def test_a_clause_s_days_are_counted_the_same_way(cited: Engine) -> None:
    with session_from(cited) as opened:
        activity = clause_activity(opened, ARTICLE_5, WEEK)

    assert activity.total == 3
    assert [count for _, count in activity.by_day][-2:] == [1, 2]
