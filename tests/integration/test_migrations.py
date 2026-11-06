"""Migrations go down as well as up, and the privileges they grant are real.

A downgrade that does not work is found while revising a migration, which is the
worst moment to find it. This runs the whole chain down to nothing and back, in a
database of its own.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.engine import make_url

from dpolens.engine.session import (
    WritableGovernanceLog,
    check_governance_privileges,
    governance_log_is_append_only,
)

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).parents[2]
DATABASE = "dpolens_migrations"
IDENTITY_TABLES = {"instance", "permissions", "roles", "role_permissions", "users", "user_roles"}


@pytest.fixture(scope="module")
def owner_url(database_url: str, app_role: str) -> Iterator[str]:
    """A throwaway database, because this test leaves nothing behind to share."""
    server = create_engine(database_url, isolation_level="AUTOCOMMIT")
    url = make_url(database_url).set(database=DATABASE).render_as_string(hide_password=False)
    try:
        with server.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{DATABASE}"'))
            connection.execute(text(f'CREATE DATABASE "{DATABASE}"'))
        yield url
        with server.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{DATABASE}" WITH (FORCE)'))
    finally:
        server.dispose()


def alembic(url: str, app_role: str) -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    config.attributes["app_role"] = app_role
    return config


def test_the_chain_goes_up_down_and_up_again(owner_url: str, app_role: str) -> None:
    config = alembic(owner_url, app_role)
    engine = create_engine(owner_url)

    try:
        command.upgrade(config, "head")
        assert set(inspect(engine).get_table_names()) >= IDENTITY_TABLES

        command.downgrade(config, "base")
        remaining = set(inspect(engine).get_table_names())
        assert not IDENTITY_TABLES & remaining
        assert "governance_log" not in remaining

        command.upgrade(config, "head")
        assert set(inspect(engine).get_table_names()) >= IDENTITY_TABLES
    finally:
        engine.dispose()


def test_the_second_upgrade_leaves_one_instance_row(owner_url: str, app_role: str) -> None:
    """The row is written by the migration, so a rebuild must not double it."""
    command.upgrade(alembic(owner_url, app_role), "head")
    engine = create_engine(owner_url)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM instance")).scalar_one() == 1
    finally:
        engine.dispose()


@pytest.fixture
def migrated_pair(
    owner_url: str, app_role: str, as_application: Callable[[str], str]
) -> Iterator[tuple[Engine, Engine]]:
    command.upgrade(alembic(owner_url, app_role), "head")
    owner = create_engine(owner_url)
    application = create_engine(as_application(owner_url))
    yield owner, application
    owner.dispose()
    application.dispose()


def test_the_check_tells_the_two_roles_apart(migrated_pair: tuple[Engine, Engine]) -> None:
    """The guarantee is checked at runtime, not inferred from a migration run."""
    owner, application = migrated_pair

    assert governance_log_is_append_only(application) is True
    check_governance_privileges(application)

    assert governance_log_is_append_only(owner) is False
    with pytest.raises(WritableGovernanceLog, match="append-only"):
        check_governance_privileges(owner)


def test_a_table_added_later_is_reachable_by_the_application_role(
    migrated_pair: tuple[Engine, Engine],
) -> None:
    """Default privileges, so a later migration does not have to remember."""
    owner, application = migrated_pair
    with owner.begin() as connection:
        connection.execute(text("CREATE TABLE later_table (id integer)"))

    try:
        with application.connect() as connection:
            connection.execute(text("SELECT * FROM later_table"))
    finally:
        with owner.begin() as connection:
            connection.execute(text("DROP TABLE later_table"))


def test_0019_names_what_was_stored_before(owner_url: str, app_role: str) -> None:
    """A law keeps its name and title, in English as they were written, until its pack loads
    again, and a policy keeps its title, in the language of its text."""
    config = alembic(owner_url, app_role)
    engine = create_engine(owner_url)
    try:
        command.downgrade(config, "base")
        command.upgrade(config, "0018")
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO packs (id, slug, name, jurisdiction, version, effective_date,
                                       trust_tier, source_url, license, authoritative_language)
                    VALUES ('00000000-0000-0000-0000-000000000001', 'uae-pdpl',
                            'Federal Decree by Law No. (45) of 2021', 'United Arab Emirates',
                            '2026.1', '2022-01-02', 'community', 'https://example.invalid',
                            'Not protected by copyright.', 'ar');
                    INSERT INTO documents (id, kind, slug, title, status, pack_id)
                    VALUES ('00000000-0000-0000-0000-000000000002', 'law', 'uae-pdpl',
                            'Federal Decree by Law No. (45) of 2021', 'active',
                            '00000000-0000-0000-0000-000000000001'),
                           ('00000000-0000-0000-0000-000000000003', 'org_policy', 'retention',
                            'سياسة الاحتفاظ', 'active', NULL);
                    INSERT INTO document_versions (id, document_id, version_number, status,
                                                   effective_date, source_ref)
                    VALUES ('00000000-0000-0000-0000-000000000004',
                            '00000000-0000-0000-0000-000000000003', 1, 'draft', '2026-01-01',
                            'upload:retention');
                    INSERT INTO document_nodes (id, document_version_id, canonical_key,
                                                node_type, is_normative, order_index, depth)
                    VALUES ('00000000-0000-0000-0000-000000000005',
                            '00000000-0000-0000-0000-000000000004', 'retention:1', 'section',
                            true, 0, 0);
                    INSERT INTO node_texts (id, node_id, lang, is_authoritative,
                                            translation_status, body_text)
                    VALUES ('00000000-0000-0000-0000-000000000006',
                            '00000000-0000-0000-0000-000000000005', 'ar', true, 'original',
                            'تحفظ البيانات ثلاثين يوما.');
                    """
                )
            )

        command.upgrade(config, "head")

        with engine.connect() as connection:
            names = [
                tuple(row)
                for row in connection.execute(
                    text("SELECT lang, name, short_name, jurisdiction FROM pack_names")
                )
            ]
            titles: dict[str, str] = {
                slug: title
                for slug, title in connection.execute(
                    text(
                        "SELECT d.slug, t.lang || ': ' || t.title FROM document_titles t "
                        "JOIN documents d ON d.id = t.document_id"
                    )
                )
            }
        assert names == [
            ("en", "Federal Decree by Law No. (45) of 2021", "UAE PDPL", "United Arab Emirates")
        ]
        assert titles == {
            "uae-pdpl": "en: Federal Decree by Law No. (45) of 2021",
            "retention": "ar: سياسة الاحتفاظ",
        }
    finally:
        engine.dispose()
