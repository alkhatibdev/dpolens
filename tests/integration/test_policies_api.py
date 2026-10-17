"""Policies through the API: upload, review, publish, versions, the original, archiving.

In a database of its own, signed in as an administrator, who may upload and publish, and as a
developer, who may read but do neither. The two retention files are the story the engine's own
tests tell: version 2 inserts a contractor rule at 4.2 and the staff rule becomes 4.3.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import quote

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


def fixed(
    client: TestClient, slug: str, edit: str, key: str, at: int | None = None, etag: str = ""
) -> httpx2.Response:
    return client.post(
        f"/v1/policies/{slug}/draft/edits",
        json={"edit": edit, "key": key, "at": at},
        headers={**SAME_ORIGIN, **({"If-Match": etag} if etag else {})},
    )


def open_flags(draft: dict[str, Any]) -> list[dict[str, Any]]:
    return [flag for flag in draft["flags"] if not flag["accepted_at"] and not flag["resolved_at"]]


class TestFixing:
    """Fixing what was read: a made-up acceptable use policy with a heading that has no number,
    two numbers typed into the clause before them, and a rule cut in two by a stray line."""

    def test_a_flag_suggests_the_fix_the_parser_knows(self, app_client: TestClient) -> None:
        client = signed_in(app_client, ADMIN)
        made = upload(
            client, "/v1/policies", "acceptable-use.md", slug="aup", effective_date="2026-01-01"
        )
        assert made.status_code == 201, made.text

        flags = made.json()["flags"]
        clauses = clauses_of(made.json())

        assert clauses["aup:1"]["fixes"] == ["make-text"]
        assert clauses["aup:2.2"]["fixes"] == [
            "split",
            "merge",
            "make-heading",
            "move-under",
            "move-out",
        ]
        assert clauses["aup:2.2"]["splits"] == [{"at": 18, "label": "2.3"}]
        assert clauses["aup:2.1"]["splits"] == []
        assert [(flag["detail"][:16], flag["suggestion"]) for flag in flags] == [
            ('"Personal use" h', {"edit": "move-under", "key": "aup:personal-use", "at": None}),
            ("2.4 follows 2.2.", {"edit": "split", "key": "aup:2.2", "at": 18}),
            ("3.3 follows 3.1.", {"edit": "split", "key": "aup:3.1", "at": 74}),
        ]

    def test_moving_a_heading_under_the_one_before_settles_its_flag(
        self, app_client: TestClient
    ) -> None:
        client = signed_in(app_client, ADMIN)
        _, etag = draft_of(client, "aup")

        response = fixed(client, "aup", "move-under", "aup:personal-use", etag=etag)

        assert response.status_code == 200, response.text
        assert response.headers["etag"] == f'"{int(etag.strip(chr(34))) + 1}"'
        draft = response.json()
        assert draft["clause"] == "aup:2:personal-use"
        moved = clauses_of(draft)["aup:2:personal-use"]
        assert (moved["layer"], moved["fixed"]) == ("reviewer", "moved-under")
        assert "aup:2:personal-use:p1" in clauses_of(draft)
        settled = draft["flags"][0]
        assert (settled["key"], settled["resolution"], settled["resolution_key"]) == (
            "aup:2:personal-use",
            "moved-under",
            "aup:2",
        )
        assert (settled["resolved_by"], settled["suggestion"]) == ("Yousef Haddad", None)

    def test_splitting_where_a_missing_number_is_typed_settles_the_numbering_flag(
        self, app_client: TestClient
    ) -> None:
        client = signed_in(app_client, ADMIN)
        draft, etag = draft_of(client, "aup")
        suggestion = draft["flags"][1]["suggestion"]

        response = fixed(client, "aup", **suggestion, etag=etag)

        assert response.status_code == 200, response.text
        draft = response.json()
        clauses = clauses_of(draft)
        assert clauses["aup:2.2"]["text"] == "Lock your screen."
        assert (clauses["aup:2.3"]["label"], clauses["aup:2.3"]["text"]) == (
            "2.3",
            "Clear your desk at the end of the day.",
        )
        gap = draft["flags"][1]
        assert (gap["key"], gap["resolution"], gap["resolution_key"]) == (
            "aup:2.4",
            "split",
            "aup:2.3",
        )
        read = client.get("/v1/policies/aup/versions/1/file", headers=SAME_ORIGIN).json()
        both = next(line for line in read["paragraphs"] if line["text"].startswith("2.2 Lock"))
        assert (both["clause"], both["clauses"]) == ("aup:2.2", ["aup:2.2", "aup:2.3"])

    def test_a_rule_cut_in_two_is_merged_with_the_one_before(self, app_client: TestClient) -> None:
        client = signed_in(app_client, ADMIN)

        response = fixed(client, "aup", "merge", "aup:3:p1")

        assert response.status_code == 200, response.text
        draft = response.json()
        assert draft["clause"] == "aup:3.3"
        assert clauses_of(draft)["aup:3.3"]["text"] == (
            "Records are read only by the security team, and only\nwhen misuse is suspected."
        )
        assert "aup:3:p1" not in clauses_of(draft)

    def test_a_fix_that_cannot_be_made_is_refused_with_why(self, app_client: TestClient) -> None:
        client = signed_in(app_client, ADMIN)
        _, etag = draft_of(client, "aup")

        first = fixed(client, "aup", "move-under", "aup:1")
        missing = fixed(client, "aup", "merge", "aup:9.9")
        nowhere = fixed(client, "aup", "split", "aup:2.1")
        stale = fixed(client, "aup", "move-out", "aup:2.1", etag='"1"')

        assert (first.status_code, first.json()["type"]) == (409, "/problems/fix-refused")
        assert "no clause before it" in first.json()["detail"]
        assert (missing.status_code, missing.json()["type"]) == (404, "/problems/no-clause")
        assert nowhere.status_code == 409
        assert stale.status_code == 412
        assert draft_of(client, "aup")[1] == etag
        reader = signed_in(app_client, DEVELOPER)
        assert fixed(reader, "aup", "move-out", "aup:2.1").status_code == 403

    def test_a_numbering_flag_stays_open_when_its_clause_only_lost_its_neighbours(
        self, app_client: TestClient
    ) -> None:
        client = signed_in(app_client, ADMIN)
        made = upload(client, "/v1/policies", "acceptable-use.md", slug="aup-gap")
        assert made.status_code == 201, made.text

        # 2.2 goes out a level and 2.4 comes along; 2.2 goes back under 2, and 2.4 stays out.
        fixed(client, "aup-gap", "move-out", "aup-gap:2.2")
        draft = fixed(client, "aup-gap", "move-under", "aup-gap:2.2").json()

        gap = next(flag for flag in draft["flags"] if flag["detail"] == "2.4 follows 2.2.")
        assert (gap["key"], gap["resolved_at"]) == ("aup-gap:2.4", None)

    def test_heading_or_text_goes_both_ways(self, app_client: TestClient) -> None:
        client = signed_in(app_client, ADMIN)

        as_text = fixed(client, "aup", "make-text", "aup:2:personal-use").json()
        made = clauses_of(as_text)[as_text["clause"]]
        assert (made["kind"], made["heading"], made["text"]) == ("paragraph", None, "Personal use")
        as_heading = fixed(client, "aup", "make-heading", as_text["clause"]).json()
        after = clauses_of(as_heading)[as_heading["clause"]]
        assert (after["kind"], after["heading"], after["fixed"]) == (
            "section",
            "Personal use",
            "made-heading",
        )
        # What followed it when it became text stays where it is; moving it back is a fix too.
        assert "aup:2:p1" in clauses_of(as_heading)
        back = fixed(client, "aup", "move-under", "aup:2:p1").json()
        assert back["clause"] == "aup:2:personal-use:p1"

    def test_with_every_flag_settled_the_fixed_draft_publishes(
        self, app_client: TestClient
    ) -> None:
        client = signed_in(app_client, ADMIN)
        draft, _ = draft_of(client, "aup")
        suggestion = draft["flags"][2]["suggestion"]
        split = fixed(client, "aup", **suggestion).json()
        assert open_flags(split) == []

        published = client.post("/v1/policies/aup/draft/publish", headers=SAME_ORIGIN)

        assert published.status_code == 200, published.text
        cited = client.get("/v1/clauses/aup:3.2", headers=SAME_ORIGIN)
        assert cited.json()["clause"]["text"] == "The records are kept for 90 days."

    def test_a_new_version_fixed_the_same_way_is_matched_again_as_unchanged(
        self, app_client: TestClient
    ) -> None:
        client = signed_in(app_client, ADMIN)
        uploaded = upload(
            client, "/v1/policies/aup/versions", "acceptable-use.md", effective_date="2026-06-01"
        ).json()
        assert clauses_of(uploaded)["aup:personal-use"]["change"] == "moved"
        assert [gone["key"] for gone in uploaded["removed"]] == ["aup:2.2", "aup:2.3", "aup:3.2"]
        splits = [
            flag["suggestion"]
            for flag in uploaded["flags"]
            if flag["suggestion"] and flag["suggestion"]["edit"] == "split"
        ]

        assert fixed(client, "aup", "move-under", "aup:personal-use").is_success
        for suggestion in splits:
            assert fixed(client, "aup", **suggestion).is_success
        draft = fixed(client, "aup", "merge", "aup:3:p1").json()

        assert draft["changes"] == {
            "added": 0,
            "modified": 0,
            "moved": 0,
            "unchanged": len(clauses_of(draft)),
            "removed": 0,
        }
        assert open_flags(draft) == []


def settle_and_publish(client: TestClient, slug: str) -> None:
    draft, _ = draft_of(client, slug)
    left = [flag["position"] for flag in open_flags(draft)]
    if left:
        client.post(
            f"/v1/policies/{slug}/draft/flags/accept",
            json={"positions": left},
            headers=SAME_ORIGIN,
        )
    published = client.post(f"/v1/policies/{slug}/draft/publish", headers=SAME_ORIGIN)
    assert published.status_code == 200, published.text


class TestLibrary:
    """A policy's versions and any two compared: version 2 inserts a rule at 4.2, and version 3
    takes it out again, so every rule of version 3 is where version 1 had it."""

    def test_the_versions_say_which_is_in_force_and_until_when(
        self, app_client: TestClient
    ) -> None:
        client = signed_in(app_client, ADMIN)
        first = upload(
            client, "/v1/policies", "retention-v1.md", slug="history", effective_date="2025-09-01"
        )
        assert first.status_code == 201, first.text
        settle_and_publish(client, "history")
        for name, effective in (
            ("retention-v2.md", "2026-02-01"),
            ("retention-v1.md", "2099-01-01"),
        ):
            path = "/v1/policies/history/versions"
            assert upload(client, path, name, effective_date=effective).status_code == 201
            settle_and_publish(client, "history")
        assert upload(client, "/v1/policies/history/versions", "retention-v2.md").status_code == 201

        listed = client.get("/v1/policies/history/versions", headers=SAME_ORIGIN).json()

        assert [
            (entry["label"], entry["state"], entry["effective_date"], entry["until"])
            for entry in listed["versions"]
        ] == [
            ("4", "draft", listed["versions"][0]["effective_date"], None),
            ("3", "scheduled", "2099-01-01", None),
            ("2", "in_force", "2026-02-01", "2098-12-31"),
            ("1", "replaced", "2025-09-01", "2026-01-31"),
        ]
        draft = listed["versions"][0]
        assert (draft["created_by"], draft["flags"] == draft["open"]) == ("Yousef Haddad", True)
        assert listed["versions"][2]["published_by"] == "Yousef Haddad"
        assert listed["versions"][2]["source"]["name"] == "retention-v2.md"

    def test_a_reader_sees_every_published_version_and_no_draft(
        self, app_client: TestClient
    ) -> None:
        listed = (
            signed_in(app_client, DEVELOPER)
            .get("/v1/policies/history/versions", headers=SAME_ORIGIN)
            .json()
        )

        assert [entry["state"] for entry in listed["versions"]] == [
            "scheduled",
            "in_force",
            "replaced",
        ]

    def test_a_section_reads_with_the_clauses_numbered_under_it(
        self, app_client: TestClient
    ) -> None:
        # 4.1 is keyed history:4.1, not history:4:4.1, and is still read as part of 4.
        branch = (
            signed_in(app_client, DEVELOPER)
            .get(f"/v1/clauses/{quote('history:4')}/subtree", headers=SAME_ORIGIN)
            .json()
        )

        assert [clause["key"] for clause in branch] == [
            "history:4",
            "history:4.1",
            "history:4.2",
            "history:4.3",
            "history:4.4",
        ]

    def test_two_adjacent_versions_compare_as_they_were_matched(
        self, app_client: TestClient
    ) -> None:
        client = signed_in(app_client, DEVELOPER)

        found = client.get(
            "/v1/policies/history/compare", params={"from": 2, "to": 1}, headers=SAME_ORIGIN
        )

        assert found.status_code == 200, found.text
        compared = found.json()
        assert (compared["earlier"]["label"], compared["later"]["label"]) == ("1", "2")
        assert compared["changes"] == {
            "added": 1,
            "modified": 1,
            "moved": 2,
            "unchanged": 3,
            "removed": 0,
        }
        by_key = {clause["key"]: clause for clause in compared["clauses"]}
        assert (by_key["history:4.3"]["change"], by_key["history:4.3"]["earlier"]["key"]) == (
            "moved",
            "history:4.2",
        )
        assert by_key["history:4.2"]["earlier"] is None
        assert by_key["history:5.1"]["earlier"]["text"] == "This policy is reviewed every year."

    def test_versions_further_apart_follow_each_rule_through_the_ones_between(
        self, app_client: TestClient
    ) -> None:
        compared = (
            signed_in(app_client, DEVELOPER)
            .get("/v1/policies/history/compare", params={"from": 1, "to": 3}, headers=SAME_ORIGIN)
            .json()
        )

        # The contractor rule came in with version 2 and left with version 3.
        assert compared["changes"] == {
            "added": 0,
            "modified": 0,
            "moved": 0,
            "unchanged": 6,
            "removed": 0,
        }

    def test_only_two_different_published_versions_compare(self, app_client: TestClient) -> None:
        client = signed_in(app_client, ADMIN)

        itself = client.get(
            "/v1/policies/history/compare", params={"from": 2, "to": 2}, headers=SAME_ORIGIN
        )
        draft = client.get(
            "/v1/policies/history/compare", params={"from": 2, "to": 4}, headers=SAME_ORIGIN
        )

        assert (itself.status_code, itself.json()["type"]) == (400, "/problems/invalid-request")
        assert (draft.status_code, draft.json()["type"]) == (404, "/problems/policy-not-found")
        assert "no published version 4" in draft.json()["detail"]


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
        assert ("document.clause_fixed", "dashboard") in actions
        assert ("document.published", "dashboard") in actions
        assert ("document.draft_discarded", "dashboard") in actions
        assert ("document.archived", "dashboard") in actions
