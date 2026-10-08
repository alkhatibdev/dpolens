"""Measure how often Claude Code calls DPOLens without being told to.

Each task in evals/trigger is something a developer might ask for in the Larder
app. Every run is a new container holding Claude Code, the app, and DPOLens
installed the way the README installs it, talking to a throwaway instance of
DPOLens built from this checkout. What is measured is whether the assistant
calls search_policies or get_clause, and whether it does so before it edits a
file.

    uv run python scripts/run_trigger_test.py --set tuning                # the pilot
    uv run python scripts/run_trigger_test.py --set held_out --runs 3 --model <id>
    uv run python scripts/run_trigger_test.py --report <batch>            # score again

Runs are billed to a Claude subscription through a token from
`claude setup-token`, read from evals/trigger/.oauth-token, which git ignores,
or to an API account when that file is absent and ANTHROPIC_API_KEY is set.
Everything a batch produces stays in evals/trigger/runs/<batch>/, also ignored,
so a batch stopped by a usage limit resumes where it stopped.
"""

from __future__ import annotations

import argparse
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
from collections.abc import Iterable, Sequence
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

CLAUDE_CODE = "2.1.288"
"""The Claude Code version every run uses, so a batch measures one thing."""

IMAGE = f"dpolens-trigger-run:{CLAUDE_CODE}"
PROJECT = "dpolens-trigger"
NETWORK = f"{PROJECT}_default"
MCP_URL = "http://mcp:8765/mcp"
DEVELOPER = "developer@larder.shop"

SETS = ("tuning", "held_out")
SETUPS = ("plugin", "mcp-only")
PREFIXES = {"plugin": "mcp__plugin_dpolens_dpolens__", "mcp-only": "mcp__dpolens__"}
SERVERS = {"plugin": "plugin:dpolens:dpolens", "mcp-only": "dpolens"}

COUNTED = ("search_policies", "get_clause")
"""The tools that return clause text. Listing documents is not consulting them."""

EDITS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
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
    model: str | None = None
    version: str | None = None
    server_status: str | None = None
    plugins: tuple[str, ...] = ()
    plugin_errors: tuple[str, ...] = ()
    tools: list[str] = field(default_factory=list)
    first_call: int | None = None
    """Where in `tools` the first counted call is."""
    first_edit: int | None = None
    call_answered: bool = False
    dpolens_answered: int = 0
    """DPOLens calls that came back, each of which wrote one row to the query log."""
    retries: list[str] = field(default_factory=list)
    result: dict[str, Any] | None = None
    started: bool = False
    _names: dict[str, str] = field(default_factory=dict)
    _call_id: str | None = None

    def see(self, event: dict[str, Any]) -> None:
        kind, subtype = event.get("type"), event.get("subtype")
        if kind == "system" and subtype == "init":
            self._init(event)
        elif kind == "system" and subtype == "api_retry":
            self.retries.append(str(event.get("error")))
        elif kind == "assistant":
            self._assistant(event)
        elif kind == "user":
            self._user(event)
        elif kind == "result":
            self.result = event

    def _init(self, event: dict[str, Any]) -> None:
        self.started = True
        self.model = event.get("model")
        self.version = event.get("claude_code_version")
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
            name = str(block.get("name", ""))
            self._names[str(block.get("id"))] = name
            self.tools.append(name)
            if self.first_call is None and self.counts(name):
                self.first_call = len(self.tools) - 1
                self._call_id = str(block.get("id"))
            if self.first_edit is None and name in EDITS:
                self.first_edit = len(self.tools) - 1

    def _user(self, event: dict[str, Any]) -> None:
        for block in blocks(event):
            if block.get("type") != "tool_result":
                continue
            use = str(block.get("tool_use_id"))
            if use == self._call_id:
                self.call_answered = True
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
            return "Claude Code never started a session"
        if setup == "plugin" and ("dpolens" not in self.plugins or self.plugin_errors):
            return f"the plugin did not load: {'; '.join(self.plugin_errors) or 'not listed'}"
        if self.server_status not in ("connected", "pending"):
            return f"the MCP server was {self.server_status or 'missing'} at the start"
        if self.called:
            return None
        if self.result and self.result.get("is_error") and capped_by(self.result) is None:
            return f"the run failed: {self.result.get('result') or self.result.get('subtype')}"
        return None


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
) -> Outcome:
    unusable = seen.unusable(setup)
    result = seen.result or {}
    capped = "clock" if clock else capped_by(result) if not seen.called else None
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


def print_score(found: dict[str, Any]) -> None:
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
    print(
        f"  estimated cost {found['estimated_cost_usd']} USD, "
        f"model {', '.join(found['models'])}, Claude Code {', '.join(found['versions'])}"
    )
    for key, label in (
        ("never_searched", "never searched"),
        ("searched_without_need", "searched without needing to"),
        ("query_log_mismatches", "query log disagrees with the stream for"),
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

    def start(self) -> None:
        print("starting a throwaway DPOLens instance", flush=True)
        try:
            self.compose("up", "-d", "--build", "--quiet-pull", capture_output=True)
        except subprocess.CalledProcessError as error:
            print(error.stdout, error.stderr, sep="\n")
            raise
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


def build_image() -> None:
    print(f"building the run container with Claude Code {CLAUDE_CODE}", flush=True)
    docker(
        "build",
        "--quiet",
        "-t",
        IMAGE,
        "--build-arg",
        f"CLAUDE_CODE_VERSION={CLAUDE_CODE}",
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


def prepare_profile(setup: str, token: str, volume: str, plugin_source: Path) -> None:
    """Install DPOLens into an empty profile once, for every run of the batch to copy."""
    values: dict[str, Any]
    if setup == "plugin":
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
        IMAGE,
        "prepare-profile.sh",
        setup,
        input=json.dumps(values),
        capture_output=True,
    )


def read_lines(stream: Any, lines: queue.Queue[str | None]) -> None:
    for line in stream:
        lines.put(line)
    lines.put(None)


def run_once(
    task: Task,
    setup: str,
    model: str | None,
    budget: float | None,
    volume: str,
    plugin_source: Path,
    credential: tuple[str, str],
    transcript: Path,
) -> tuple[Observation, bool, bool, float]:
    """One container, one prompt. Returns what was seen, and why it ended."""
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
        IMAGE,
        "run-task.sh",
    ]
    seen = Observation(prefix=PREFIXES[setup], server=SERVERS[setup])
    started = time.monotonic()
    stopped_at_call = clock = False

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
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                seen.see(event)
            if seen.call_answered:
                stopped_at_call = True
                break

    if stopped_at_call or clock:
        subprocess.run(["docker", "kill", name], capture_output=True, check=False)
    process.wait(timeout=60)
    return seen, stopped_at_call, clock, time.monotonic() - started


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
    seen, at_call, clock, seconds = run_once(
        task,
        args.setup,
        args.model,
        args.max_budget_usd,
        volume,
        plugin_source,
        credential,
        batch / "transcripts" / f"{task.id}.{run}.{attempt}.jsonl",
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
    )


def verdict(outcome: Outcome) -> str:
    if not outcome.scored:
        return f"not scored, {outcome.unusable}"
    if outcome.called:
        return "searched" + ("" if outcome.before_edit else " after editing")
    return f"did not search ({outcome.capped or 'finished'}), {outcome.seconds:.0f}s"


def read_outcomes(path: Path) -> list[Outcome]:
    if not path.is_file():
        return []
    return [
        Outcome(**json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def credential_for_runs() -> tuple[str, str] | None:
    """The variable Claude Code authenticates with, and its value."""
    if TOKEN_FILE.is_file():
        return "CLAUDE_CODE_OAUTH_TOKEN", TOKEN_FILE.read_text(encoding="utf-8").strip()
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "ANTHROPIC_API_KEY", os.environ["ANTHROPIC_API_KEY"]
    return None


def run_batch(args: argparse.Namespace) -> int:
    tasks = read_tasks(TRIGGER / f"{args.set}.yaml")
    if args.tasks:
        wanted = set(args.tasks.split(","))
        tasks = [task for task in tasks if task.id in wanted]

    if args.set == "held_out" and not args.model:
        print("a held-out batch is published, so its model is pinned: pass --model")
        return 2
    planned = len(tasks) * args.runs
    if planned > args.max_runs:
        print(f"{planned} runs planned, more than --max-runs {args.max_runs}; nothing started")
        return 2
    credential = credential_for_runs()
    if credential is None:
        print(
            f"no subscription token at {TOKEN_FILE}: run `claude setup-token` and save it "
            "there, or set ANTHROPIC_API_KEY to bill an API account instead"
        )
        return 2

    batch_id = args.batch or f"{args.set}-{args.setup}-{datetime.now(UTC):%Y%m%d-%H%M}"
    batch = RUNS / batch_id
    (batch / "transcripts").mkdir(parents=True, exist_ok=True)
    outcomes_file = batch / "outcomes.jsonl"
    outcomes = read_outcomes(outcomes_file)
    meta = {
        "set": args.set,
        "setup": args.setup,
        "model": args.model,
        "claude_code": CLAUDE_CODE,
        "runs_per_task": args.runs,
        "max_turns": MAX_TURNS,
        "max_budget_usd": args.max_budget_usd,
        "commit": subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True
        ).stdout.strip(),
        "started": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    (batch / "batch.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"batch {batch_id}: {len(tasks)} tasks, {args.runs} runs each, setup {args.setup}")

    build_image()
    instance = Instance()
    volume = f"{PROJECT}-profile-{args.setup}"
    failures = 0
    try:
        instance.start()
        plugin_source = marketplace(batch)
        prepare_profile(args.setup, instance.token, volume, plugin_source)

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
    print_score(found)
    return 0


def report(batch_id: str) -> int:
    batch = RUNS / batch_id
    meta = json.loads((batch / "batch.json").read_text(encoding="utf-8"))
    tasks = read_tasks(TRIGGER / f"{meta['set']}.yaml")
    found = score(tasks, read_outcomes(batch / "outcomes.jsonl"))
    print(f"batch {batch_id}: {meta['set']}, setup {meta['setup']}")
    print_score(found)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--set", choices=SETS, default="tuning")
    parser.add_argument("--setup", choices=SETUPS, default="plugin")
    parser.add_argument("--runs", type=int, default=1, help="runs of each task")
    parser.add_argument("--model", help="the full model id; Claude Code's default when left out")
    parser.add_argument("--tasks", help="only these task ids, separated by commas")
    parser.add_argument("--batch", help="a batch to resume, or the name for a new one")
    parser.add_argument(
        "--max-runs", type=int, default=20, help="refuse to plan more runs than this"
    )
    parser.add_argument(
        "--max-budget-usd", type=float, help="Claude Code's estimated cost cap per run"
    )
    parser.add_argument("--keep-instance", action="store_true", help="leave the instance running")
    parser.add_argument("--report", metavar="BATCH", help="score an existing batch and stop")
    args = parser.parse_args()

    if args.report:
        return report(args.report)
    return run_batch(args)


if __name__ == "__main__":
    sys.exit(main())
