"""What the four tools hand back, and what they do with a refusal.

The question behind most of these: could an assistant write a citation from this
answer that somebody could then check. That needs the clause word for word, the
key, the version and the date, and it needs a refusal to say what to do next
rather than to look like an empty result.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from mcp import Client

from dpolens_mcp.api import Api, Refused
from dpolens_mcp.credential import Credential
from dpolens_stub import (
    DEVELOPER,
    PAT_ID,
    SURFACE,
    USER_ID,
    Refusal,
    Stub,
    problem,
    said,
    structured,
)

pytestmark = pytest.mark.anyio


async def search(connected: Client, **arguments: Any) -> Any:
    return await connected.call_tool("search_policies", {"query": "retention", **arguments})


class TestWhatASearchHandsBack:
    async def test_the_clause_comes_back_word_for_word(self, connected: Client) -> None:
        result = await search(connected)

        found = structured(result)["results"][0]
        assert (
            found["text"] == "Data kept for a deleted account shall be erased within thirty days."
        )
        assert found["key"] == "testlaw:art-5:para-1"

    async def test_the_citation_names_the_document_the_version_and_the_date(
        self, connected: Client
    ) -> None:
        """Built here rather than left to the model, because a remembered one is wrong."""
        result = await search(connected)

        citation = structured(result)["results"][0]["citation"]
        assert citation == (
            "Test Data Protection Law, Chapter II Principles > Article 5 Storage limitation > 1 "
            "(testlaw:art-5:para-1), version 2020/1, in force since 2020-01-01"
        )

    async def test_the_breadcrumb_says_where_the_clause_sits(self, connected: Client) -> None:
        result = await search(connected)

        assert structured(result)["results"][0]["breadcrumb"] == [
            "Chapter II Principles",
            "Article 5 Storage limitation",
        ]

    async def test_a_result_carries_what_the_clause_points_at(self, connected: Client) -> None:
        result = await search(connected)

        assert structured(result)["results"][0]["cross_references"] == ["testlaw:art-6"]

    async def test_it_says_what_was_searched(self, connected: Client) -> None:
        result = await search(connected)

        assert structured(result)["searched"] == (
            "every pack loaded on this instance, and the organisation's own policies, "
            "as they stand today"
        )

    async def test_a_date_is_reflected_in_what_was_searched(self, connected: Client) -> None:
        result = await search(connected, as_of="2019-06-01")

        assert "as they stood on 2019-06-01" in structured(result)["searched"]

    async def test_the_model_and_the_client_are_told_the_same_thing(
        self, connected: Client
    ) -> None:
        """One answer, not two that can disagree."""
        result = await search(connected)

        assert json.loads(said(result)) == structured(result)

    async def test_nothing_found_is_an_empty_list_and_not_a_failure(
        self, connected: Client, stub: Stub
    ) -> None:
        """A question the corpus cannot answer is an answer, and worth recording."""
        stub.results = []

        result = await search(connected)

        assert result.is_error is False
        assert structured(result)["results"] == []

    async def test_a_clause_from_a_policy_carries_no_law_provenance(
        self, connected: Client, stub: Stub
    ) -> None:
        """An organisation's own policy is its own source, so those fields are null."""
        policy = {
            **stub.results[0]["clause"],
            "pack_slug": None,
            "jurisdiction": None,
            "trust_tier": None,
            "source_url": None,
            "document_title": "Data Retention Policy",
        }
        stub.results = [{**stub.results[0], "clause": policy, "breadcrumb": []}]

        result = await search(connected)

        found = structured(result)["results"][0]
        assert found["jurisdiction"] is None
        assert found["trust_tier"] is None
        assert found["source_url"] is None
        assert found["citation"].startswith("Data Retention Policy,")


class TestArgumentsThatCannotBeSent:
    async def test_a_question_longer_than_the_api_accepts_is_refused_here(
        self, connected: Client, stub: Stub
    ) -> None:
        """Refused before the call, so a mistake costs nothing and says why."""
        result = await connected.call_tool("search_policies", {"query": "x" * 1001})

        assert result.is_error is True
        assert stub.calls("/v1/search") == []

    @pytest.mark.parametrize("limit", [0, 51, -1])
    async def test_a_limit_outside_what_is_allowed_is_refused(
        self, connected: Client, stub: Stub, limit: int
    ) -> None:
        result = await search(connected, limit=limit)

        assert result.is_error is True
        assert stub.calls("/v1/search") == []

    async def test_an_empty_question_is_refused(self, connected: Client, stub: Stub) -> None:
        result = await connected.call_tool("search_policies", {"query": ""})

        assert result.is_error is True
        assert stub.calls("/v1/search") == []

    async def test_a_date_that_is_not_a_date_is_refused(
        self, connected: Client, stub: Stub
    ) -> None:
        result = await search(connected, as_of="last tuesday")

        assert result.is_error is True
        assert stub.calls("/v1/search") == []

    async def test_only_what_was_asked_for_reaches_the_api(
        self, connected: Client, stub: Stub
    ) -> None:
        """A default left out here stays the API's to decide."""
        await search(connected)

        sent = json.loads(stub.calls("/v1/search")[0].content)
        assert sent == {
            "query": "retention",
            "limit": 10,
            "lang": "en",
            "as_of": None,
            "include_explanatory": False,
        }


class TestActingForSomebody:
    async def test_the_real_call_names_the_developer_and_their_token(
        self, connected: Client, stub: Stub
    ) -> None:
        await search(connected)

        call = stub.calls("/v1/search")[0]
        assert call.headers["DPOLens-On-Behalf-Of-User"] == USER_ID
        assert call.headers["DPOLens-On-Behalf-Of-Token"] == PAT_ID

    async def test_the_credential_presented_upstream_is_this_servers_own(
        self, connected: Client, stub: Stub
    ) -> None:
        await search(connected)

        for call in stub.seen:
            assert call.headers["Authorization"] == f"Bearer {SURFACE}"

    async def test_the_callers_token_is_never_sent_on(self, connected: Client, stub: Stub) -> None:
        """The one place a caller's token may appear is the question about it."""
        await search(connected)

        asked_about = stub.calls("/v1/tokens/introspect")
        assert json.loads(asked_about[0].content) == {"token": DEVELOPER}
        for call in stub.calls("/v1/search"):
            assert DEVELOPER not in json.dumps(dict(call.headers))
            assert DEVELOPER not in call.content.decode()

    async def test_the_question_about_the_token_and_the_search_share_one_id(
        self, connected: Client, stub: Stub
    ) -> None:
        """Two calls, one question, so one id follows it through the instance's logs."""
        await search(connected)

        # The question about the token is the call immediately before the search
        # it led to, which is the pair the instance's logs have to join up.
        searched_at = stub.ordered().index("/v1/search")
        asked = stub.seen[searched_at - 1]
        searched = stub.seen[searched_at]
        assert asked.url.path == "/v1/tokens/introspect"
        assert asked.headers["X-Request-Id"] == searched.headers["X-Request-Id"]
        assert len(searched.headers["X-Request-Id"]) == 36

    async def test_every_call_asks_again_rather_than_trusting_a_cache(
        self, connected: Client, stub: Stub
    ) -> None:
        """Revoking a token has to take effect on the next call, not after a timeout."""
        await search(connected)
        await search(connected)

        assert len(stub.calls("/v1/tokens/introspect")) >= 2


class TestReadingAClause:
    async def test_it_returns_the_clause_its_place_and_what_sits_beneath(
        self, connected: Client
    ) -> None:
        result = await connected.call_tool("get_clause", {"key": "testlaw:art-5"})

        answer = structured(result)
        assert answer["clause"]["key"] == "testlaw:art-5"
        assert answer["clause"]["breadcrumb"] == ["Chapter II Principles"]
        assert [child["key"] for child in answer["children"]] == ["testlaw:art-5:para-1"]
        assert answer["children"][0]["text"].startswith("Data kept for a deleted account")
        assert answer["cross_references"] == ["testlaw:art-6"]

    async def test_a_child_is_cited_beneath_its_parent(self, connected: Client) -> None:
        result = await connected.call_tool("get_clause", {"key": "testlaw:art-5"})

        child = structured(result)["children"][0]
        assert child["breadcrumb"] == ["Chapter II Principles", "Article 5 Storage limitation"]

    async def test_the_whole_article_is_only_fetched_when_it_is_asked_for(
        self, connected: Client, stub: Stub
    ) -> None:
        result = await connected.call_tool("get_clause", {"key": "testlaw:art-5"})

        assert structured(result)["subtree"] == []
        assert stub.calls("/v1/clauses/testlaw:art-5/subtree") == []

    async def test_asking_for_the_whole_article_returns_it_in_reading_order(
        self, connected: Client
    ) -> None:
        result = await connected.call_tool(
            "get_clause", {"key": "testlaw:art-5", "whole_subtree": True}
        )

        assert [clause["key"] for clause in structured(result)["subtree"]] == [
            "testlaw:art-5",
            "testlaw:art-5:para-1",
        ]


class TestWhatCanBeCited:
    async def test_listing_says_what_is_loaded_and_which_version(self, connected: Client) -> None:
        result = await connected.call_tool("list_documents", {})

        answer = structured(result)
        assert answer["total"] == 1
        assert answer["documents"][0]["slug"] == "testlaw"
        assert answer["documents"][0]["version"] == "2020/1"
        assert answer["documents"][0]["in_force_since"] == "2020-01-01"

    async def test_an_outline_carries_no_text(self, connected: Client) -> None:
        """A document of a thousand clauses does not belong in one answer."""
        result = await connected.call_tool("get_document", {"slug": "testlaw"})

        outline = structured(result)["outline"]
        assert outline[0]["key"] == "testlaw:art-5"
        assert outline[0]["children"] == 3
        assert "text" not in outline[0]


class TestWhenTheInstanceRefuses:
    async def test_a_key_that_does_not_exist_says_what_to_try(
        self, connected: Client, stub: Stub
    ) -> None:
        stub.refuse(
            "/v1/clauses/testlaw:nope",
            Refusal(404, problem(404, "not-found", "Not found", "no clause testlaw:nope")),
        )

        result = await connected.call_tool("get_clause", {"key": "testlaw:nope"})

        assert result.is_error is True
        assert "no clause testlaw:nope" in said(result)
        assert "list_documents" in said(result)

    async def test_a_missing_permission_names_it_and_who_can_grant_it(
        self, connected: Client, stub: Stub
    ) -> None:
        stub.refuse(
            "/v1/search",
            Refusal(
                403,
                problem(
                    403,
                    "permission-required",
                    "Permission required",
                    "this token does not carry documents.read",
                    permission="documents.read",
                ),
            ),
        )

        result = await search(connected)

        assert result.is_error is True
        assert "documents.read" in said(result)
        assert "administers" in said(result)

    async def test_a_spent_quota_says_how_long_to_wait(self, connected: Client, stub: Stub) -> None:
        stub.refuse(
            "/v1/search",
            Refusal(
                429,
                problem(429, "too-many-requests", "Too many requests", "the quota is spent"),
                headers={"Retry-After": "17"},
            ),
        )

        result = await search(connected)

        assert result.is_error is True
        assert "Wait 17 seconds" in said(result)

    async def test_a_question_the_api_will_not_take_is_passed_back(
        self, connected: Client, stub: Stub
    ) -> None:
        stub.refuse(
            "/v1/search",
            Refusal(
                422,
                problem(422, "invalid-request", "Invalid request", "lang is not a language"),
            ),
        )

        result = await search(connected)

        assert result.is_error is True
        assert "lang is not a language" in said(result)

    @pytest.mark.parametrize(
        ("status", "kind", "detail"),
        [
            (401, "unauthenticated", "that token is not valid here"),
            (503, "not-ready", "the database is not reachable"),
            (500, "", "something broke"),
        ],
    )
    async def test_a_failure_the_caller_cannot_fix_is_not_explained_to_the_model(
        self, connected: Client, stub: Stub, status: int, kind: str, detail: str
    ) -> None:
        """An instance's own problem belongs in its log, not in a chat window.

        The call still fails, so the assistant does not act as though it had an
        answer, and the operator gets the status and the detail.
        """
        stub.refuse("/v1/search", Refusal(status, problem(status, kind, "Failed", detail)))

        result = await search(connected)

        assert result.is_error is True
        assert detail not in said(result)

    async def test_an_instance_that_cannot_be_reached_fails_the_call(
        self, connected: Client, stub: Stub
    ) -> None:
        stub.unreachable = {"/v1/search"}

        result = await search(connected)

        assert result.is_error is True


class TestWhenTheCredentialIsReplaced:
    async def test_a_new_credential_on_disk_is_picked_up_without_a_restart(
        self, connected: Client, stub: Stub, surface_file: Any
    ) -> None:
        """An operator who provisions a new credential should not have to restart this."""
        replaced = "dpol_replacedcredentialcccccccccccccccccc"
        stub.accepts = replaced
        surface_file.write_text(replaced + "\n", encoding="utf-8")

        result = await search(connected)

        assert result.is_error is False
        assert stub.calls("/v1/search")[-1].headers["Authorization"] == f"Bearer {replaced}"

    async def test_a_credential_the_file_still_holds_is_not_presented_twice(
        self, stub: Stub, surface_file: Any
    ) -> None:
        """A second refusal is all a second attempt could buy.

        Tested against the client rather than through a tool call, because a
        surface credential the instance refuses is refused at the door first.
        """
        api = Api(
            base_url="http://api.invalid",
            credential=Credential(surface_file),
            timeout=5,
            transport=stub.transport,
        )
        stub.accepts = "dpol_somethingelse"

        with pytest.raises(Refused) as refused:
            await api.introspect(DEVELOPER, request_id="r")

        assert refused.value.status == 401
        assert len(stub.calls("/v1/tokens/introspect")) == 1
        await api.aclose()
