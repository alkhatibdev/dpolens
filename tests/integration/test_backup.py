"""A backup restored into an instance that holds nothing yet is the instance it was taken from.

The scripts in `deploy/backup` run the way Compose runs them: in the database's own image, as
root, beside the server. One database is filled the way an instance fills itself and backed up,
then restored into a new database, which must hold the same governance log, still verifying and
still closed to the application role, the same people and questions, a keyword index that
answers, and every original file the database points at.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer

from dpolens.engine.auth.catalog import bootstrap
from dpolens.engine.auth.permissions import ADMIN
from dpolens.engine.auth.users import create_user
from dpolens.engine.documents.models import DocumentVersion
from dpolens.engine.logs.governance import Actor, verify
from dpolens.engine.logs.queries import record_query
from dpolens.engine.originals import Directory, Stored
from dpolens.engine.packs.load import load_pack
from dpolens.engine.policies.store import upload_policy
from dpolens.engine.search import keyword_search
from dpolens.engine.session import session_from

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).parents[2]
SCRIPTS = REPO_ROOT / "deploy" / "backup"
POSTGRES_IMAGE = "dpolens-postgres:test"
TESTLAW = Path(__file__).parents[1] / "fixtures" / "packs" / "testlaw"
POLICIES = Path(__file__).parents[1] / "fixtures" / "policies"
ACTOR = Actor(via="cli", identity={"os_user": "tests", "host": "ci"})
SOURCE = "dpolens_backup_source"
NAME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{6}Z$")
COUNTED = ("users", "documents", "document_versions", "query_log_entries", "governance_log")


def run(
    postgres: PostgresContainer,
    script: str,
    *arguments: str,
    database: str,
    originals: Path,
    backups: Path,
    **environment: str,
) -> tuple[int, str]:
    """Run `backup.sh` or `restore.sh` in the database's image, sharing the server's network."""
    restoring = script == "restore.sh"
    container = (
        DockerContainer(POSTGRES_IMAGE)
        .with_kwargs(
            entrypoint=["sh", f"/opt/dpolens/backup/{script}"],
            network_mode=f"container:{postgres.get_wrapped_container().id}",
        )
        .with_command(" ".join(arguments))
        .with_envs(
            PGHOST="127.0.0.1",
            PGPORT="5432",
            PGUSER=postgres.username,
            PGPASSWORD=postgres.password,
            PGDATABASE=database,
            DPOLENS_VERSION="0.0.0-test",
            **environment,
        )
        .with_volume_mapping(str(SCRIPTS), "/opt/dpolens/backup", "ro")
        .with_volume_mapping(
            str(originals), "/var/lib/dpolens/originals", "rw" if restoring else "ro"
        )
        .with_volume_mapping(str(backups), "/backups", "ro" if restoring else "rw")
    )
    container.start()
    try:
        status: int = container.get_wrapped_container().wait(timeout=120)["StatusCode"]
        out, err = container.get_logs()
    finally:
        container.stop()
    return status, (out + err).decode()


def counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in COUNTED
        }


@dataclass(frozen=True)
class Instance:
    database: str
    app: Engine
    originals: Path


@pytest.fixture(scope="module")
def empty_database(database_url: str) -> Callable[[str], str]:
    """A database with nothing in it, the way a new volume's is."""

    def make(name: str) -> str:
        server = create_engine(database_url, isolation_level="AUTOCOMMIT")
        try:
            with server.connect() as connection:
                connection.execute(text(f'CREATE DATABASE "{name}"'))
        finally:
            server.dispose()
        return name

    return make


@pytest.fixture(scope="module")
def source(
    database_of_its_own: Callable[[str], tuple[str, str]],
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[Instance]:
    """An instance with a law, a person, a published policy's original and a question."""
    app_url, owner_url = database_of_its_own(SOURCE)
    originals = tmp_path_factory.mktemp("source-originals")

    owner = create_engine(owner_url)
    with session_from(owner) as session:
        load_pack(session, TESTLAW)
    owner.dispose()

    app = create_engine(app_url)
    with session_from(app) as session:
        bootstrap(session, actor=ACTOR)
        dpo = create_user(
            session, email="dpo@example.com", display_name="The DPO", actor=ACTOR, roles=(ADMIN,)
        )
        session.flush()
        upload_policy(
            session,
            Directory(originals),
            (POLICIES / "retention-v1.md").read_bytes(),
            "retention-v1.md",
            actor=ACTOR,
            slug="retention",
            effective_date=date(2026, 1, 1),
        )
        record_query(
            session,
            user_id=dpo.id,
            pat_id=None,
            surface="mcp",
            operation="search",
            status="ok",
            query="how long do we keep staff records",
            scope="selected",
        )
    yield Instance(SOURCE, app, originals)
    app.dispose()


@pytest.fixture(scope="module")
def backed_up(
    postgres: PostgresContainer, source: Instance, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, str]:
    backups = tmp_path_factory.mktemp("backups")
    status, output = run(
        postgres,
        "backup.sh",
        database=source.database,
        originals=source.originals,
        backups=backups,
        DPOLENS_QUERY_LOG_RETENTION_DAYS="30",
    )
    assert status == 0, output
    [folder] = backups.iterdir()
    return folder, output


@pytest.fixture(scope="module")
def restored(
    postgres: PostgresContainer,
    database_url: str,
    as_application: Callable[[str], str],
    empty_database: Callable[[str], str],
    backed_up: tuple[Path, str],
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[Instance]:
    folder, _ = backed_up
    database = empty_database("dpolens_backup_restored")
    originals = tmp_path_factory.mktemp("restored-originals")
    status, output = run(
        postgres,
        "restore.sh",
        folder.name,
        database=database,
        originals=originals,
        backups=folder.parent,
    )
    assert status == 0, output
    url = make_url(database_url).set(database=database).render_as_string(hide_password=False)
    app = create_engine(as_application(url))
    yield Instance(database, app, originals)
    app.dispose()


class TestABackup:
    def test_is_one_folder_named_for_when_it_was_taken(self, backed_up: tuple[Path, str]) -> None:
        folder, _ = backed_up

        assert NAME.match(folder.name)
        assert {path.name for path in folder.iterdir()} == {
            "database.dump",
            "originals.tar",
            "SHA256SUMS",
            "backup.json",
        }

    def test_says_what_it_holds(self, backed_up: tuple[Path, str], source: Instance) -> None:
        folder, output = backed_up
        described = json.loads((folder / "backup.json").read_text(encoding="utf-8"))
        with source.app.connect() as connection:
            schema = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()

        assert described["dpolens"] == "0.0.0-test"
        assert described["schema"] == schema
        assert (described["originals"], described["questions"]) == (1, 1)
        assert "with 1 question, and 1 original file." in output

    def test_says_its_questions_outlive_the_retention(self, backed_up: tuple[Path, str]) -> None:
        _, output = backed_up

        assert "deletes a question 30 days after it was asked" in output
        assert "keeps the questions in it for as long as the backup is kept" in output


class TestARestore:
    def test_brings_back_every_row_that_was_counted(
        self, source: Instance, restored: Instance
    ) -> None:
        assert counts(restored.app) == counts(source.app)

    def test_brings_back_a_governance_log_that_verifies(
        self, source: Instance, restored: Instance
    ) -> None:
        with session_from(source.app) as session:
            before = verify(session)
        with session_from(restored.app) as session:
            after = verify(session)

        assert after.ok
        assert after.entries == before.entries > 0

    def test_keeps_the_governance_log_closed_to_the_application_role(
        self, restored: Instance
    ) -> None:
        with restored.app.connect() as connection, pytest.raises(ProgrammingError) as refused:
            connection.execute(text("UPDATE governance_log SET action = action"))

        assert "permission denied" in str(refused.value)

    def test_brings_back_a_keyword_index_that_answers(
        self, source: Instance, restored: Instance
    ) -> None:
        def found(engine: Engine) -> list[str]:
            with session_from(engine) as session:
                return [hit.key for hit in keyword_search(session, "erase personal data")]

        assert found(restored.app)[0] == "testlaw:art-5"
        assert found(restored.app) == found(source.app)

    def test_brings_back_every_original_by_its_hash(self, restored: Instance) -> None:
        kept = []
        with session_from(restored.app) as session:
            for version in session.scalars(
                select(DocumentVersion).where(DocumentVersion.source_key.is_not(None))
            ):
                assert version.source_key and version.source_size and version.source_sha256
                kept.append(Stored(version.source_key, version.source_size, version.source_sha256))

        assert len(kept) == 1
        for stored in kept:
            Directory(restored.originals).get(stored)

    def test_is_refused_by_an_instance_that_holds_data(
        self, postgres: PostgresContainer, source: Instance, backed_up: tuple[Path, str]
    ) -> None:
        folder, _ = backed_up
        before = counts(source.app)

        status, output = run(
            postgres,
            "restore.sh",
            folder.name,
            database=source.database,
            originals=source.originals,
            backups=folder.parent,
        )

        assert status != 0
        assert "already holds data" in output
        assert "docker compose down -v" in output
        assert counts(source.app) == before

    def test_of_a_changed_backup_loads_nothing(
        self,
        postgres: PostgresContainer,
        database_url: str,
        empty_database: Callable[[str], str],
        backed_up: tuple[Path, str],
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        folder, _ = backed_up
        changed = tmp_path_factory.mktemp("changed") / folder.name
        shutil.copytree(folder, changed)
        with (changed / "originals.tar").open("r+b") as archive:
            archive.seek(100)
            archive.write(b"!")
        database = empty_database("dpolens_backup_changed")

        status, output = run(
            postgres,
            "restore.sh",
            changed.name,
            database=database,
            originals=tmp_path_factory.mktemp("changed-originals"),
            backups=changed.parent,
        )

        assert status != 0
        assert "has changed since it was written" in output
        url = make_url(database_url).set(database=database)
        engine = create_engine(url)
        try:
            with engine.connect() as connection:
                tables = connection.execute(
                    text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
                ).scalar_one()
        finally:
            engine.dispose()
        assert tables == 0


class TestKeepingBackups:
    def test_deletes_the_oldest_whole_backups_and_nothing_else(
        self,
        postgres: PostgresContainer,
        source: Instance,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        backups = tmp_path_factory.mktemp("kept")
        for old in ("2026-01-01T000000Z", "2026-01-02T000000Z"):
            (backups / old).mkdir()
            (backups / old / "backup.json").write_text("{}", encoding="utf-8")
        (backups / "2026-01-03T000000Z").mkdir()  # no backup.json: not a whole backup
        (backups / "notes.txt").write_text("the operator's own", encoding="utf-8")

        status, output = run(
            postgres,
            "backup.sh",
            database=source.database,
            originals=source.originals,
            backups=backups,
            DPOLENS_BACKUP_KEEP="2",
        )

        assert status == 0, output
        left = sorted(path.name for path in backups.iterdir())
        assert left[:3] == ["2026-01-02T000000Z", "2026-01-03T000000Z", left[2]]
        assert NAME.match(left[2]) and left[2] > "2026-01-03T000000Z"
        assert left[3:] == ["notes.txt"]
        assert "Deleted the older backup ./backups/2026-01-01T000000Z." in output

    def test_is_a_number_from_one(
        self,
        postgres: PostgresContainer,
        source: Instance,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> None:
        backups = tmp_path_factory.mktemp("refused")

        status, output = run(
            postgres,
            "backup.sh",
            database=source.database,
            originals=source.originals,
            backups=backups,
            DPOLENS_BACKUP_KEEP="0",
        )

        assert status != 0
        assert "DPOLENS_BACKUP_KEEP is how many backups to keep" in output
        assert list(backups.iterdir()) == []
