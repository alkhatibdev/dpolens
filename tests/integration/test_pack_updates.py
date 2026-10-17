"""A newer version of a law, loaded from its pack archive beside the version before it.

Which law is in force is what every citation rests on, so a new version arrives
only when somebody asks for it, is written to the governance log, and never
replaces the text an old citation quotes.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Iterator
from pathlib import Path

import click
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from typer.testing import CliRunner, Result

from dpolens.cli import pack as pack_commands
from dpolens.cli.main import app
from dpolens.engine.documents.models import Document, DocumentVersion
from dpolens.engine.documents.read import get_clause
from dpolens.engine.logs.governance import LAWS_PACK_LOADED, cli_actor
from dpolens.engine.logs.models import GovernanceEntry
from dpolens.engine.packs.archive import ArchiveError, sha256_of, write_archive
from dpolens.engine.packs.install import install_archive
from dpolens.engine.packs.load import OlderPack, load_pack
from dpolens.engine.packs.releases import PackRelease

pytestmark = pytest.mark.integration

LICENCE = Path(__file__).parents[2] / "packs" / "LICENSE"
FIXTURE = Path(__file__).parents[1] / "fixtures" / "packs" / "testlaw"
OLD_WORDING = "compliance with a legal\nobligation."
NEW_WORDING = "compliance with a legal\nobligation or for reasons of public interest."
runner = CliRunner()


def revised(folder: Path, version: str = "2026.2") -> Path:
    """The test law corrected without the law changing: the same date, one paragraph reworded."""
    copy = folder / "testlaw"
    shutil.copytree(FIXTURE, copy)
    pack_yaml = copy / "pack.yaml"
    pack_yaml.write_text(
        pack_yaml.read_text(encoding="utf-8").replace('version: "2026.1"', f'version: "{version}"'),
        encoding="utf-8",
    )
    article = copy / "testlaw" / "art-5.md"
    article.write_text(
        article.read_text(encoding="utf-8").replace(OLD_WORDING, NEW_WORDING), encoding="utf-8"
    )
    return copy


def pack_file(folder: Path, version: str = "2026.2") -> Path:
    return write_archive(revised(folder, version), LICENCE, folder / "dist", "testlaw", version)


def said(result: Result) -> str:
    return " ".join(click.unstyle(result.output).split())


def test_a_newer_version_is_stored_beside_the_one_before(
    session: Session, testlaw_pack: Path, tmp_path: Path
) -> None:
    load_pack(session, testlaw_pack)
    data = pack_file(tmp_path).read_bytes()

    result = install_archive(session, data, sha256_of(data), source="file", actor=cli_actor())
    session.commit()

    assert (result.version, result.already_loaded) == ("2026.2", False)
    labels = session.scalars(
        select(DocumentVersion.version_label)
        .join(Document)
        .where(Document.slug == "testlaw")
        .order_by(DocumentVersion.version_number)
    ).all()
    assert list(labels) == ["2026.1", "2026.2"]


def test_a_correction_dated_the_same_day_is_the_version_in_force(
    session: Session, testlaw_pack: Path, tmp_path: Path
) -> None:
    load_pack(session, testlaw_pack)
    data = pack_file(tmp_path).read_bytes()
    install_archive(session, data, sha256_of(data), source="file", actor=cli_actor())
    session.commit()

    clause = get_clause(session, "testlaw:art-5:para-2").clause

    assert clause.version_label == "2026.2"
    assert "for reasons of public interest" in clause.text


def test_the_load_is_logged_and_its_clauses_are_queued_for_embedding(
    session: Session, testlaw_pack: Path, tmp_path: Path
) -> None:
    load_pack(session, testlaw_pack)
    data = pack_file(tmp_path).read_bytes()

    result = install_archive(session, data, sha256_of(data), source="file", actor=cli_actor())
    session.commit()

    entry = session.scalars(
        select(GovernanceEntry)
        .where(GovernanceEntry.action == LAWS_PACK_LOADED)
        .order_by(GovernanceEntry.seq.desc())
        .limit(1)
    ).one()
    assert entry.target_id == "testlaw"
    assert entry.details["version"] == "2026.2"
    assert entry.details["source"] == "file"
    assert entry.details["sha256"] == sha256_of(data)
    queued = session.scalar(
        text(
            "SELECT count(*) FROM procrastinate_jobs "
            "WHERE task_name = 'dpolens.index_version' AND args->>'version_id' = ANY(:ids)"
        ),
        {"ids": [str(version_id) for version_id in result.version_ids]},
    )
    assert queued == 2


def test_an_update_records_the_repository_it_was_read_from(
    session: Session, testlaw_pack: Path, tmp_path: Path
) -> None:
    load_pack(session, testlaw_pack)
    data = pack_file(tmp_path).read_bytes()

    install_archive(
        session,
        data,
        sha256_of(data),
        source="update",
        actor=cli_actor(),
        expected=("testlaw", "2026.2"),
        repository="example/a-fork",
    )
    session.commit()

    entry = session.scalars(
        select(GovernanceEntry)
        .where(GovernanceEntry.action == LAWS_PACK_LOADED)
        .order_by(GovernanceEntry.seq.desc())
        .limit(1)
    ).one()
    assert (entry.details["source"], entry.details["repository"]) == ("update", "example/a-fork")


def test_an_older_version_than_the_one_loaded_is_refused(
    session: Session, testlaw_pack: Path, tmp_path: Path
) -> None:
    newer = revised(tmp_path, "2026.2")
    load_pack(session, newer)

    with pytest.raises(
        OlderPack, match=re.escape("has testlaw 2026.2, which is newer than 2026.1")
    ):
        load_pack(session, testlaw_pack)


def test_a_file_holding_another_version_than_its_release_names_is_refused(
    session: Session, tmp_path: Path
) -> None:
    data = pack_file(tmp_path).read_bytes()

    with pytest.raises(
        ArchiveError, match=re.escape("holds testlaw 2026.2, not the testlaw 2026.3")
    ):
        install_archive(
            session,
            data,
            sha256_of(data),
            source="update",
            actor=cli_actor(),
            expected=("testlaw", "2026.3"),
        )


# The commands, as an operator runs them.


@pytest.fixture
def instance(migrated: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("DPOLENS_DATABASE_URL", migrated)
    yield
    monkeypatch.delenv("DPOLENS_DATABASE_URL", raising=False)


@pytest.fixture
def has_testlaw(instance: None, clean_tables: None) -> None:
    result = runner.invoke(app, ["pack", "load", str(FIXTURE)])
    assert result.exit_code == 0, result.output


def test_starting_an_instance_leaves_a_loaded_law_alone(has_testlaw: None, tmp_path: Path) -> None:
    newer = revised(tmp_path)

    result = runner.invoke(app, ["pack", "load", "--unless-loaded", str(newer)])

    assert result.exit_code == 0, result.output
    assert "testlaw 2026.2 is in" in said(result)
    assert "this instance has 2026.1" in said(result)
    again = runner.invoke(app, ["pack", "load", "--unless-loaded", str(FIXTURE)])
    assert "testlaw 2026.1 is loaded" in said(again)


def test_a_pack_archive_imports_with_the_checksum_beside_it(
    has_testlaw: None, tmp_path: Path
) -> None:
    archive = pack_file(tmp_path)

    result = runner.invoke(app, ["pack", "import", str(archive)])

    assert result.exit_code == 0, result.output
    assert "Loaded testlaw 2026.2" in said(result)


def test_a_pack_archive_without_a_checksum_is_not_imported(
    has_testlaw: None, tmp_path: Path
) -> None:
    archive = pack_file(tmp_path)
    archive.with_name(f"{archive.name}.sha256").unlink()

    missing = runner.invoke(app, ["pack", "import", str(archive)])
    wrong = runner.invoke(app, ["pack", "import", str(archive), "--sha256", "0" * 64])

    assert missing.exit_code == 1
    assert "there is no checksum to check" in said(missing)
    assert wrong.exit_code == 1
    assert "changed or damaged on its way here" in said(wrong)


def test_update_lists_what_is_newer_and_loads_only_what_is_named(
    has_testlaw: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = pack_file(tmp_path)
    files = {
        "https://example.test/pack.tar.gz": archive.read_bytes(),
        "https://example.test/pack.tar.gz.sha256": archive.with_name(
            f"{archive.name}.sha256"
        ).read_bytes(),
    }
    published = PackRelease(
        slug="testlaw",
        version="2026.2",
        page="https://example.test/release",
        archive_url="https://example.test/pack.tar.gz",
        checksum_url="https://example.test/pack.tar.gz.sha256",
    )
    monkeypatch.setattr(pack_commands, "pack_releases", lambda repository: [published])
    monkeypatch.setattr(pack_commands, "fetch", files.__getitem__)

    listed = runner.invoke(app, ["pack", "update"])
    loaded = runner.invoke(app, ["pack", "update", "testlaw"])
    newest = runner.invoke(app, ["pack", "update", "testlaw"])

    assert "testlaw 2026.1: 2026.2 is published" in said(listed)
    assert loaded.exit_code == 0, loaded.output
    assert "Loaded testlaw 2026.2" in said(loaded)
    assert "testlaw 2026.2: nothing newer is published" in said(newest)
