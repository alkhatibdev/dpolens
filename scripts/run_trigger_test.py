"""Measure how often an AI coding assistant calls DPOLens without being told to.

Each task in evals/trigger is something a developer might ask for in the Larder
app. Every run is a new container holding the AI assistant, the app, and
DPOLens installed the way a user installs it, talking to a throwaway instance
of DPOLens built from this checkout. What is measured is whether the AI
assistant calls search_policies or get_clause, and whether it does so before
it edits a file.

    uv run python scripts/run_trigger_test.py --set tuning                # the pilot
    uv run python scripts/run_trigger_test.py --set held_out --runs 3 --model <id>
    uv run python scripts/run_trigger_test.py --report <batch>            # score again

Claude Code runs are billed to a Claude subscription through a token from
`claude setup-token`, read from evals/trigger/.oauth-token, which git ignores,
or to an API account when that file is absent and ANTHROPIC_API_KEY is set.
Qwen Code runs talk to the OpenAI-compatible server named by --base-url, with
its key in OPENAI_API_KEY.
Everything a batch produces stays in evals/trigger/runs/<batch>/, also ignored,
so a batch stopped by a usage limit resumes where it stopped.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages" / "dpolens" / "src"))

from dpolens.engine.evals.score import grouped_interval  # noqa: E402

TRIGGER = REPO / "evals" / "trigger"
RUNS = TRIGGER / "runs"
TOKEN_FILE = TRIGGER / ".oauth-token"
RESULTS = REPO / "evals" / "results" / "trigger.json"


@dataclass(frozen=True)
class Client:
    """An AI coding assistant the test runs, at the version every run of a batch uses, so a
    batch measures one thing."""

    name: str
    """Its target in the run container's Dockerfile."""
    label: str
    version: str
    version_key: str
    """Where the first event of its stream gives its version."""
    edits: frozenset[str]
    """The tools that change a file."""
    bridge: str | None = None
    """A tool that calls the tool named in its input. Qwen Code keeps MCP tools out of the
    prompt until the model looks one up, and the model can call one through it as well as by
    its own name."""
    turn_cap: str | None = None
    """What it prints on reaching the turn limit, when no final event says so."""

    @property
    def image(self) -> str:
        return f"dpolens-trigger-run:{self.name}-{self.version}"

    @property
    def version_arg(self) -> str:
        return self.name.upper().replace("-", "_") + "_VERSION"


CLAUDE_CODE = Client(
    name="claude-code",
    label="Claude Code",
    version="2.1.288",
    version_key="claude_code_version",
    edits=frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"}),
)
QWEN_CODE = Client(
    name="qwen-code",
    label="Qwen Code",
    version="0.27.4",
    version_key="qwen_code_version",
    edits=frozenset({"edit", "write_file", "notebook_edit"}),
    bridge="tool_call",
    turn_cap="Reached max session turns",
)
CLIENTS = {client.name: client for client in (CLAUDE_CODE, QWEN_CODE)}

PROJECT = "dpolens-trigger"
INSTANCE_VERSION = "trigger-test"
"""What the instance's images are built as. Compose names each image after DPOLENS_VERSION,
so a build under a release's number would replace that release's images on this machine."""

INSTANCE_IMAGES = {
    "api": f"ghcr.io/alkhatibdev/dpolens:{INSTANCE_VERSION}",
    "setup": f"ghcr.io/alkhatibdev/dpolens:{INSTANCE_VERSION}",
    "mcp": f"ghcr.io/alkhatibdev/dpolens-mcp:{INSTANCE_VERSION}",
}
LAWS = ("gdpr",)
"""What the instance's searches cover, as in the published runs. An instance searches nothing
until somebody chooses its laws, and refuses every search until then."""

NETWORK = f"{PROJECT}_default"
MCP_URL = "http://mcp:8765/mcp"
DEVELOPER = "developer@larder.shop"
OPENAI_KEY = "OPENAI_API_KEY"
"""The variable that holds the model server's key, on this machine and in the container."""

SAMPLING: dict[str, Callable[[str], float | int]] = {
    "temperature": float,
    "top_p": float,
    "top_k": int,
    "presence_penalty": float,
    "frequency_penalty": float,
    "repetition_penalty": float,
}
"""The sampling values Qwen Code sends with every request when its settings name them."""

SETS = ("tuning", "held_out")
SETUPS = ("plugin", "mcp-only")
PREFIXES = {"plugin": "mcp__plugin_dpolens_dpolens__", "mcp-only": "mcp__dpolens__"}
SERVERS = {"plugin": "plugin:dpolens:dpolens", "mcp-only": "dpolens"}

COUNTED = ("search_policies", "get_clause")
"""The tools that return clause text. Listing documents is not consulting them."""
QUESTIONS = {"search_policies": "query", "get_clause": "key"}
"""What each counted tool needs to be asked. A call without it is refused by the server's
schema, whatever the instance holds."""

VERBS = ("collect", "store", "log", "share", "delete")
KINDS = ("coding", "question")

GIVEAWAYS = re.compile(
    r"personal data|privacy|gdpr|polic(?:y|ies)|consent|\blaws?\b|lawful|legal"
    r"|compliant|compliance|regulat",
    re.IGNORECASE,
)
"""Words a coding task may not use: a task that names the subject tests nothing."""

MAX_TURNS = 25
CLOCK_SECONDS = 600
ATTEMPTS = 3
FAILURES_BEFORE_STOPPING = 2
STARTS = 3
"""Building the instance asks registries about base images, and a network blip fails it."""

BAKED_IN = {
    "api": ("pyproject.toml", "uv.lock", "alembic.ini", "packages", "packs"),
    "setup": ("pyproject.toml", "uv.lock", "alembic.ini", "packages", "packs"),
    "mcp": ("pyproject.toml", "uv.lock", "packages/dpolens/pyproject.toml", "packages/dpolens-mcp"),
}
"""What each image copies from the checkout, under /opt/dpolens."""

ENGINE_SCRIPTS = {
    "/usr/local/bin/setup.sh": "deploy/dpolens/setup.sh",
    "/usr/local/bin/serve.sh": "deploy/dpolens/serve.sh",
}


class TaskSetError(Exception):
    """A task file that would make the number mean something other than it says."""


@dataclass(frozen=True)
class Task:
    id: str
    kind: str
    should_search: bool
    prompt: str
    reason: str
    verb: str | None = None
    near_miss: bool = False
    note: str | None = None

    @property
    def group(self) -> str:
        if self.kind == "question":
            return "questions"
        return "should" if self.should_search else "should_not"


FIELDS = frozenset(Task.__dataclass_fields__)


def read_tasks(path: Path) -> list[Task]:
    """Every task in one file, refusing a file that would not mean what it says."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    entries = raw.get("tasks") if isinstance(raw, dict) else None
    if not isinstance(entries, list) or not entries:
        raise TaskSetError(f"{path.name}: no tasks")

    tasks = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise TaskSetError(f"{path.name}: every task is a mapping")
        unknown = set(entry) - FIELDS
        if unknown:
            raise TaskSetError(f"{path.name}: {entry.get('id')}: unknown fields {sorted(unknown)}")
        try:
            tasks.append(Task(**entry))
        except TypeError as error:
            raise TaskSetError(f"{path.name}: {entry.get('id')}: {error}") from error

    found = problems(tasks)
    if found:
        raise TaskSetError(f"{path.name}:\n  " + "\n  ".join(found))
    return tasks


def problems(tasks: Sequence[Task]) -> list[str]:
    """What is wrong with a set, as sentences. Empty when the set can be run."""
    found = []
    seen: set[str] = set()
    for task in tasks:
        if task.id in seen:
            found.append(f"{task.id}: the id is used twice")
        seen.add(task.id)

        if task.kind not in KINDS:
            found.append(f"{task.id}: kind is {task.kind!r}, expected one of {KINDS}")
        if not task.prompt.strip() or not task.reason.strip():
            found.append(f"{task.id}: needs a prompt and a reason")
        if task.kind == "question" and not task.should_search:
            found.append(f"{task.id}: a question about the rules should always search")
        if task.kind == "coding" and (word := GIVEAWAYS.search(task.prompt)):
            found.append(f"{task.id}: the prompt names the subject ({word.group(0)!r})")
        if task.kind == "coding" and task.should_search and not task.verb:
            found.append(f"{task.id}: a task that should search says what it does to the data")
        if not task.should_search and task.verb:
            found.append(f"{task.id}: a task that should not search has no verb")
        if task.near_miss and task.should_search:
            found.append(f"{task.id}: a near miss is a task that should not search")

    should = sum(task.should_search for task in tasks)
    if should * 2 != len(tasks):
        found.append(
            f"{should} tasks should search and {len(tasks) - should} should not; "
            "a set is half and half"
        )

    covered = {task.verb for task in tasks if task.group == "should"}
    missing = [verb for verb in VERBS if verb not in covered]
    if missing:
        found.append(f"no task that should search covers {', '.join(missing)}")
    if not any(task.near_miss for task in tasks):
        found.append("no near misses among the tasks that should not search")
    if not any(task.kind == "question" for task in tasks):
        found.append("no questions about the rules")
    return found


def blocks(event: dict[str, Any]) -> Iterable[dict[str, Any]]:
    message = event.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):
        yield from (block for block in content if isinstance(block, dict))


@dataclass
class Observation:
    """What one run's stream of events showed."""

    prefix: str
    server: str
    client: Client = CLAUDE_CODE
    model: str | None = None
    version: str | None = None
    server_status: str | None = None
    plugins: tuple[str, ...] = ()
    plugin_errors: tuple[str, ...] = ()
    tools: list[str] = field(default_factory=list)
    first_call: int | None = None
    """Where in `tools` the first counted call is."""
    first_edit: int | None = None
    turn_capped: bool = False
    call_answered: bool = False
    call_failed: bool = False
    """Whether the first counted call came back as an error, which no setup should cause."""
    call_asked: bool = True
    """Whether the first counted call carried its question. One sent with none is the AI
    assistant's slip: no instance can answer it, and the decision to search was still made."""
    dpolens_answered: int = 0
    """DPOLens calls that came back, each of which wrote one row to the query log."""
    retries: list[str] = field(default_factory=list)
    result: dict[str, Any] | None = None
    started: bool = False
    retrying: bool = False
    """Whether the last thing that happened was a failed request to the model."""
    _names: dict[str, str] = field(default_factory=dict)
    _call_id: str | None = None
    _registered: tuple[str, ...] = ()

    def read(self, line: str) -> None:
        """One line of a run's output: an event, or text printed outside the events."""
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            if self.client.turn_cap and line.startswith(self.client.turn_cap):
                self.turn_capped = True
            return
        if isinstance(event, dict):
            self.see(event)

    def see(self, event: dict[str, Any]) -> None:
        kind, subtype = event.get("type"), event.get("subtype")
        if kind == "system" and subtype == "init":
            self._init(event)
        elif kind == "system" and subtype == "api_retry":
            self.retries.append(str(event.get("error")))
            self.retrying = True
        elif kind == "assistant":
            self.retrying = False
            self._assistant(event)
        elif kind == "user":
            self._user(event)
        elif kind == "result":
            self.result = event

    def _init(self, event: dict[str, Any]) -> None:
        self.started = True
        self.model = event.get("model")
        self.version = event.get(self.client.version_key)
        self._registered = tuple(str(name) for name in event.get("tools") or [])
        for server in event.get("mcp_servers") or []:
            if isinstance(server, dict) and server.get("name") == self.server:
                self.server_status = server.get("status")
        self.plugins = tuple(
            str(plugin.get("name"))
            for plugin in event.get("plugins") or []
            if isinstance(plugin, dict)
        )
        self.plugin_errors = tuple(
            str(error.get("message", error)) if isinstance(error, dict) else str(error)
            for error in event.get("plugin_errors") or []
        )

    def _assistant(self, event: dict[str, Any]) -> None:
        for block in blocks(event):
            if block.get("type") != "tool_use":
                continue
            name = self._target(block)
            self._names[str(block.get("id"))] = name
            self.tools.append(name)
            if self.first_call is None and self.counts(name):
                self.first_call = len(self.tools) - 1
                self._call_id = str(block.get("id"))
                self.call_asked = self._asked(block, name)
            if self.first_edit is None and name in self.client.edits:
                self.first_edit = len(self.tools) - 1

    def _target(self, block: dict[str, Any]) -> str:
        """The tool a call runs. Through the bridge, it is the tool named, resolved the way
        Qwen Code resolves it: the exact name, or else the only one differing in case."""
        name = str(block.get("name", ""))
        given = block.get("input")
        named = given.get("name") if isinstance(given, dict) else None
        if name != self.client.bridge or not isinstance(named, str):
            return name
        if named in self._registered:
            return named
        same = {tool for tool in self._registered if tool.lower() == named.lower()}
        return same.pop() if len(same) == 1 else named

    def _asked(self, block: dict[str, Any], name: str) -> bool:
        """Whether a counted call named its question. A call through the bridge carries its
        arguments in its own shape, so it is taken as asked."""
        given = block.get("input")
        if block.get("name") != name or not isinstance(given, dict):
            return True
        question = given.get(QUESTIONS[name.removeprefix(self.prefix)])
        return isinstance(question, str) and bool(question.strip())

    def _user(self, event: dict[str, Any]) -> None:
        for block in blocks(event):
            if block.get("type") != "tool_result":
                continue
            use = str(block.get("tool_use_id"))
            if use == self._call_id:
                self.call_answered = True
                self.call_failed = bool(block.get("is_error"))
            if self._names.get(use, "").startswith(self.prefix):
                self.dpolens_answered += 1

    def counts(self, name: str) -> bool:
        return name in {self.prefix + tool for tool in COUNTED}

    @property
    def called(self) -> bool:
        return self.first_call is not None

    @property
    def before_edit(self) -> bool:
        return self.first_call is not None and (
            self.first_edit is None or self.first_call < self.first_edit
        )

    def unusable(self, setup: str) -> str | None:
        """Why this run could not have called DPOLens, if it could not."""
        if not self.started:
            return f"{self.client.label} never started a session"
        if setup == "plugin" and ("dpolens" not in self.plugins or self.plugin_errors):
            return f"the plugin did not load: {'; '.join(self.plugin_errors) or 'not listed'}"
        if self.server_status not in ("connected", "pending"):
            return f"the MCP server was {self.server_status or 'missing'} at the start"
        if self.called:
            return None
        if (
            self.server_status == "connected"
            and self._registered
            and not any(tool.startswith(self.prefix) for tool in self._registered)
        ):
            return "the MCP server connected, but none of its tools reached the AI assistant"
        if self.retrying:
            return f"the model requests kept failing ({', '.join(sorted(set(self.retries)))})"
        if self.result and self.result.get("is_error") and capped_by(self.result) is None:
            error = self.result.get("error")
            reason = (
                self.result.get("result")
                or (error.get("message") if isinstance(error, dict) else None)
                or self.result.get("subtype")
            )
            return f"the run failed: {reason}"
        return None

    @property
    def capped(self) -> str | None:
        """Which limit ended the run, if one did."""
        return "turns" if self.turn_capped else capped_by(self.result or {})

    def settled(self, stop_at_edit: bool) -> bool:
        """Whether the run's outcome is known: its first call came back or, when runs stop at
        the first edit, it edited before calling."""
        return self.call_answered or (
            stop_at_edit and self.first_edit is not None and self.first_call is None
        )


def capped_by(result: dict[str, Any]) -> str | None:
    """Which limit ended a run, read from Claude Code's final event."""
    subtype = str(result.get("subtype", ""))
    if "max_turns" in subtype:
        return "turns"
    if "budget" in subtype:
        return "budget"
    return None


@dataclass
class Outcome:
    """One attempt at one run, as it is written to a batch's outcomes file."""

    task: str
    run: int
    attempt: int
    setup: str
    scored: bool
    called: bool
    before_edit: bool
    stopped_at_call: bool
    capped: str | None
    unusable: str | None
    model: str | None
    version: str | None
    turns: int | None
    cost_usd: float | None
    seconds: float
    tools: list[str]
    dpolens_calls: int
    query_log_rows: int | None
    search_failed: bool = False
    """Whether the search that decided the run came back as an error although it asked
    something, so the instance could not answer. Batches recorded before this was noted read as
    False."""
    search_asked_nothing: bool = False
    """Whether the search that decided the run carried no question, which the server refuses.
    It counts as a search: what is measured is the decision to look the rules up."""
    stopped_at_edit: bool = False
    """Whether the run was ended at its first edit, which only `--stop-at-edit` does."""


def outcome_of(
    task: Task,
    run: int,
    attempt: int,
    setup: str,
    seen: Observation,
    *,
    stopped_at_call: bool,
    clock: bool,
    seconds: float,
    rows: int | None,
    stopped_at_edit: bool = False,
) -> Outcome:
    unusable = seen.unusable(setup)
    result = seen.result or {}
    capped = "clock" if clock else seen.capped if not seen.called else None
    return Outcome(
        task=task.id,
        run=run,
        attempt=attempt,
        setup=setup,
        scored=unusable is None,
        called=seen.called,
        before_edit=seen.before_edit,
        stopped_at_call=stopped_at_call,
        capped=capped,
        unusable=unusable,
        model=seen.model,
        version=seen.version,
        turns=result.get("num_turns"),
        cost_usd=result.get("total_cost_usd"),
        seconds=round(seconds, 1),
        tools=seen.tools,
        dpolens_calls=seen.dpolens_answered,
        query_log_rows=rows,
        search_failed=seen.call_failed and seen.call_asked,
        search_asked_nothing=seen.called and not seen.call_asked,
        stopped_at_edit=stopped_at_edit,
    )


@dataclass(frozen=True)
class Rate:
    runs: int
    calls: int
    low: float
    high: float

    @property
    def share(self) -> float:
        return self.calls / self.runs if self.runs else 0.0


def rate(runs_by_task: Sequence[Sequence[bool]]) -> Rate:
    groups = [list(runs) for runs in runs_by_task if runs]
    interval = grouped_interval(groups)
    return Rate(
        runs=sum(len(group) for group in groups),
        calls=sum(sum(group) for group in groups),
        low=interval.low,
        high=interval.high,
    )


def consistency(runs_by_task: Sequence[Sequence[bool]]) -> dict[str, int]:
    """How many tasks called in every run, in none, or in some."""
    counts = {"every": 0, "none": 0, "some": 0}
    for runs in runs_by_task:
        if not runs:
            continue
        counts["every" if all(runs) else "none" if not any(runs) else "some"] += 1
    return counts


def agrees(outcome: Outcome) -> bool:
    """Whether the query log wrote what the stream says was asked.

    A run stopped at its first answer can leave a second call in flight: the
    server has written its row, and the answer never reached the stream. So the
    rows fall between the calls answered and the calls sent.
    """
    if outcome.query_log_rows is None:
        return True
    sent = sum(name.startswith(PREFIXES[outcome.setup]) for name in outcome.tools)
    return outcome.dpolens_calls <= outcome.query_log_rows <= sent


def score(tasks: Sequence[Task], outcomes: Sequence[Outcome]) -> dict[str, Any]:
    """The numbers a batch supports, from the scored attempt of each run."""
    final: dict[tuple[str, int], Outcome] = {}
    for outcome in outcomes:
        if outcome.scored:
            final[(outcome.task, outcome.run)] = outcome

    def runs_of(task: Task) -> list[Outcome]:
        return sorted(
            (outcome for (task_id, _), outcome in final.items() if task_id == task.id),
            key=lambda outcome: outcome.run,
        )

    groups: dict[str, Any] = {}
    for group in ("should", "should_not", "questions"):
        members = [task for task in tasks if task.group == group]
        called = [[run.called for run in runs_of(task)] for task in members]
        entry: dict[str, Any] = {
            "tasks": len(members),
            "rate": asdict(rate(called)),
            "consistency": consistency(called),
        }
        if group == "should":
            entry["before_edit"] = asdict(
                rate([[run.before_edit for run in runs_of(task)] for task in members])
            )
        groups[group] = entry

    scored = list(final.values())
    costs = [outcome.cost_usd for outcome in scored if outcome.cost_usd is not None]
    searched = {task.id: [run.called for run in runs_of(task)] for task in tasks}
    return {
        "groups": groups,
        "runs_scored": len(scored),
        "attempts_not_scored": sum(not outcome.scored for outcome in outcomes),
        "capped": sum(outcome.capped is not None for outcome in scored),
        "query_log_mismatches": [
            f"{outcome.task}#{outcome.run}" for outcome in scored if not agrees(outcome)
        ],
        "searches_that_failed": [
            f"{outcome.task}#{outcome.run}" for outcome in scored if outcome.search_failed
        ],
        "searches_without_a_question": [
            f"{outcome.task}#{outcome.run}" for outcome in scored if outcome.search_asked_nothing
        ],
        "estimated_cost_usd": round(sum(costs), 2),
        "never_searched": [
            task.id
            for task in tasks
            if task.should_search and searched[task.id] and not any(searched[task.id])
        ],
        "searched_without_need": [
            task.id for task in tasks if not task.should_search and any(searched[task.id])
        ],
        "models": sorted({str(outcome.model) for outcome in scored}),
        "versions": sorted({str(outcome.version) for outcome in scored}),
    }


def print_score(found: dict[str, Any], client: Client) -> None:
    labels = {
        "should": "coding tasks that should search",
        "should_not": "coding tasks that should not",
        "questions": "questions about the rules",
    }
    print()
    for group, label in labels.items():
        entry = found["groups"][group]
        share = entry["rate"]
        runs = share["runs"]
        if not runs:
            continue
        print(
            f"  {label:34} searched {share['calls']:3} of {runs:3} runs "
            f"({share['calls'] / runs:.2f}, {share['low']:.2f} to {share['high']:.2f})"
        )
        if group == "should":
            early = entry["before_edit"]
            print(f"  {'':34} before the first edit {early['calls']:3} of {runs:3}")
        every = entry["consistency"]
        print(
            f"  {'':34} tasks: every run {every['every']}, "
            f"none {every['none']}, some {every['some']}"
        )
    print()
    print(
        f"  runs scored {found['runs_scored']}, capped {found['capped']}, "
        f"attempts not scored {found['attempts_not_scored']}"
    )
    cost = found["estimated_cost_usd"]
    print(
        (f"  estimated cost {cost} USD, " if cost else "  ")
        + f"model {', '.join(found['models'])}, {client.label} {', '.join(found['versions'])}"
    )
    for key, label in (
        ("never_searched", "never searched"),
        ("searched_without_need", "searched without needing to"),
        ("query_log_mismatches", "query log disagrees with the stream for"),
        ("searches_that_failed", "a search came back as an error in"),
        ("searches_without_a_question", "a search asked no question in"),
    ):
        if found[key]:
            print(f"  {label}: {', '.join(found[key])}")


def docker(*args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], text=True, check=True, **kwargs)


def token_from(printed: str) -> str:
    """The token `dpolens token create` prints on a line of its own.

    The line before it names the token by its prefix, which also starts with
    `dpol_` and is not the token.
    """
    found = re.search(r"^(dpol_[A-Za-z0-9_\-]{20,})$", printed, re.MULTILINE)
    if found is None:
        raise RuntimeError("the instance did not print a token")
    return found.group(1)


class Instance:
    """A throwaway DPOLens built from this checkout, reachable as `mcp` on its network."""

    def __init__(self) -> None:
        self.env = {
            **os.environ,
            "DPOLENS_OWNER_PASSWORD": secrets.token_hex(24),
            "DPOLENS_APP_PASSWORD": secrets.token_hex(24),
            "DPOLENS_API_PORT": "18000",
            "DPOLENS_MCP_PORT": "18765",
            "DPOLENS_MCP_ALLOWED_HOSTS": '["mcp:8765"]',
            "DPOLENS_VERSION": INSTANCE_VERSION,
        }
        self.token = ""

    def compose(self, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["docker", "compose", "-p", PROJECT, *args],
            cwd=REPO,
            env=self.env,
            text=True,
            check=True,
            **kwargs,
        )

    def start(self, build: bool = True) -> None:
        print("starting a throwaway DPOLens instance", flush=True)
        if build:
            self._retry("up", "-d", "--build", "--quiet-pull")
        else:
            # The database image copies nothing from the checkout and its base
            # comes from Docker Hub, so it is built either way.
            self._retry("build", "--quiet", "db")
            stale = stale_images()
            if stale:
                raise RuntimeError(
                    "the images do not hold this checkout, so they have to be built: "
                    + ", ".join(stale[:10])
                )
            self.compose("up", "-d", "--no-build", capture_output=True)
        self._wait_until_healthy(("api", "mcp"), timeout=900)
        self.compose(
            "exec",
            "-T",
            "api",
            "dpolens",
            "user",
            "create",
            "--email",
            DEVELOPER,
            "--name",
            "Larder Developer",
            "--role",
            "Developer",
            capture_output=True,
        )
        created = self.compose(
            "exec",
            "-T",
            "api",
            "dpolens",
            "token",
            "create",
            "--email",
            DEVELOPER,
            "--name",
            "trigger-test",
            "--permission",
            "documents.read",
            capture_output=True,
        )
        self.token = token_from(created.stdout)
        self.compose("exec", "-T", "api", "dpolens", "laws", "select", *LAWS, capture_output=True)

    def _retry(self, *args: str) -> None:
        """A Compose command that a network blip can fail, tried a few times."""
        for attempt in range(1, STARTS + 1):
            try:
                self.compose(*args, capture_output=True)
                return
            except subprocess.CalledProcessError as error:
                if attempt == STARTS:
                    print(error.stdout, error.stderr, sep="\n")
                    raise
                print(f"  the instance did not start, trying again ({attempt} of {STARTS})")
                time.sleep(30)

    def _wait_until_healthy(self, services: Sequence[str], timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            listed = self.compose("ps", "--format", "json", capture_output=True).stdout.strip()
            rows = (
                json.loads(listed)
                if listed.startswith("[")
                else [json.loads(line) for line in listed.splitlines() if line.strip()]
            )
            health = {row.get("Service"): row.get("Health") for row in rows}
            if all(health.get(service) == "healthy" for service in services):
                return
            time.sleep(3)
        raise RuntimeError(f"{', '.join(services)} did not become healthy in {timeout:.0f}s")

    def rows(self) -> int | None:
        """How many questions the query log holds, for checking the stream against."""
        status = self.compose(
            "exec", "-T", "api", "dpolens", "queries", "status", capture_output=True
        ).stdout
        found = re.search(r"(\d+) entries kept", status)
        return int(found.group(1)) if found else None

    def stop(self) -> None:
        self.compose("down", "-v", "--remove-orphans", capture_output=True)


def digests(listing: str) -> dict[str, str]:
    """Paths and their SHA-256, from what `sha256sum` prints."""
    found = {}
    for line in listing.splitlines():
        digest, _, path = line.partition("  ")
        if path:
            found[path] = digest
    return found


def differing(expected: dict[str, str], found: dict[str, str]) -> list[str]:
    """The files whose contents are not what the checkout holds, missing ones included."""
    return sorted(path for path, digest in expected.items() if found.get(path) != digest)


def stale_images() -> list[str]:
    """Every file an instance image holds differently from this checkout.

    Starting from images already built is only a measurement of this checkout
    if they were built from it, which a timestamp cannot show: a rebuild that
    changes nothing keeps the old date, and so does a build from files that
    were committed later.
    """
    stale = []
    for service, paths in BAKED_IN.items():
        tracked = subprocess.run(
            ["git", "ls-files", "--", *paths], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.split()
        inside = {f"/opt/dpolens/{name}": name for name in tracked}
        if service in ("api", "setup"):
            inside.update(ENGINE_SCRIPTS)
        expected = {
            path: hashlib.sha256((REPO / name).read_bytes()).hexdigest()
            for path, name in inside.items()
        }
        listing = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--entrypoint",
                "sha256sum",
                INSTANCE_IMAGES[service],
                *inside,
            ],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        stale += [f"{service}:{inside[path]}" for path in differing(expected, digests(listing))]

    return stale


def build_image(client: Client) -> None:
    print(f"building the run container with {client.label} {client.version}", flush=True)
    docker(
        "build",
        "--quiet",
        "--target",
        client.name,
        "-t",
        client.image,
        "--build-arg",
        f"{client.version_arg}={client.version}",
        "-f",
        str(TRIGGER / "container" / "Dockerfile"),
        str(TRIGGER),
        stdout=subprocess.DEVNULL,
    )


def marketplace(batch: Path) -> Path:
    """The plugin and its marketplace file, and nothing else from this repository."""
    target = batch / "marketplace"
    shutil.rmtree(target, ignore_errors=True)
    (target / ".claude-plugin").mkdir(parents=True)
    shutil.copy2(REPO / ".claude-plugin" / "marketplace.json", target / ".claude-plugin")
    shutil.copytree(REPO / "clients" / "claude-code", target / "clients" / "claude-code")
    return target


def qwen_settings(
    model: str,
    base_url: str,
    token: str,
    sampling: dict[str, float | int] | None,
    context_window: int | None,
) -> dict[str, Any]:
    """Qwen Code's settings for a batch: the model at its server, and DPOLens as the entry
    `qwen mcp add` writes. Nothing reports usage, fetches a model catalogue or updates
    Qwen Code, so a run talks to the model server and DPOLens only."""
    generation: dict[str, Any] = {}
    if sampling:
        generation["samplingParams"] = sampling
    if context_window:
        generation["contextWindowSize"] = context_window
    provider = {
        "id": model,
        "name": model,
        "baseUrl": base_url,
        "envKey": OPENAI_KEY,
        "generationConfig": generation,
    }
    return {
        "general": {"enableAutoUpdate": False},
        "privacy": {"usageStatisticsEnabled": False},
        "security": {"auth": {"selectedType": "openai"}},
        "model": {"name": model, "catalogRefresh": False},
        "modelProviders": {"openai": [provider]},
        "mcpServers": {
            "dpolens": {"httpUrl": MCP_URL, "headers": {"Authorization": f"Bearer {token}"}}
        },
    }


def prepare_profile(
    client: Client, args: argparse.Namespace, token: str, volume: str, plugin_source: Path
) -> None:
    """Install DPOLens into an empty profile once, for every run of the batch to copy."""
    values: dict[str, Any]
    if client is QWEN_CODE:
        values = qwen_settings(args.model, args.base_url, token, args.sampling, args.context_window)
    elif args.setup == "plugin":
        values = {"url": MCP_URL, "token": token}
    else:
        values = {"type": "http", "url": MCP_URL, "headers": {"Authorization": f"Bearer {token}"}}
    subprocess.run(["docker", "volume", "rm", "-f", volume], capture_output=True, check=False)
    docker(
        "run",
        "--rm",
        "-i",
        "--network",
        NETWORK,
        "-v",
        f"{volume}:/home/node/profile",
        "-v",
        f"{plugin_source}:/marketplace:ro",
        client.image,
        "prepare-profile.sh",
        args.setup,
        input=json.dumps(values),
        capture_output=True,
    )


def read_lines(stream: Any, lines: queue.Queue[str | None]) -> None:
    for line in stream:
        lines.put(line)
    lines.put(None)


def run_once(
    task: Task,
    client: Client,
    setup: str,
    model: str | None,
    budget: float | None,
    volume: str,
    plugin_source: Path,
    credential: tuple[str, str],
    transcript: Path,
    stop_at_edit: bool = False,
) -> tuple[Observation, bool, bool, bool, float]:
    """One container, one prompt. Returns what was seen, and why it ended: at the first call
    answered, at the first edit, or on the clock."""
    name = f"{PROJECT}-run-{secrets.token_hex(4)}"
    env = {
        **os.environ,
        credential[0]: credential[1],
        "TASK_PROMPT": task.prompt,
        "TASK_MODEL": model or "",
        "TASK_MAX_TURNS": str(MAX_TURNS),
        "TASK_MAX_BUDGET_USD": "" if budget is None else str(budget),
    }
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--network",
        NETWORK,
        "-e",
        credential[0],
        "-e",
        "TASK_PROMPT",
        "-e",
        "TASK_MODEL",
        "-e",
        "TASK_MAX_TURNS",
        "-e",
        "TASK_MAX_BUDGET_USD",
        "-v",
        f"{volume}:/home/node/profile:ro",
        "-v",
        f"{plugin_source}:/marketplace:ro",
        # A model server on this machine is host.docker.internal, a name Docker Desktop gives
        # every container and Docker on Linux has to be told.
        *(["--add-host", "host.docker.internal:host-gateway"] if client is QWEN_CODE else []),
        client.image,
        "run-task.sh",
    ]
    seen = Observation(prefix=PREFIXES[setup], server=SERVERS[setup], client=client)
    started = time.monotonic()
    stopped_at_call = stopped_at_edit = clock = False

    process = subprocess.Popen(
        command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    lines: queue.Queue[str | None] = queue.Queue()
    threading.Thread(target=read_lines, args=(process.stdout, lines), daemon=True).start()

    with transcript.open("w", encoding="utf-8") as record:
        while True:
            remaining = CLOCK_SECONDS - (time.monotonic() - started)
            if remaining <= 0:
                clock = True
                break
            try:
                line = lines.get(timeout=remaining)
            except queue.Empty:
                clock = True
                break
            if line is None:
                break
            record.write(line)
            seen.read(line)
            if seen.settled(stop_at_edit):
                stopped_at_call = seen.call_answered
                stopped_at_edit = not stopped_at_call
                break

    if stopped_at_call or stopped_at_edit or clock:
        subprocess.run(["docker", "kill", name], capture_output=True, check=False)
    process.wait(timeout=60)
    return seen, stopped_at_call, stopped_at_edit, clock, time.monotonic() - started


def attempt_run(
    task: Task,
    run: int,
    attempt: int,
    args: argparse.Namespace,
    instance: Instance,
    volume: str,
    plugin_source: Path,
    credential: tuple[str, str],
    batch: Path,
) -> Outcome:
    before = instance.rows()
    seen, at_call, at_edit, clock, seconds = run_once(
        task,
        CLIENTS[args.client],
        args.setup,
        args.model,
        args.max_budget_usd,
        volume,
        plugin_source,
        credential,
        batch / "transcripts" / f"{task.id}.{run}.{attempt}.jsonl",
        args.stop_at_edit,
    )
    after = instance.rows()
    rows = after - before if before is not None and after is not None else None
    return outcome_of(
        task,
        run,
        attempt,
        args.setup,
        seen,
        stopped_at_call=at_call,
        clock=clock,
        seconds=seconds,
        rows=rows,
        stopped_at_edit=at_edit,
    )


def verdict(outcome: Outcome) -> str:
    if not outcome.scored:
        return f"not scored, {outcome.unusable}"
    if outcome.called:
        return "searched" + ("" if outcome.before_edit else " after editing")
    if outcome.stopped_at_edit:
        return f"edited without searching, {outcome.seconds:.0f}s"
    return f"did not search ({outcome.capped or 'finished'}), {outcome.seconds:.0f}s"


def read_outcomes(path: Path) -> list[Outcome]:
    if not path.is_file():
        return []
    return [
        Outcome(**json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def credential_for_runs(client: Client) -> tuple[str, str] | None:
    """The variable the AI assistant authenticates with, and its value."""
    if client is QWEN_CODE:
        key = os.environ.get(OPENAI_KEY)
        return (OPENAI_KEY, key) if key else None
    if TOKEN_FILE.is_file():
        return "CLAUDE_CODE_OAUTH_TOKEN", TOKEN_FILE.read_text(encoding="utf-8").strip()
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "ANTHROPIC_API_KEY", os.environ["ANTHROPIC_API_KEY"]
    return None


def refusal(args: argparse.Namespace) -> str | None:
    """Why the options cannot make a batch, when they cannot."""
    client = CLIENTS[args.client]
    if client is QWEN_CODE:
        if args.setup == "plugin":
            return "the plugin is Claude Code's: Qwen Code runs use --setup mcp-only"
        if not args.model or not args.base_url:
            return "Qwen Code runs need --model and --base-url: the model, at the server holding it"
        if args.max_budget_usd is not None:
            return "--max-budget-usd is Claude Code's limit, and Qwen Code has none"
    elif args.base_url or args.sampling or args.context_window:
        return "--base-url, --sampling and --context-window are for Qwen Code runs"
    if args.set == "held_out" and not args.model:
        return "a held-out batch is published, so its model is pinned: pass --model"
    return None


def run_batch(args: argparse.Namespace) -> int:
    client = CLIENTS[args.client]
    args.setup = args.setup or ("plugin" if client is CLAUDE_CODE else "mcp-only")
    refused = refusal(args)
    if refused:
        print(refused)
        return 2

    tasks = read_tasks(TRIGGER / f"{args.set}.yaml")
    if args.tasks:
        wanted = set(args.tasks.split(","))
        tasks = [task for task in tasks if task.id in wanted]

    planned = len(tasks) * args.runs
    if planned > args.max_runs:
        print(f"{planned} runs planned, more than --max-runs {args.max_runs}; nothing started")
        return 2
    credential = credential_for_runs(client)
    if credential is None:
        print(
            f"set {OPENAI_KEY} to the key of the server at --base-url, or to any value when "
            "it needs none"
            if client is QWEN_CODE
            else f"no subscription token at {TOKEN_FILE}: run `claude setup-token` and save it "
            "there, or set ANTHROPIC_API_KEY to bill an API account instead"
        )
        return 2

    named = (
        args.setup
        if client is CLAUDE_CODE
        else f"{client.name}-{re.sub(r'[^A-Za-z0-9._-]+', '-', args.model)}"
    )
    batch_id = args.batch or f"{args.set}-{named}-{datetime.now(UTC):%Y%m%d-%H%M}"
    batch = RUNS / batch_id
    (batch / "transcripts").mkdir(parents=True, exist_ok=True)
    outcomes_file = batch / "outcomes.jsonl"
    outcomes = read_outcomes(outcomes_file)
    meta_file = batch / "batch.json"
    this_run = {
        "started": datetime.now(UTC).isoformat(timespec="seconds"),
        **checkout(),
        "instance": (
            "reused images holding the same files as the checkout"
            if args.reuse_images
            else "built from the checkout"
        ),
    }
    asked = conditions(args)
    if meta_file.is_file():
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        differ = [key for key, value in asked.items() if recorded(meta, key) != value]
        if differ:
            print(
                f"batch {batch_id} was started with other {', '.join(differ)}: resume it with those"
            )
            return 2
        meta.setdefault("resumed", []).append(this_run)
    else:
        meta = {
            **{key: value for key, value in asked.items() if value is not None or key == "model"},
            "client_version": client.version,
            **({"claude_code": client.version} if client is CLAUDE_CODE else {}),
            "runs_per_task": args.runs,
            "max_turns": MAX_TURNS,
            "max_budget_usd": args.max_budget_usd,
            **this_run,
        }
    meta_file.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(
        f"batch {batch_id}: {len(tasks)} tasks, {args.runs} runs each, "
        f"{client.label}, setup {args.setup}"
    )

    build_image(client)
    instance = Instance()
    volume = f"{PROJECT}-profile-{client.name}-{args.setup}"
    failures = 0
    try:
        instance.start(build=not args.reuse_images)
        plugin_source = marketplace(batch)
        prepare_profile(client, args, instance.token, volume, plugin_source)

        for task in tasks:
            for run in range(1, args.runs + 1):
                while failures < FAILURES_BEFORE_STOPPING:
                    attempts = [o for o in outcomes if o.task == task.id and o.run == run]
                    if any(o.scored for o in attempts) or len(attempts) >= ATTEMPTS:
                        break
                    outcome = attempt_run(
                        task,
                        run,
                        len(attempts) + 1,
                        args,
                        instance,
                        volume,
                        plugin_source,
                        credential,
                        batch,
                    )
                    outcomes.append(outcome)
                    with outcomes_file.open("a", encoding="utf-8") as record:
                        record.write(json.dumps(asdict(outcome)) + "\n")
                    print(f"  {task.id} #{run}: {verdict(outcome)}", flush=True)
                    failures = 0 if outcome.scored else failures + 1

        if failures >= FAILURES_BEFORE_STOPPING:
            print(
                "stopped: runs keep failing, for the reason printed above. A usage limit "
                f"clears with time; run the same command with --batch {batch_id} to resume."
            )
    finally:
        if not args.keep_instance:
            instance.stop()
        subprocess.run(["docker", "volume", "rm", "-f", volume], capture_output=True, check=False)

    found = score(tasks, outcomes)
    (batch / "score.json").write_text(json.dumps(found, indent=2) + "\n", encoding="utf-8")
    print_score(found, client)
    return 0


def conditions(args: argparse.Namespace) -> dict[str, Any]:
    """What a batch measures under, which every run of it shares, resumed ones included."""
    return {
        "set": args.set,
        "setup": args.setup,
        "model": args.model,
        "client": args.client,
        "base_url": args.base_url,
        "sampling": args.sampling,
        "context_window": args.context_window,
        "stop_at_edit": args.stop_at_edit or None,
    }


def recorded(meta: dict[str, Any], key: str) -> Any:
    """A condition as a batch recorded it. Batches from before there was a choice of client
    ran Claude Code."""
    return meta.get(key, CLAUDE_CODE.name if key == "client" else None)


def checkout() -> dict[str, Any]:
    """The commit a batch ran from, and whether tracked files had changed since."""

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
        ).stdout.strip()

    return {
        "commit": git("rev-parse", "--short", "HEAD"),
        "uncommitted_changes": bool(git("status", "--porcelain", "--untracked-files=no")),
    }


def reread(batch_id: str) -> int:
    """Apply the rules as they stand to every run a batch recorded, from its transcripts.

    For a rule that was decided before the batch and implemented wrongly: the
    runs it misjudged are rescored, and any that should not have been scored
    become runs the next resume tries again. What was recorded first is kept
    beside the new file.
    """
    batch = RUNS / batch_id
    meta = json.loads((batch / "batch.json").read_text(encoding="utf-8"))
    tasks = {task.id: task for task in read_tasks(TRIGGER / f"{meta['set']}.yaml")}
    outcomes_file = batch / "outcomes.jsonl"
    outcomes = read_outcomes(outcomes_file)
    first = batch / "outcomes.recorded.jsonl"
    if not first.is_file():
        shutil.copy2(outcomes_file, first)

    client = CLIENTS[recorded(meta, "client")]
    updated = []
    for old in outcomes:
        seen = Observation(prefix=PREFIXES[old.setup], server=SERVERS[old.setup], client=client)
        transcript = batch / "transcripts" / f"{old.task}.{old.run}.{old.attempt}.jsonl"
        for line in transcript.read_text(encoding="utf-8").splitlines():
            seen.read(line)
        new = outcome_of(
            tasks[old.task],
            old.run,
            old.attempt,
            old.setup,
            seen,
            stopped_at_call=old.stopped_at_call,
            clock=old.capped == "clock",
            seconds=old.seconds,
            rows=old.query_log_rows,
            stopped_at_edit=old.stopped_at_edit,
        )
        if verdict(new) != verdict(old):
            print(
                f"  {old.task} #{old.run}, attempt {old.attempt}: {verdict(old)} -> {verdict(new)}"
            )
        updated.append(new)

    outcomes_file.write_text(
        "".join(json.dumps(asdict(outcome)) + "\n" for outcome in updated), encoding="utf-8"
    )
    return 0


class NotPublishable(Exception):
    """Batches that cannot stand behind a published number together."""


def published(batch_ids: Sequence[str]) -> dict[str, Any]:
    """The results file for complete held-out batches run on one model and one version."""
    tasks = read_tasks(TRIGGER / "held_out.yaml")
    runs = []
    for batch_id in batch_ids:
        meta = json.loads((RUNS / batch_id / "batch.json").read_text(encoding="utf-8"))
        if meta["set"] != "held_out":
            raise NotPublishable(f"{batch_id} is a {meta['set']} batch; only held-out is published")
        if recorded(meta, "client") != CLAUDE_CODE.name:
            raise NotPublishable(
                f"{batch_id} ran {meta['client']}; {RESULTS.name} is Claude Code's"
            )
        if meta.get("stop_at_edit"):
            raise NotPublishable(
                f"{batch_id} stopped runs at their first edit, so it cannot say what they did after"
            )
        if not meta.get("model"):
            raise NotPublishable(
                f"{batch_id} ran on whatever model was the default, not a pinned one"
            )
        found = score(tasks, read_outcomes(RUNS / batch_id / "outcomes.jsonl"))
        expected = len(tasks) * meta["runs_per_task"]
        if found["runs_scored"] != expected:
            raise NotPublishable(f"{batch_id} scored {found['runs_scored']} of {expected} runs")
        if found["searches_that_failed"]:
            raise NotPublishable(
                f"{batch_id}: a search came back as an error in "
                f"{len(found['searches_that_failed'])} runs, so its instance could not answer"
            )
        if found["models"] != [meta["model"]] or found["versions"] != [meta["claude_code"]]:
            raise NotPublishable(
                f"{batch_id} pinned {meta['model']} on {meta['claude_code']}, and its sessions "
                f"reported {found['models']} on {found['versions']}"
            )
        runs.append({"setup": meta["setup"], "batch": {"id": batch_id, **meta}, **found})

    if len({run["batch"]["model"] for run in runs}) != 1:
        raise NotPublishable("the batches ran on different models")
    if len({run["batch"]["claude_code"] for run in runs}) != 1:
        raise NotPublishable("the batches ran on different versions of Claude Code")

    dates = [
        entry["started"][:10]
        for run in runs
        for entry in (run["batch"], *run["batch"].get("resumed", []))
    ]
    return {
        "question_set": "held_out",
        "measured_at": max(dates),
        "model": runs[0]["batch"]["model"],
        "claude_code": runs[0]["batch"]["claude_code"],
        "runs": runs,
    }


def write(batch_ids: Sequence[str]) -> int:
    try:
        payload = published(batch_ids)
    except NotPublishable as reason:
        print(f"not written: {reason}")
        return 2
    RESULTS.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {RESULTS.relative_to(REPO)} from {', '.join(batch_ids)}")
    return 0


def report(batch_id: str) -> int:
    batch = RUNS / batch_id
    meta = json.loads((batch / "batch.json").read_text(encoding="utf-8"))
    tasks = read_tasks(TRIGGER / f"{meta['set']}.yaml")
    found = score(tasks, read_outcomes(batch / "outcomes.jsonl"))
    client = CLIENTS[recorded(meta, "client")]
    print(f"batch {batch_id}: {meta['set']}, {client.label}, setup {meta['setup']}")
    print_score(found, client)
    return 0


def sampling(text: str) -> dict[str, float | int]:
    """`temperature=0.6,top_k=20` as the values Qwen Code sends with every request."""
    found: dict[str, float | int] = {}
    for pair in text.split(","):
        key, _, value = (part.strip() for part in pair.partition("="))
        if key not in SAMPLING:
            raise argparse.ArgumentTypeError(f"{key!r} is not one of {', '.join(SAMPLING)}")
        try:
            found[key] = SAMPLING[key](value)
        except ValueError:
            raise argparse.ArgumentTypeError(f"{key} takes a number, not {value!r}") from None
    return found


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--set", choices=SETS, default="tuning")
    parser.add_argument(
        "--client", choices=sorted(CLIENTS), default=CLAUDE_CODE.name, help="the AI assistant"
    )
    parser.add_argument(
        "--setup", choices=SETUPS, help="plugin, Claude Code's default, or the MCP server alone"
    )
    parser.add_argument("--runs", type=int, default=1, help="runs of each task")
    parser.add_argument("--model", help="the full model id; Claude Code's default when left out")
    parser.add_argument(
        "--base-url", help="Qwen Code: the OpenAI-compatible server, as the container reaches it"
    )
    parser.add_argument(
        "--sampling",
        type=sampling,
        help="Qwen Code: sampling sent with every request, as temperature=0.6,top_k=20",
    )
    parser.add_argument(
        "--context-window", type=int, help="Qwen Code: the context the server gives the model"
    )
    parser.add_argument(
        "--stop-at-edit",
        action="store_true",
        help="end a run at its first edit, when whether it searched before editing is known",
    )
    parser.add_argument("--tasks", help="only these task ids, separated by commas")
    parser.add_argument("--batch", help="a batch to resume, or the name for a new one")
    parser.add_argument(
        "--max-runs", type=int, default=20, help="refuse to plan more runs than this"
    )
    parser.add_argument(
        "--max-budget-usd", type=float, help="Claude Code's estimated cost cap per run"
    )
    parser.add_argument("--keep-instance", action="store_true", help="leave the instance running")
    parser.add_argument(
        "--reuse-images",
        action="store_true",
        help="start the instance from the images already built, if they hold this checkout",
    )
    parser.add_argument("--report", metavar="BATCH", help="score an existing batch and stop")
    parser.add_argument(
        "--reread", metavar="BATCH", help="apply the current rules to a batch's recorded runs"
    )
    parser.add_argument(
        "--write",
        metavar="BATCHES",
        help="write evals/results/trigger.json from held-out batches, separated by commas",
    )
    return parser.parse_args(argv)


def main() -> int:
    args = arguments()

    if args.report:
        return report(args.report)
    if args.reread:
        return reread(args.reread)
    if args.write:
        return write([batch.strip() for batch in args.write.split(",") if batch.strip()])
    return run_batch(args)


if __name__ == "__main__":
    sys.exit(main())
