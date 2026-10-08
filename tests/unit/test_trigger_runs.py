"""Reading a trigger run from Claude Code's stream of events, and scoring a batch.

The events are built by hand in the shape Claude Code prints with
`--output-format stream-json`, so these tests pin what counts as a call
without running an assistant.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from run_trigger_test import (  # noqa: E402
    PREFIXES,
    SERVERS,
    Observation,
    Outcome,
    Task,
    agrees,
    outcome_of,
    score,
    token_from,
)

SEARCH = PREFIXES["plugin"] + "search_policies"
LIST = PREFIXES["plugin"] + "list_documents"


def init(status: str = "connected", plugins: tuple[str, ...] = ("dpolens",)) -> dict[str, Any]:
    return {
        "type": "system",
        "subtype": "init",
        "model": "claude-test-1",
        "claude_code_version": "2.1.288",
        "mcp_servers": [{"name": SERVERS["plugin"], "status": status}],
        "plugins": [{"name": name, "path": "/x"} for name in plugins],
    }


def use(tool_id: str, name: str) -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "id": tool_id, "name": name, "input": {}}]},
    }


def answer(tool_id: str) -> dict[str, Any]:
    return {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "tool_use_id": tool_id, "content": "ok"}]},
    }


def watch(*events: dict[str, Any]) -> Observation:
    seen = Observation(prefix=PREFIXES["plugin"], server=SERVERS["plugin"])
    for event in events:
        seen.see(event)
    return seen


def test_the_token_is_the_line_that_holds_it_not_the_prefix_named_above_it() -> None:
    """The prefix line came first and was taken for the token, so every run was refused."""
    printed = (
        "Created dpol_AbCd... for developer@larder.shop: trigger-test\n"
        "  permissions: documents.read\n"
        "  expires: when revoked\n"
        "\n"
        "dpol_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abc\n"
        "This is the only time the token is shown. Nothing stores it, only its hash.\n"
    )

    assert token_from(printed) == "dpol_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abc"


def test_a_search_before_any_edit_is_a_call_before_editing() -> None:
    seen = watch(init(), use("1", "Read"), use("2", SEARCH), answer("2"), use("3", "Edit"))

    assert seen.called and seen.before_edit
    assert seen.call_answered
    assert seen.unusable("plugin") is None


def test_a_search_after_an_edit_still_counts_but_not_as_before() -> None:
    seen = watch(init(), use("1", "Edit"), use("2", SEARCH), answer("2"))

    assert seen.called
    assert not seen.before_edit


def test_listing_documents_is_not_consulting_them() -> None:
    seen = watch(init(), use("1", LIST), answer("1"), use("2", "Write"))

    assert not seen.called
    assert seen.dpolens_answered == 1, "it still wrote a row to the query log"


def test_another_servers_search_tool_does_not_count() -> None:
    seen = watch(init(), use("1", "mcp__other__search_policies"), answer("1"))

    assert not seen.called


def test_a_run_whose_server_failed_is_not_scored() -> None:
    seen = watch(init(status="failed"), use("1", "Edit"))

    assert seen.unusable("plugin") == "the MCP server was failed at the start"


def test_a_run_without_the_plugin_is_not_scored() -> None:
    seen = watch(init(plugins=()), use("1", "Edit"))

    unusable = seen.unusable("plugin")
    assert unusable is not None and unusable.startswith("the plugin did not load")


def test_a_run_that_never_started_is_not_scored() -> None:
    assert watch().unusable("plugin") == "Claude Code never started a session"


def test_a_failed_model_request_is_not_scored_but_a_turn_cap_is() -> None:
    failed = watch(
        init(), {"type": "result", "subtype": "error_during_execution", "is_error": True}
    )
    capped = watch(init(), {"type": "result", "subtype": "error_max_turns", "is_error": True})

    assert failed.unusable("plugin") is not None
    assert capped.unusable("plugin") is None


TASKS = [
    Task(id="a", kind="coding", should_search=True, prompt="x", reason="r", verb="log"),
    Task(id="b", kind="coding", should_search=True, prompt="x", reason="r", verb="share"),
    Task(id="c", kind="coding", should_search=False, prompt="x", reason="r"),
    Task(id="q", kind="question", should_search=True, prompt="x", reason="r"),
]


def outcome(task: str, run: int, called: bool, *, scored: bool = True, attempt: int = 1) -> Outcome:
    seen = watch(init(), *([use("1", SEARCH), answer("1")] if called else []))
    result = outcome_of(
        next(item for item in TASKS if item.id == task),
        run,
        attempt,
        "plugin",
        seen,
        stopped_at_call=called,
        clock=False,
        seconds=1.0,
        rows=1 if called else 0,
    )
    result.scored = scored
    return result


def test_the_groups_are_scored_apart() -> None:
    outcomes = [
        outcome("a", 1, True),
        outcome("a", 2, True),
        outcome("b", 1, False),
        outcome("b", 2, True),
        outcome("c", 1, False),
        outcome("c", 2, False),
        outcome("q", 1, True),
        outcome("q", 2, True),
    ]

    found = score(TASKS, outcomes)

    assert found["groups"]["should"]["rate"]["calls"] == 3
    assert found["groups"]["should"]["rate"]["runs"] == 4
    assert found["groups"]["should_not"]["rate"]["calls"] == 0
    assert found["groups"]["questions"]["rate"]["calls"] == 2
    assert found["groups"]["should"]["consistency"] == {"every": 1, "none": 0, "some": 1}
    assert found["never_searched"] == []
    assert found["query_log_mismatches"] == []


def test_only_the_scored_attempt_of_a_run_counts() -> None:
    outcomes = [
        outcome("a", 1, False, scored=False, attempt=1),
        outcome("a", 1, True, attempt=2),
        outcome("c", 1, False),
        outcome("q", 1, True),
        outcome("b", 1, True),
    ]

    found = score(TASKS, outcomes)

    assert found["groups"]["should"]["rate"]["runs"] == 2
    assert found["attempts_not_scored"] == 1


def test_a_task_that_never_searched_and_one_that_did_not_need_to_are_named() -> None:
    outcomes = [
        outcome("a", 1, False),
        outcome("b", 1, True),
        outcome("c", 1, True),
        outcome("q", 1, True),
    ]

    found = score(TASKS, outcomes)

    assert found["never_searched"] == ["a"]
    assert found["searched_without_need"] == ["c"]


def test_a_second_call_still_in_flight_is_not_a_disagreement() -> None:
    """Two searches sent together, the run stopped at the first answer: two rows, one answer."""
    seen = watch(init(), use("1", SEARCH), use("2", SEARCH), answer("1"))
    parallel = outcome_of(
        TASKS[0], 1, 1, "plugin", seen, stopped_at_call=True, clock=False, seconds=1.0, rows=2
    )

    assert agrees(parallel)


def test_rows_outside_what_was_sent_and_answered_are_a_disagreement() -> None:
    seen = watch(init(), use("1", SEARCH), use("2", SEARCH), answer("1"))

    for rows in (0, 3):
        outcome = outcome_of(
            TASKS[0],
            1,
            1,
            "plugin",
            seen,
            stopped_at_call=True,
            clock=False,
            seconds=1.0,
            rows=rows,
        )
        assert not agrees(outcome)
