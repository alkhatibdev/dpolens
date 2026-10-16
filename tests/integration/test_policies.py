"""A policy's life: uploaded as a draft, reviewed, published, searched, versioned, archived.

In a database of its own, as the application role, with originals in a temporary folder. The
two retention files tell one story: version 2 inserts a contractor rule at 4.2, so the staff
rule is printed as 4.3, and a citation of version 1's 4.2 must still say where the staff rule
went.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.orm import Session

from dpolens.engine import jobs
from dpolens.engine.documents.models import DocumentVersion
from dpolens.engine.documents.read import ClauseNotFound, get_clause, list_documents
from dpolens.engine.logs.governance import Actor
from dpolens.engine.logs.models import GovernanceEntry
from dpolens.engine.originals import Directory, OriginalUnavailable
from dpolens.engine.policies.blocks import UnreadablePolicy
from dpolens.engine.policies.store import (
    SAMPLE_SLUG,
    DraftExists,
    EffectiveDateTooEarly,
    FlagsOpen,
    LabelTaken,
    NoDraft,
    PolicyExists,
    accept_flags,
    archive,
    discard,
    edit_draft,
    list_policies,
    load_sample,
    original,
    publish,
    read_draft,
    upload_policy,
    upload_version,
)
from dpolens.engine.search.engine import search
from dpolens.engine.session import session_from
from dpolens.settings import Settings

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parents[1] / "fixtures" / "policies"
ACTOR = Actor(via="cli", identity={"os_user": "tests", "host": "ci"})
FIRST = date(2026, 1, 1)
SECOND = date(2026, 6, 1)


@pytest.fixture(scope="module")
def own(database_of_its_own: Callable[[str], tuple[str, str]]) -> Iterator[Engine]:
    app_url, _ = database_of_its_own("dpolens_policies")
    engine = create_engine(app_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def originals(tmp_path_factory: pytest.TempPathFactory) -> Directory:
    return Directory(tmp_path_factory.mktemp("originals"))


@pytest.fixture(scope="module")
def worker(own: Engine, originals: Directory) -> Iterator[jobs.Runtime]:
    """The worker's jobs, run in this process rather than by a worker polling the queue."""
    settings = Settings.model_validate(
        {
            "database_url": str(own.url.render_as_string(hide_password=False)),
            "originals_dir": str(originals.root),
        }
    )
    runtime = jobs.Runtime(settings=settings, engine=own)
    jobs.running.append(runtime)
    yield runtime
    jobs.running.remove(runtime)
    for loaded in runtime.loaded:
        loaded.close()


def upload_v1(own: Engine, originals: Directory) -> None:
    with session_from(own) as session:
        upload_policy(
            session,
            originals,
            (FIXTURES / "retention-v1.md").read_bytes(),
            "retention-v1.md",
            actor=ACTOR,
            slug="retention",
            effective_date=FIRST,
        )


def entries(own: Engine, action: str) -> list[GovernanceEntry]:
    with session_from(own) as session:
        found = list(
            session.scalars(select(GovernanceEntry).where(GovernanceEntry.action == action))
        )
        session.expunge_all()
        return found


class TestFirstVersion:
    def test_an_upload_is_a_draft_that_nothing_can_find(
        self, own: Engine, originals: Directory
    ) -> None:
        upload_v1(own, originals)

        with session_from(own) as session:
            draft = read_draft(session, "retention")
            assert draft.version.status == "draft"
            assert [c.key for c in draft.clauses] == ["retention:4", "retention:5"]
            assert [c.key for c in draft.clauses[0].children] == [
                "retention:4.1",
                "retention:4.2",
                "retention:4.3",
            ]
            with pytest.raises(ClauseNotFound):
                get_clause(session, "retention:4.2", as_of=FIRST)
        assert entries(own, "document.drafted")[-1].details["document"] == "retention"

    def test_a_second_new_policy_with_the_same_slug_is_refused(
        self, own: Engine, originals: Directory
    ) -> None:
        with session_from(own) as session, pytest.raises(PolicyExists):
            upload_policy(
                session,
                originals,
                b"# Other\n\nText here.\n",
                "x.md",
                actor=ACTOR,
                slug="retention",
            )

    def test_an_unreadable_file_is_refused_before_anything_is_kept(
        self, own: Engine, originals: Directory
    ) -> None:
        with session_from(own) as session, pytest.raises(UnreadablePolicy):
            upload_policy(session, originals, b"%PDF-1.7", "scan.pdf", actor=ACTOR, slug="scan")
        with session_from(own) as session:
            assert "scan" not in [p.slug for p in list_policies(session)]

    def test_publishing_waits_for_every_flag(self, own: Engine, originals: Directory) -> None:
        with session_from(own) as session:
            upload_policy(
                session,
                originals,
                (FIXTURES / "heading-styles.docx").read_bytes(),
                "heading-styles.docx",
                actor=ACTOR,
                slug="council-data",
            )
        with session_from(own) as session, pytest.raises(FlagsOpen) as refused:
            publish(session, "council-data", actor=ACTOR)
        assert refused.value.positions == [1]

        with session_from(own) as session:
            accepted = accept_flags(session, "council-data", [1], actor=ACTOR)
        assert accepted.flags[0].accepted_by == "the command line"
        with session_from(own) as session:
            published = publish(session, "council-data", actor=ACTOR)
        assert published.status == "published"
        assert published.label == "1"
        assert entries(own, "document.flag_accepted")[-1].details["flags"][0]["position"] == 1

    def test_a_published_version_is_queued_to_embed_and_then_searched(
        self, own: Engine, worker: jobs.Runtime
    ) -> None:
        with session_from(own) as session:
            version = publish(session, "retention", actor=ACTOR)
            assert version.indexing == "todo"
            job = session.scalar(
                select(DocumentVersion.index_job_id).where(DocumentVersion.version_label == "1")
            )
        assert job is not None

        embedded = jobs.index_version(version_id="any")
        assert embedded > 0

        with session_from(own) as session:
            results = search(session, worker.embedder(), "how long do we keep staff records")
            assert results[0].clause.key == "retention:4.2"
            assert results[0].clause.document_title == "Retention policy"

    def test_the_original_file_is_kept_and_checked(self, own: Engine, originals: Directory) -> None:
        with session_from(own) as session:
            data, name, form = original(session, originals, "retention", 1)
        assert data == (FIXTURES / "retention-v1.md").read_bytes()
        assert (name, form) == ("retention-v1.md", "markdown")

        with session_from(own) as session:
            key = session.scalar(
                select(DocumentVersion.source_key).where(
                    DocumentVersion.source_name == "retention-v1.md"
                )
            )
        assert key is not None
        path = originals.path(key)
        kept = path.read_bytes()
        path.write_bytes(kept + b"tampered")
        try:
            with session_from(own) as session, pytest.raises(OriginalUnavailable):
                original(session, originals, "retention", 1)
        finally:
            path.write_bytes(kept)


class TestSecondVersion:
    def test_a_new_version_is_matched_to_the_one_before(
        self, own: Engine, originals: Directory
    ) -> None:
        with session_from(own) as session:
            draft = upload_version(
                session,
                originals,
                "retention",
                (FIXTURES / "retention-v2.md").read_bytes(),
                "retention-v2.md",
                actor=ACTOR,
                effective_date=SECOND,
            )

        retention = {c.key: c for c in draft.clauses[0].children}
        assert (retention["retention:4.1"].change, retention["retention:4.1"].continues) == (
            "unchanged",
            "retention:4.1",
        )
        assert retention["retention:4.2"].change == "added"
        assert (retention["retention:4.3"].change, retention["retention:4.3"].continues) == (
            "moved",
            "retention:4.2",
        )
        assert retention["retention:4.4"].continues == "retention:4.3"
        assert draft.changes == {
            "added": 1,
            "modified": 1,
            "moved": 2,
            "unchanged": 3,
            "removed": 0,
        }
        assert [(flag.key, flag.kind) for flag in draft.flags] == [
            ("retention:4.2", "unmatched_key"),
            ("retention:4.3", "unmatched_key"),
            ("retention:4.4", "unmatched_key"),
            ("retention:5.1", "unmatched_key"),
        ]
        assert "4.3 continues 4.2 from version 1" in draft.flags[1].detail
        assert "In version 1, 4.3 was a different rule (Supplier records" in draft.flags[1].detail
        assert "renumbered and reworded" in draft.flags[2].detail
        assert draft.flags[3].detail == (
            "5.1 has new words since version 1, where it read: This policy is reviewed every "
            "year. Check that it is still the same rule."
        )

    def test_one_draft_at_a_time_unless_it_is_replaced(
        self, own: Engine, originals: Directory
    ) -> None:
        upload = (FIXTURES / "retention-v2.md").read_bytes()
        with session_from(own) as session, pytest.raises(DraftExists):
            upload_version(session, originals, "retention", upload, "retention-v2.md", actor=ACTOR)
        with session_from(own) as session:
            upload_version(
                session,
                originals,
                "retention",
                upload,
                "retention-v2.md",
                actor=ACTOR,
                effective_date=SECOND,
                replace=True,
            )
        assert entries(own, "document.draft_discarded")[-1].details["reason"] == (
            "replaced by a new upload"
        )

    def test_a_new_version_takes_effect_after_the_one_before(self, own: Engine) -> None:
        """Otherwise the version a citation names and the version in force could disagree."""
        with session_from(own) as session:
            accept_flags(session, "retention", None, actor=ACTOR)
        for too_early in (FIRST, date(2025, 12, 1)):
            with session_from(own) as session:
                edit_draft(session, "retention", effective_date=too_early, actor=ACTOR)
            with session_from(own) as session, pytest.raises(EffectiveDateTooEarly):
                publish(session, "retention", actor=ACTOR)

    def test_a_label_names_one_version(self, own: Engine) -> None:
        with session_from(own) as session:
            edit_draft(session, "retention", effective_date=SECOND, version_label="1", actor=ACTOR)
        with session_from(own) as session, pytest.raises(LabelTaken):
            publish(session, "retention", actor=ACTOR)
        with session_from(own) as session:
            edit_draft(session, "retention", version_label="", actor=ACTOR)
            assert publish(session, "retention", actor=ACTOR).label == "2"

    def test_a_number_now_naming_another_rule_says_so(self, own: Engine) -> None:
        with session_from(own) as session:
            today = get_clause(session, "retention:4.2", as_of=SECOND)

        assert today.clause.text.startswith("Contractor records")
        assert today.formerly is not None
        assert today.formerly.version_label == "1"
        assert today.formerly.text.startswith("Staff records")
        assert today.formerly.now == "retention:4.3"

    def test_an_old_citation_says_where_its_rule_went(self, own: Engine) -> None:
        with session_from(own) as session:
            cited = get_clause(session, "retention:4.2", as_of=FIRST)

        assert cited.clause.text.startswith("Staff records")
        assert cited.now is not None
        assert (cited.now.key, cited.now.moved, cited.now.changed) == ("retention:4.3", True, False)
        assert cited.now.version_label == "2"


class TestEndings:
    def test_a_discarded_draft_is_gone_from_the_policy(
        self, own: Engine, originals: Directory
    ) -> None:
        with session_from(own) as session:
            upload_version(
                session,
                originals,
                "retention",
                (FIXTURES / "retention-v1.md").read_bytes(),
                "retention-v1.md",
                actor=ACTOR,
                effective_date=date(2026, 9, 1),
            )
        with session_from(own) as session:
            discard(session, "retention", actor=ACTOR)
        with session_from(own) as session, pytest.raises(NoDraft):
            read_draft(session, "retention")

    def test_an_archived_policy_is_not_searched_but_still_reads(
        self, own: Engine, worker: jobs.Runtime
    ) -> None:
        with session_from(own) as session:
            archive(session, "council-data", actor=ACTOR)
        with session_from(own) as session:
            listed = [summary.slug for summary in list_documents(session)[0]]
            assert "council-data" not in listed
            assert "retention" in listed
            found = search(session, worker.embedder(), "the right of access")
            assert all(result.clause.document_slug != "council-data" for result in found)
            kept = get_clause(session, "council-data:individuals-rights:p1")
            assert kept.clause.archived

    def test_a_new_version_brings_an_archived_policy_back(
        self, own: Engine, originals: Directory
    ) -> None:
        with session_from(own) as session:
            upload_version(
                session,
                originals,
                "council-data",
                (FIXTURES / "heading-styles.docx").read_bytes(),
                "heading-styles.docx",
                actor=ACTOR,
                effective_date=date.today() + timedelta(days=1),
            )
            accept_flags(session, "council-data", None, actor=ACTOR)
            publish(session, "council-data", actor=ACTOR)
        with session_from(own) as session:
            summary = next(p for p in list_policies(session) if p.slug == "council-data")
            assert summary.status == "active"
            assert "council-data" in [s.slug for s in list_documents(session)[0]]
        assert entries(own, "document.published")[-1].details["restored"] is True

    def test_the_sample_policy_is_published_once_and_never_brought_back(
        self, own: Engine, originals: Directory
    ) -> None:
        with session_from(own) as session:
            assert load_sample(session, originals, actor=ACTOR)
        with session_from(own) as session:
            assert not load_sample(session, originals, actor=ACTOR)
            archive(session, SAMPLE_SLUG, actor=ACTOR)
        with session_from(own) as session:
            assert not load_sample(session, originals, actor=ACTOR)
            summary = next(p for p in list_policies(session) if p.slug == SAMPLE_SLUG)
        assert (summary.status, summary.published) == ("archived", 1)

    def test_the_daily_purge_removes_originals_nothing_points_at(
        self, own: Engine, originals: Directory, worker: jobs.Runtime
    ) -> None:
        stray = originals.put(b"a file whose upload never finished")
        kept = originals.put((FIXTURES / "retention-v1.md").read_bytes())
        day_ago = time.time() - 2 * 24 * 60 * 60
        for stored in (stray, kept):
            os.utime(originals.path(stored.key), (day_ago, day_ago))
        fresh = originals.put(b"an upload still in progress")

        counts = jobs.daily_purge(timestamp=int(time.time()))

        assert counts["originals"] == 1
        assert not originals.path(stray.key).exists()
        assert originals.path(kept.key).exists()
        assert originals.path(fresh.key).exists()

    def test_the_purge_also_runs_when_the_worker_starts(
        self, originals: Directory, worker: jobs.Runtime
    ) -> None:
        """For an instance that is not running at 03:17 UTC, such as one on a laptop."""
        stray = originals.put(b"left by an upload on a day the worker was stopped")
        day_ago = time.time() - 2 * 24 * 60 * 60
        os.utime(originals.path(stray.key), (day_ago, day_ago))

        jobs.purge_on_start()

        assert not originals.path(stray.key).exists()


def test_a_rolled_back_publish_leaves_no_job(own: Engine, originals: Directory) -> None:
    with session_from(own) as session:
        upload_policy(
            session,
            originals,
            (FIXTURES / "retention-v1.md").read_bytes(),
            "retention-v1.md",
            actor=ACTOR,
            slug="rolled-back",
        )
    with own.connect() as connection:
        before = connection.execute(text("SELECT count(*) FROM procrastinate_jobs")).scalar_one()
    with Session(own) as session:
        publish(session, "rolled-back", actor=ACTOR)
        session.rollback()
    with own.connect() as connection:
        after = connection.execute(text("SELECT count(*) FROM procrastinate_jobs")).scalar_one()
    assert after == before
