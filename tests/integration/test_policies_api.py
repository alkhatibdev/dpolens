"""Policies through the API: upload, review, publish, versions, the original, archiving.

In a database of its own, signed in as an administrator, who may upload and publish, and as a
developer, who may read but do neither. The two retention files are the story the engine's own
tests tell: version 2 inserts a contractor rule at 4.2 and the staff rule becomes 4.3.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, select

from dpolens.api.app import create_app
from dpolens.engine.auth import permissions as catalog
from dpolens.engine.auth.catalog import bootstrap
from dpolens.engine.auth.passwords import set_password
from dpolens.engine.auth.users import create_user
from dpolens.engine.logs.governance import Actor
from dpolens.engine.logs.models import GovernanceEntry
from dpolens.engine.policies.store import MAX_UPLOAD_BYTES
from dpolens.engine.session import session_from
from dpolens.settings import Settings

pytestmark = pytest.mark.integration

ACTOR = Actor(via="cli", identity={"os_user": "tests", "host": "ci"})
PASSWORD = "correct horse battery staple"
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}
FIXTURES = Path(__file__).parents[1] / "fixtures" / "policies"
ADMIN = "admin-policies@example.com"
DEVELOPER = "dev-policies@example.com"
UPLOAD = {**SAME_ORIGIN, "Content-Type": "application/octet-stream"}


@pytest.fixture(scope="module")
def own(database_of_its_own: Callable[[str], tuple[str, str]]) -> Iterator[tuple[str, Engine]]:
    app_url, owner_url = database_of_its_own("dpolens_policies_api")
    owner = create_engine(owner_url)
    with session_from(owner) as opened:
        bootstrap(opened, actor=ACTOR)
    for email, role, name in (
        (ADMIN, catalog.ADMIN, "Yousef Haddad"),
        (DEVELOPER, catalog.DEVELOPER, "Omar Khalil"),
    ):
        with session_from(owner) as opened:
            create_user(opened, email=email, display_name=name, actor=ACTOR, roles=(role,))
            opened.flush()
            set_password(opened, email=email, password=PASSWORD, actor=ACTOR)
    yield app_url, owner
    owner.dispose()


@pytest.fixture(scope="module")
def app_client(
    own: tuple[str, Engine], tmp_path_factory: pytest.TempPathFactory
) -> Iterator[TestClient]:
    settings = Settings.model_validate(
        {"database_url": own[0], "originals_dir": str(tmp_path_factory.mktemp("originals"))}
    )
    with TestClient(create_app(settings), base_url="https://testserver") as client:
        yield client


def signed_in(client: TestClient, email: str) -> TestClient:
    client.cookies.clear()
    response = client.post(
        "/v1/sessions", json={"email": email, "password": PASSWORD}, headers=SAME_ORIGIN
    )
    assert response.status_code == 201, response.text
    return client


def upload(client: TestClient, path: str, name: str, **query: str) -> httpx2.Response:
    return client.post(
        path,
        params={"filename": name, **query},
        content=(FIXTURES / name).read_bytes(),
        headers=UPLOAD,
    )


class TestUploadAndPublish:
    def test_an_upload_comes_back_as_a_draft(self, app_client: TestClient) -> None:
        client = signed_in(app_client, ADMIN)

        response = upload(
            client, "/v1/policies", "retention-v1.md", slug="retention", effective_date="2026-01-01"
        )

        assert response.status_code == 201, response.text
        draft = response.json()
        assert draft["version"]["status"] == "draft"
        assert draft["version"]["created_by"] == "Yousef Haddad"
        assert [clause["key"] for clause in draft["clauses"][0]["children"]] == [
            "retention:4.1",
            "retention:4.2",
            "retention:4.3",
        ]
        assert draft["coverage"]["missed"] == 0
        assert draft["changes"]["removed"] == 0

    def test_a_file_it_cannot_read_is_refused_with_what_to_do(self, app_client: TestClient) -> None:
        client = signed_in(app_client, ADMIN)

        response = client.post(
            "/v1/policies", params={"filename": "scan.pdf"}, content=b"%PDF-1.7", headers=UPLOAD
        )

        assert response.status_code == 422
        assert response.json()["type"] == "/problems/unreadable-policy"
        assert "Word or Markdown file the PDF was made from" in response.json()["detail"]

    def test_a_file_over_the_limit_is_refused_before_it_is_read(
        self, app_client: TestClient
    ) -> None:
        response = app_client.post(
            "/v1/policies",
            params={"filename": "huge.md"},
            content=b"x" * (MAX_UPLOAD_BYTES + 1),
            headers=UPLOAD,
        )

        assert response.status_code == 413
        assert response.json()["type"] == "/problems/too-large"

    def test_a_developer_can_neither_upload_nor_publish(self, app_client: TestClient) -> None:
        client = signed_in(app_client, DEVELOPER)

        assert upload(client, "/v1/policies", "retention-v1.md", slug="x").status_code == 403
        assert (
            client.post("/v1/policies/retention/draft/publish", headers=SAME_ORIGIN).status_code
            == 403
        )

    def test_publishing_waits_for_the_flags_and_names_them(self, app_client: TestClient) -> None:
        client = signed_in(app_client, ADMIN)
        assert (
            upload(client, "/v1/policies", "heading-styles.docx", slug="council").status_code == 201
        )

        refused = client.post("/v1/policies/council/draft/publish", headers=SAME_ORIGIN)

        assert refused.status_code == 409
        assert refused.json()["type"] == "/problems/flags-open"
        assert refused.json()["flags"] == [1]

        accepted = client.post(
            "/v1/policies/council/draft/flags/accept", json={"positions": [1]}, headers=SAME_ORIGIN
        )
        assert accepted.json()["flags"][0]["accepted_by"] == "Yousef Haddad"
        published = client.post("/v1/policies/council/draft/publish", headers=SAME_ORIGIN)
        assert published.status_code == 200, published.text
        assert published.json()["status"] == "published"
        assert published.json()["indexing"] == "todo"

    def test_a_published_policy_reads_like_any_clause(self, app_client: TestClient) -> None:
        client = signed_in(app_client, ADMIN)
        assert (
            client.post("/v1/policies/retention/draft/publish", headers=SAME_ORIGIN).status_code
            == 200
        )

        read = signed_in(app_client, DEVELOPER).get(
            "/v1/clauses/retention:4.2", headers=SAME_ORIGIN
        )

        assert read.status_code == 200, read.text
        assert read.json()["clause"]["text"].startswith("Staff records")
        assert read.json()["clause"]["version_label"] == "1"
        documents = signed_in(app_client, DEVELOPER).get("/v1/documents", headers=SAME_ORIGIN)
        assert "retention" in [document["slug"] for document in documents.json()["documents"]]


class TestVersions:
    def test_a_new_version_is_matched_and_flagged(self, app_client: TestClient) -> None:
        client = signed_in(app_client, ADMIN)

        response = upload(
            client,
            "/v1/policies/retention/versions",
            "retention-v2.md",
            effective_date="2026-06-01",
        )

        assert response.status_code == 201, response.text
        draft = response.json()
        assert draft["previous"] == "1"
        assert draft["changes"] == {
            "added": 1,
            "modified": 1,
            "moved": 2,
            "unchanged": 3,
            "removed": 0,
        }
        staff = draft["clauses"][0]["children"][2]
        assert (staff["key"], staff["change"], staff["continues"]) == (
            "retention:4.3",
            "moved",
            "retention:4.2",
        )

    def test_a_second_draft_is_refused_and_says_which_is_open(self, app_client: TestClient) -> None:
        client = signed_in(app_client, ADMIN)

        refused = upload(client, "/v1/policies/retention/versions", "retention-v2.md")

        assert refused.status_code == 409
        assert refused.json()["type"] == "/problems/draft-exists"
        assert refused.json()["version"] == 2

    def test_publishing_the_new_version_keeps_old_citations_exact(
        self, app_client: TestClient
    ) -> None:
        client = signed_in(app_client, ADMIN)
        draft = client.get("/v1/policies/retention/draft", headers=SAME_ORIGIN).json()
        positions = [flag["position"] for flag in draft["flags"]]
        client.post(
            "/v1/policies/retention/draft/flags/accept",
            json={"positions": positions},
            headers=SAME_ORIGIN,
        )
        assert (
            client.post("/v1/policies/retention/draft/publish", headers=SAME_ORIGIN).status_code
            == 200
        )

        today = client.get(
            "/v1/clauses/retention:4.2", params={"as_of": "2026-06-01"}, headers=SAME_ORIGIN
        ).json()
        assert today["clause"]["text"].startswith("Contractor records")
        assert today["formerly"]["now"] == "retention:4.3"

        cited = client.get(
            "/v1/clauses/retention:4.2", params={"as_of": "2026-01-01"}, headers=SAME_ORIGIN
        ).json()
        assert cited["clause"]["text"].startswith("Staff records")
        assert cited["now"] == {
            "key": "retention:4.3",
            "version_label": "2",
            "effective_date": "2026-06-01",
            "moved": True,
            "changed": False,
        }

    def test_the_original_file_downloads_as_it_was_uploaded(self, app_client: TestClient) -> None:
        response = signed_in(app_client, DEVELOPER).get(
            "/v1/policies/retention/versions/1/original", headers=SAME_ORIGIN
        )

        assert response.status_code == 200
        assert response.content == (FIXTURES / "retention-v1.md").read_bytes()
        assert response.headers["content-disposition"] == 'attachment; filename="retention-v1.md"'

    def test_a_name_in_arabic_downloads_under_that_name(self, app_client: TestClient) -> None:
        client = signed_in(app_client, ADMIN)
        assert (
            client.post(
                "/v1/policies",
                params={"filename": "سياسة الاحتفاظ.md", "slug": "arabic-name"},
                content=(FIXTURES / "retention-v1.md").read_bytes(),
                headers=UPLOAD,
            ).status_code
            == 201
        )

        response = client.get("/v1/policies/arabic-name/versions/1/original", headers=SAME_ORIGIN)

        assert response.status_code == 200
        assert response.headers["content-disposition"] == (
            'attachment; filename="arabic-name-1.md"; '
            "filename*=UTF-8''%D8%B3%D9%8A%D8%A7%D8%B3%D8%A9%20"
            "%D8%A7%D9%84%D8%A7%D8%AD%D8%AA%D9%81%D8%A7%D8%B8.md"
        )


def draft_of(client: TestClient, slug: str) -> tuple[dict[str, Any], str]:
    response = client.get(f"/v1/policies/{slug}/draft", headers=SAME_ORIGIN)
    assert response.status_code == 200, response.text
    return response.json(), response.headers["etag"]


def flag_on(draft: dict[str, Any], key: str) -> dict[str, Any]:
    return next(flag for flag in draft["flags"] if flag["key"] == key)


def clauses_of(draft: dict[str, Any]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}

    def walk(clauses: list[dict[str, Any]]) -> None:
        for clause in clauses:
            found[clause["key"]] = clause
            walk(clause["children"])

    walk(draft["clauses"])
    return found


class TestReview:
    """Two reviewers on one draft, a match said to be wrong, and the file beside its clauses."""

    def test_a_change_made_after_someone_else_s_is_refused_with_who_and_when(
        self, app_client: TestClient
    ) -> None:
        client = signed_in(app_client, ADMIN)
        made = upload(
            client, "/v1/policies", "retention-v1.md", slug="schedule", effective_date="2026-01-01"
        )
        assert made.headers["etag"] == '"1"'
        draft, etag = draft_of(client, "schedule")
        assert (draft["revision"], draft["updated_by"]) == (1, "Yousef Haddad")

        changed = client.patch(
            "/v1/policies/schedule/draft",
            json={"title": "Retention schedule"},
            headers={**SAME_ORIGIN, "If-Match": etag},
        )
        stale = client.patch(
            "/v1/policies/schedule/draft",
            json={"version_label": "2026"},
            headers={**SAME_ORIGIN, "If-Match": etag},
        )

        assert changed.status_code == 200, changed.text
        assert changed.headers["etag"] == '"2"'
        assert stale.status_code == 412
        assert stale.json()["type"] == "/problems/edit-conflict"
        assert (stale.json()["revision"], stale.json()["updated_by"]) == (2, "Yousef Haddad")
        assert draft_of(client, "schedule")[0]["version"]["label"] is None
        unreadable = client.patch(
            "/v1/policies/schedule/draft",
            json={"title": "x"},
            headers={**SAME_ORIGIN, "If-Match": "yesterday"},
        )
        assert unreadable.status_code == 400

    def test_a_match_said_to_be_wrong_makes_the_clause_new_and_the_rule_before_removed(
        self, app_client: TestClient
    ) -> None:
        client = signed_in(app_client, ADMIN)
        assert (
            client.post("/v1/policies/schedule/draft/publish", headers=SAME_ORIGIN).status_code
            == 200
        )
        assert (
            upload(
                client,
                "/v1/policies/schedule/versions",
                "retention-v2.md",
                effective_date="2026-06-01",
            ).status_code
            == 201
        )
        draft, etag = draft_of(client, "schedule")
        assert (draft["version"]["label"], draft["next_label"]) == (None, "2")
        assert flag_on(draft, "schedule:4.2")["detail"].endswith(", now 4.3.")
        staff = clauses_of(draft)["schedule:4.3"]
        assert staff["earlier"]["text"].startswith("Staff records")

        response = client.post(
            "/v1/policies/schedule/draft/matches/schedule:4.3/reject",
            headers={**SAME_ORIGIN, "If-Match": etag},
        )

        assert response.status_code == 200, response.text
        draft = response.json()
        staff = clauses_of(draft)["schedule:4.3"]
        assert (staff["change"], staff["continues"], staff["earlier"]) == ("added", None, None)
        assert [gone["key"] for gone in draft["removed"]] == ["schedule:4.2"]
        assert draft["changes"] == {
            "added": 2,
            "modified": 1,
            "moved": 1,
            "unchanged": 3,
            "removed": 1,
        }
        settled = flag_on(draft, "schedule:4.3")
        assert (settled["resolution"], settled["resolved_by"], settled["accepted_at"]) == (
            "match-rejected",
            "Yousef Haddad",
            None,
        )
        assert flag_on(draft, "schedule:4.2")["detail"].endswith(", since removed.")
        again = client.post(
            "/v1/policies/schedule/draft/matches/schedule:4.3/reject", headers=SAME_ORIGIN
        )
        assert again.status_code == 404
        assert again.json()["type"] == "/problems/no-match"

    def test_the_rule_said_to_be_different_reads_as_removed_once_published(
        self, app_client: TestClient
    ) -> None:
        client = signed_in(app_client, ADMIN)
        refused = client.post("/v1/policies/schedule/draft/publish", headers=SAME_ORIGIN)
        draft, _ = draft_of(client, "schedule")
        open_flags = [
            flag["position"]
            for flag in draft["flags"]
            if flag["accepted_at"] is None and flag["resolved_at"] is None
        ]
        assert refused.json()["flags"] == open_flags
        assert flag_on(draft, "schedule:4.3")["position"] not in open_flags
        client.post(
            "/v1/policies/schedule/draft/flags/accept",
            json={"positions": open_flags},
            headers=SAME_ORIGIN,
        )

        assert (
            client.post("/v1/policies/schedule/draft/publish", headers=SAME_ORIGIN).status_code
            == 200
        )
        cited = client.get(
            "/v1/clauses/schedule:4.2", params={"as_of": "2026-01-01"}, headers=SAME_ORIGIN
        ).json()
        assert cited["clause"]["text"].startswith("Staff records")
        assert cited["now"]["key"] is None

    def test_the_file_as_read_names_the_clause_each_paragraph_went_to(
        self, app_client: TestClient
    ) -> None:
        response = signed_in(app_client, DEVELOPER).get(
            "/v1/policies/schedule/versions/1/file", headers=SAME_ORIGIN
        )

        assert response.status_code == 200, response.text
        read = response.json()
        assert read["source"] == {
            "name": "retention-v1.md",
            "format": "markdown",
            "size": len((FIXTURES / "retention-v1.md").read_bytes()),
        }
        assert [
            (
                paragraph["text"][:12],
                paragraph["heading"],
                paragraph["clause"],
                paragraph["set_aside"],
            )
            for paragraph in read["paragraphs"][:3]
        ] == [
            ("Retention po", 1, None, "title"),
            ("4. Retention", 2, "schedule:4", None),
            ("4.1 Customer", None, "schedule:4.1", None),
        ]

    def test_a_draft_s_file_and_original_are_for_those_who_review_policies(
        self, app_client: TestClient
    ) -> None:
        client = signed_in(app_client, ADMIN)
        assert (
            upload(client, "/v1/policies/schedule/versions", "retention-v1.md").status_code == 201
        )
        assert client.get("/v1/policies/schedule/versions/3/file", headers=SAME_ORIGIN).is_success

        reader = signed_in(app_client, DEVELOPER)
        for path in ("file", "original"):
            refused = reader.get(f"/v1/policies/schedule/versions/3/{path}", headers=SAME_ORIGIN)
            assert refused.status_code == 403
            assert refused.json()["permissions"] == ["documents.upload", "documents.publish"]

    def test_the_list_says_how_far_each_review_has_got(self, app_client: TestClient) -> None:
        client = signed_in(app_client, ADMIN)
        assert (
            upload(
                client, "/v1/policies", "retention-v1.md", slug="later", effective_date="2099-01-01"
            ).status_code
            == 201
        )
        assert (
            client.post("/v1/policies/later/draft/publish", headers=SAME_ORIGIN).status_code == 200
        )

        listed = {p["slug"]: p for p in client.get("/v1/policies", headers=SAME_ORIGIN).json()}

        schedule = listed["schedule"]
        assert (schedule["in_force"], schedule["in_force_number"], schedule["draft"]) == ("2", 2, 3)
        assert (schedule["sample"], schedule["next_label"]) == (False, "3")
        assert (schedule["review"]["uploaded_by"], schedule["review"]["next_label"]) == (
            "Yousef Haddad",
            "3",
        )
        assert schedule["review"]["open"] == schedule["review"]["flags"]
        assert schedule["last_change"]["by"] == "Yousef Haddad"
        later = listed["later"]
        assert (later["in_force"], later["scheduled"]) == (
            None,
            {"label": "1", "effective_date": "2099-01-01"},
        )
        assert (later["review"], later["next_label"]) == (None, "2")


class TestEndings:
    def test_a_draft_can_be_discarded(self, app_client: TestClient) -> None:
        client = signed_in(app_client, ADMIN)
        assert (
            upload(client, "/v1/policies/retention/versions", "retention-v1.md").status_code == 201
        )

        assert client.delete("/v1/policies/retention/draft", headers=SAME_ORIGIN).status_code == 204
        assert client.get("/v1/policies/retention/draft", headers=SAME_ORIGIN).status_code == 404

    def test_archiving_takes_a_policy_out_of_the_library(self, app_client: TestClient) -> None:
        assert (
            signed_in(app_client, DEVELOPER)
            .post("/v1/policies/council/archive", headers=SAME_ORIGIN)
            .status_code
            == 403
        )
        client = signed_in(app_client, ADMIN)

        assert client.post("/v1/policies/council/archive", headers=SAME_ORIGIN).status_code == 204

        documents = client.get("/v1/documents", headers=SAME_ORIGIN).json()["documents"]
        assert "council" not in [document["slug"] for document in documents]
        listed = {p["slug"]: p for p in client.get("/v1/policies", headers=SAME_ORIGIN).json()}
        assert listed["council"]["status"] == "archived"
        assert listed["retention"]["in_force"] == "2"
        assert listed["retention"]["indexing"] == "todo"

    def test_every_step_names_who_took_it(self, own: tuple[str, Engine]) -> None:
        with session_from(own[1]) as opened:
            actions = [
                (entry.action, entry.details["via"])
                for entry in opened.scalars(
                    select(GovernanceEntry)
                    .where(GovernanceEntry.action.like("document.%"))
                    .order_by(GovernanceEntry.seq)
                )
            ]
        assert ("document.drafted", "dashboard") in actions
        assert ("document.flag_accepted", "dashboard") in actions
        assert ("document.match_rejected", "dashboard") in actions
        assert ("document.published", "dashboard") in actions
        assert ("document.draft_discarded", "dashboard") in actions
        assert ("document.archived", "dashboard") in actions
