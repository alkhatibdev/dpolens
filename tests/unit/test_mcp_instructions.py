"""What the server tells an assistant, and what the two prompts ask it to do.

The guidance is the product as much as the search is: a corpus nothing consults
answers nothing. These tests hold the sentences that have to arrive, because they
are easy to lose in an edit and nothing else would notice.
"""

from __future__ import annotations

import pytest
from mcp import Client

from dpolens_mcp.instructions import EXAMPLES, INSTRUCTIONS, LOGGED, SENTENCES
from dpolens_stub import DEVELOPER

pytestmark = pytest.mark.anyio

DASHES = ("\u2014", "\u2013")
"""The em dash and the en dash, as escapes, so this file holds neither of them.

Public text in this project is punctuated with commas, colons, full stops and
parentheses, and a test about that rule should not be the file that breaks it.
"""


class TestWhatArrivesOnConnect:
    async def test_the_instructions_are_sent(self, connected: Client) -> None:
        assert connected.instructions is not None
        assert "DPOLens answers questions" in connected.instructions

    @pytest.mark.parametrize("sentence", SENTENCES, ids=range(len(SENTENCES)))
    async def test_every_sentence_a_surface_has_to_carry_is_there(
        self, connected: Client, sentence: str
    ) -> None:
        assert connected.instructions is not None
        assert sentence in connected.instructions

    @pytest.mark.parametrize("example", EXAMPLES)
    async def test_the_examples_are_there(self, connected: Client, example: str) -> None:
        """An assistant that has seen a question in this shape asks one in this shape."""
        assert connected.instructions is not None
        assert example in connected.instructions

    async def test_it_says_that_asking_is_recorded(self, connected: Client) -> None:
        """Said where somebody will read it, not only in the documentation."""
        assert connected.instructions is not None
        assert LOGGED in connected.instructions

    async def test_it_names_the_server_the_way_a_client_shows_it(self, connected: Client) -> None:
        named = connected.server_info
        assert named is not None
        assert named.name == "dpolens"
        assert named.title == "DPOLens"


class TestWhatTheToolsSayAboutThemselves:
    async def test_every_tool_says_that_the_call_is_recorded(self, connected: Client) -> None:
        """A developer should learn what is kept from the tool, not from an incident."""
        listed = await connected.list_tools()

        for tool in listed.tools:
            assert tool.description is not None
            assert "record" in tool.description.lower(), tool.name

    async def test_the_search_tool_says_when_to_reach_for_it(self, connected: Client) -> None:
        listed = await connected.list_tools()

        search = next(tool for tool in listed.tools if tool.name == "search_policies")
        assert search.description is not None
        assert "personal data" in search.description
        assert "before writing or changing code" in search.description

    async def test_the_search_tool_says_what_it_searches(self, connected: Client) -> None:
        """Every loaded pack, which is worth saying while there is one pack."""
        listed = await connected.list_tools()

        search = next(tool for tool in listed.tools if tool.name == "search_policies")
        assert search.description is not None
        assert "every pack loaded on this instance" in search.description

    async def test_nothing_here_writes(self, connected: Client) -> None:
        """A client may show the difference, and there is nothing to show but reads."""
        listed = await connected.list_tools()

        for tool in listed.tools:
            assert tool.annotations is not None
            assert tool.annotations.read_only_hint is True


class TestThePrompts:
    async def test_both_are_offered_with_a_title_a_person_can_read(self, connected: Client) -> None:
        listed = await connected.list_prompts()

        offered = {prompt.name: prompt for prompt in listed.prompts}
        assert set(offered) == {"policy_check", "policy_tour"}
        assert offered["policy_check"].title == "Check this change against the policies"
        assert offered["policy_tour"].title == "Show me what this instance can do"

    async def test_neither_asks_for_anything_before_it_can_run(self, connected: Client) -> None:
        """A prompt a person picks from a menu should not stop to ask for an argument."""
        listed = await connected.list_prompts()

        for prompt in listed.prompts:
            for argument in prompt.arguments or []:
                assert argument.required is not True, prompt.name

    async def test_the_check_asks_for_the_citation_and_for_what_was_not_found(
        self, connected: Client
    ) -> None:
        rendered = await connected.get_prompt("policy_check")

        said = str(rendered.messages[0].content)
        assert "the key, document and version" in said
        assert "found nothing about" in said

    async def test_the_check_can_be_pointed_at_something(self, connected: Client) -> None:
        rendered = await connected.get_prompt("policy_check", {"focus": "the new users table"})

        assert "Start with: the new users table" in str(rendered.messages[0].content)

    async def test_an_empty_focus_adds_nothing(self, connected: Client) -> None:
        rendered = await connected.get_prompt("policy_check", {"focus": "   "})

        assert "Start with:" not in str(rendered.messages[0].content)

    async def test_the_tour_shows_the_instance_rather_than_describing_it(
        self, connected: Client
    ) -> None:
        rendered = await connected.get_prompt("policy_tour")

        said = str(rendered.messages[0].content)
        assert "list_documents" in said
        assert "get_clause" in said
        assert "quote the documents rather than describing them" in said.lower()

    async def test_a_prompt_is_one_message_the_person_appears_to_have_sent(
        self, connected: Client
    ) -> None:
        rendered = await connected.get_prompt("policy_tour")

        assert len(rendered.messages) == 1
        assert rendered.messages[0].role == "user"


class TestTheTextItself:
    @pytest.mark.parametrize("dash", DASHES, ids=["em dash", "en dash"])
    def test_no_dash_appears_in_anything_a_reader_sees(self, dash: str) -> None:
        from dpolens_mcp import instructions

        for name in dir(instructions):
            value = getattr(instructions, name)
            if isinstance(value, str) and not name.startswith("__"):
                assert dash not in value, name

    def test_the_developers_token_is_not_in_any_of_it(self) -> None:
        """A sanity check on the fixture, so a leak in a test cannot read as a pass."""
        assert DEVELOPER not in INSTRUCTIONS
