"""The guarantees the governance log makes, tested against the database that keeps them.

Application code could promise append-only. These tests prove the promise
survives code that never asked, and an operator with psql.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from dpolens.engine.auth.catalog import bootstrap
from dpolens.engine.auth.users import create_user
from dpolens.engine.instance import instance_id
from dpolens.engine.logs.governance import (
    HASH_VERSION,
    Actor,
    canonical_json,
    cli_actor,
    genesis_hash,
    read_entries,
    record,
    verify,
)
from dpolens.engine.logs.models import GovernanceEntry

pytestmark = pytest.mark.integration

ACTOR = Actor(via="cli", identity={"os_user": "tests", "host": "ci"})


@pytest.fixture
def ready(session: Session) -> Session:
    bootstrap(session, actor=ACTOR)
    session.flush()
    return session


def test_the_chain_starts_at_this_instances_genesis(ready: Session) -> None:
    """Which is what stops one instance's chain being presented as another's."""
    rows = read_entries(ready)
    assert rows
    assert rows[0].prev_hash == genesis_hash(ready)
    assert rows[0].seq == min(row.seq for row in rows)


def test_a_written_chain_verifies(ready: Session) -> None:
    for number in range(3):
        record(
            ready,
            actor=ACTOR,
            action="documents.published",
            target_type="document_version",
            target_id=f"testlaw:v{number}",
        )
    ready.flush()

    report = verify(ready)
    assert report.ok
    assert report.reason is None


def test_each_entry_links_to_the_one_before_it(ready: Session) -> None:
    first = record(ready, actor=ACTOR, action="a", target_type="t", target_id="1")
    second = record(ready, actor=ACTOR, action="b", target_type="t", target_id="2")
    ready.flush()

    rows = {row.seq: row for row in read_entries(ready)}
    assert rows[second].prev_hash == rows[first].entry_hash


def test_the_stored_details_are_the_exact_text_that_was_hashed(ready: Session) -> None:
    """The reason the column is `json` and not `jsonb`.

    `jsonb` would reorder the keys, and the hash covers the text, so the chain
    would break on rows nobody had touched.
    """
    seq = record(
        ready,
        actor=ACTOR,
        action="role.permissions_changed",
        target_type="role",
        target_id="DPO",
        details={"zebra": 1, "apple": 2},
    )
    ready.flush()

    stored = ready.execute(
        text("SELECT details::text FROM governance_log WHERE seq = :seq"), {"seq": seq}
    ).scalar_one()

    assert stored == canonical_json({"zebra": 1, "apple": 2, "via": "cli", "actor": ACTOR.identity})
    assert stored.index('"zebra"') < stored.index('"apple"')


def test_a_cli_action_names_no_person(ready: Session) -> None:
    """An operator holding the database URL is outside the identity system."""
    seq = record(
        ready, actor=cli_actor(), action="user.created", target_type="user", target_id="someone"
    )
    ready.flush()

    row = ready.get_one(GovernanceEntry, seq)
    assert row.actor_user_id is None
    assert row.details["via"] == "cli"
    assert set(row.details["actor"]) == {"os_user", "host"}


def test_an_api_action_names_the_user(ready: Session, unique: str) -> None:
    user = create_user(ready, email=f"dpo-{unique}@example.com", display_name="A DPO", actor=ACTOR)
    ready.flush()
    seq = record(
        ready,
        actor=Actor(user_id=user.id, via="api"),
        action="documents.published",
        target_type="document_version",
        target_id="testlaw:v1",
    )
    ready.flush()

    row = ready.get_one(GovernanceEntry, seq)
    assert row.actor_user_id == user.id
    assert row.details == {"via": "api"}


def test_the_recipe_version_is_recorded_on_every_row(ready: Session) -> None:
    """So a future recipe can be told apart from this one rather than guessed at."""
    seq = record(ready, actor=ACTOR, action="a", target_type="t", target_id="1")
    ready.flush()

    assert ready.get_one(GovernanceEntry, seq).hash_version == HASH_VERSION


class TestNothingCanChangeIt:
    def test_the_owner_cannot_update_a_row(self, ready: Session) -> None:
        """The trigger refuses for everybody, not only for the application role."""
        seq = record(ready, actor=ACTOR, action="a", target_type="t", target_id="1")
        ready.flush()

        with pytest.raises(DBAPIError, match="append-only"):
            ready.execute(
                text("UPDATE governance_log SET action = 'b' WHERE seq = :seq"), {"seq": seq}
            )
        ready.rollback()

    def test_the_owner_cannot_delete_a_row(self, ready: Session) -> None:
        seq = record(ready, actor=ACTOR, action="a", target_type="t", target_id="1")
        ready.flush()

        with pytest.raises(DBAPIError, match="append-only"):
            ready.execute(text("DELETE FROM governance_log WHERE seq = :seq"), {"seq": seq})
        ready.rollback()

    def test_the_table_cannot_be_truncated(self, ready: Session) -> None:
        """A row trigger never sees TRUNCATE, which is why there is a second one.

        Without it the entire log would go in one statement that every row-level
        guard would miss.
        """
        with pytest.raises(DBAPIError, match="append-only"):
            ready.execute(text("TRUNCATE governance_log"))
        ready.rollback()

    def test_the_application_role_has_no_update_privilege(self, app_engine: Engine) -> None:
        """The privilege is absent, so the trigger is not the only thing in the way."""
        with Session(app_engine) as session:
            granted = session.execute(
                text("SELECT has_table_privilege(current_user, 'governance_log', :privilege)"),
                {"privilege": "UPDATE"},
            ).scalar_one()
            assert granted is False

            for privilege in ("DELETE", "TRUNCATE"):
                assert (
                    session.execute(
                        text(
                            "SELECT has_table_privilege(current_user, 'governance_log', :privilege)"
                        ),
                        {"privilege": privilege},
                    ).scalar_one()
                    is False
                )

    def test_the_application_role_can_append_and_read(self, app_engine: Engine) -> None:
        """What the application actually needs, so the revoke did not overreach."""
        with Session(app_engine) as session:
            for privilege in ("INSERT", "SELECT"):
                assert (
                    session.execute(
                        text(
                            "SELECT has_table_privilege(current_user, 'governance_log', :privilege)"
                        ),
                        {"privilege": privilege},
                    ).scalar_one()
                    is True
                )

            bootstrap(session, actor=ACTOR)
            seq = record(
                session, actor=ACTOR, action="a", target_type="t", target_id="from-the-app-role"
            )
            assert seq > 0
            session.rollback()


class TestVerifyCatchesTampering:
    def test_an_edited_row_is_found_and_named(self, ready: Session) -> None:
        """What the verify command is for.

        The triggers have to be disabled to make this happen at all, which takes
        ownership of the table. That is the point: tampering is not something the
        application can do, and when somebody with the keys does it, the chain
        still says so.
        """
        seq = record(
            ready,
            actor=ACTOR,
            action="user.role_granted",
            target_type="user",
            target_id="somebody",
            details={"role": "Developer"},
        )
        ready.flush()
        assert verify(ready).ok

        ready.execute(text("ALTER TABLE governance_log DISABLE TRIGGER USER"))
        ready.execute(
            text("UPDATE governance_log SET details = :details WHERE seq = :seq"),
            {"details": json.dumps({"role": "Admin", "via": "cli"}), "seq": seq},
        )
        ready.execute(text("ALTER TABLE governance_log ENABLE TRIGGER USER"))

        report = verify(ready)
        assert not report.ok
        assert report.first_broken_seq == seq
        ready.rollback()

    def test_a_deleted_row_is_found(self, ready: Session) -> None:
        record(ready, actor=ACTOR, action="a", target_type="t", target_id="1")
        middle = record(ready, actor=ACTOR, action="b", target_type="t", target_id="2")
        record(ready, actor=ACTOR, action="c", target_type="t", target_id="3")
        ready.flush()

        ready.execute(text("ALTER TABLE governance_log DISABLE TRIGGER USER"))
        ready.execute(text("DELETE FROM governance_log WHERE seq = :seq"), {"seq": middle})
        ready.execute(text("ALTER TABLE governance_log ENABLE TRIGGER USER"))

        report = verify(ready)
        assert not report.ok
        assert report.reason is not None
        assert "link" in report.reason
        ready.rollback()


def test_two_writers_cannot_append_at_the_same_time(app_engine: Engine, engine: Engine) -> None:
    """The advisory lock is what keeps the chain linear.

    Without it, two transactions read the same last entry and write two rows
    claiming the same predecessor, which is a fork rather than a chain. Neither
    transaction commits here, so the log is left as it was found.
    """
    with Session(engine) as first, Session(app_engine) as second:
        bootstrap(first, actor=ACTOR)
        record(first, actor=ACTOR, action="a", target_type="t", target_id="first")
        first.flush()

        second.execute(text("SET LOCAL lock_timeout = '300ms'"))
        with pytest.raises(DBAPIError) as raised:
            record(second, actor=ACTOR, action="b", target_type="t", target_id="second")
        assert "lock" in str(raised.value).lower()
        second.rollback()

        first.rollback()

        # With the first transaction finished, the same write goes through.
        second.execute(text("SET LOCAL lock_timeout = '300ms'"))
        assert record(second, actor=ACTOR, action="b", target_type="t", target_id="second") > 0
        second.rollback()


def test_an_erased_user_leaves_the_chain_verifiable(ready: Session, unique: str) -> None:
    """Why the hash covers ids and never emails.

    An erasure request has to be able to succeed without destroying the evidence
    that somebody acted.
    """
    user = create_user(
        ready, email=f"leaver-{unique}@example.com", display_name="Leaver", actor=ACTOR
    )
    ready.flush()
    record(
        ready,
        actor=Actor(user_id=user.id, via="api"),
        action="documents.published",
        target_type="document_version",
        target_id="testlaw:v1",
    )
    ready.flush()

    user.status = "erased"
    user.email = f"erased-{user.id}@invalid"
    user.display_name = "erased"
    ready.flush()

    assert verify(ready).ok
    assert ready.scalars(
        select(GovernanceEntry.seq).where(GovernanceEntry.actor_user_id == user.id)
    ).all()


def test_the_instance_row_is_the_only_one(ready: Session) -> None:
    """Because the genesis value depends on there being exactly one."""
    identifier = instance_id(ready)
    with pytest.raises(IntegrityError):
        ready.execute(text("INSERT INTO instance (id, singleton) VALUES (gen_random_uuid(), true)"))
    ready.rollback()
    assert instance_id(ready) == identifier
