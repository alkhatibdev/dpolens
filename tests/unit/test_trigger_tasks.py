"""The trigger test's task files.

The number they produce only means something if the tasks follow their rules:
half should search and half should not, the ones that should cover every way
an app handles data about a person, and no coding task names the subject. A
task that says "make this compliant" would trigger any assistant.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from run_trigger_test import TRIGGER, Task, TaskSetError, problems, read_tasks  # noqa: E402

SETS = ("tuning", "held_out")


@pytest.mark.parametrize("name", SETS)
def test_each_set_follows_the_rules(name: str) -> None:
    tasks = read_tasks(TRIGGER / f"{name}.yaml")

    assert problems(tasks) == []


def test_the_sets_are_the_sizes_the_number_depends_on() -> None:
    assert len(read_tasks(TRIGGER / "tuning.yaml")) == 20
    assert len(read_tasks(TRIGGER / "held_out.yaml")) == 30


def test_no_task_is_in_both_sets() -> None:
    """A task tuned against cannot also be one the published number rests on."""
    tuning = {task.id for task in read_tasks(TRIGGER / "tuning.yaml")}
    held_out = {task.id for task in read_tasks(TRIGGER / "held_out.yaml")}
    prompts = {task.prompt for task in read_tasks(TRIGGER / "tuning.yaml")}

    assert tuning.isdisjoint(held_out)
    assert prompts.isdisjoint(task.prompt for task in read_tasks(TRIGGER / "held_out.yaml"))


def balanced(*extra: Task) -> list[Task]:
    """A smallest set that passes, for changing one thing at a time."""
    tasks = [
        Task(id=verb, kind="coding", should_search=True, prompt=f"{verb} it", reason="r", verb=verb)
        for verb in ("collect", "store", "log", "share", "delete")
    ]
    tasks.append(Task(id="q", kind="question", should_search=True, prompt="how long?", reason="r"))
    tasks += [
        Task(id=f"no{n}", kind="coding", should_search=False, prompt="sort it", reason="r")
        for n in range(5)
    ]
    tasks.append(
        Task(id="near", kind="coding", should_search=False, near_miss=True, prompt="x", reason="r")
    )
    return [*tasks, *extra]


def test_the_smallest_set_passes() -> None:
    assert problems(balanced()) == []


@pytest.mark.parametrize(
    "prompt",
    [
        "Make signup GDPR compliant",
        "Ask for consent before tracking",
        "Update the privacy page",
        "Store it as the policies say",
        "Check the law on this",
        "Whatever is legal",
    ],
)
def test_a_coding_task_that_names_the_subject_is_refused(prompt: str) -> None:
    tasks = balanced()
    tasks[0] = replace(tasks[0], prompt=prompt)

    assert any("names the subject" in problem for problem in problems(tasks))


def test_a_question_may_name_the_subject() -> None:
    tasks = balanced()
    tasks[5] = replace(tasks[5], prompt="What does the law say about keeping orders?")

    assert problems(tasks) == []


def test_an_unbalanced_set_is_refused() -> None:
    extra = Task(id="more", kind="coding", should_search=True, prompt="x", reason="r", verb="log")

    assert any("half and half" in problem for problem in problems(balanced(extra)))


def test_a_verb_left_uncovered_is_refused() -> None:
    tasks = [task for task in balanced() if task.id != "delete"]
    tasks = [task for task in tasks if task.id != "no0"]

    assert any("covers delete" in problem for problem in problems(tasks))


def test_an_unknown_field_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "tasks.yaml"
    path.write_text(
        "tasks:\n  - id: a\n    kind: coding\n    should_search: false\n"
        "    prompt: x\n    reason: r\n    shoud_search: true\n",
        encoding="utf-8",
    )

    with pytest.raises(TaskSetError, match="unknown fields"):
        read_tasks(path)
