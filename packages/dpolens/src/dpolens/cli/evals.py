"""Running the eval sets and publishing what they say."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from dpolens.cli.ask import Asking
from dpolens.engine.embedding import DEFAULT_MODEL, Embedder, get_model
from dpolens.engine.evals import (
    Run,
    check_configuration,
    read_questions,
    run_set,
    run_together,
)
from dpolens.engine.session import session_scope
from dpolens.settings import load_settings

app = typer.Typer(
    name="evals", help="Measure whether search finds the right clause.", no_args_is_help=True
)

EVALS = Path("evals")
PUBLISHED_SET = "held_out"
"""The set whose numbers are written to the committed results file, in any language."""
BASELINES = ("keyword", "meaning")


def _commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout.strip()
    except subprocess.SubprocessError, OSError:
        return "unknown"


def _published(question_set: str) -> bool:
    """The held-out set, or the same set asked in another language, such as held_out.ar."""
    return question_set == PUBLISHED_SET or question_set.startswith(f"{PUBLISHED_SET}.")


@app.command(cls=Asking)
def run(
    pack: Annotated[str, typer.Option(help="Pack slug, for example gdpr")],
    question_sets: Annotated[
        list[str] | None,
        typer.Option(
            "--set",
            help=(
                "tuning, held_out, or either asked in another language, such as held_out.ar. "
                "Repeatable"
            ),
        ),
    ] = None,
    configuration: Annotated[
        str,
        typer.Option(
            "--config",
            help=(
                "rrf:10, convex:0.5, keyword or meaning, optionally with +normative, "
                "+light, +snowball or +folded-snowball"
            ),
        ),
    ] = "convex:0.5+normative",
    model: Annotated[str, typer.Option(help="Embedding model")] = DEFAULT_MODEL,
    baselines: Annotated[bool, typer.Option(help="Also score each retriever alone")] = False,
    together: Annotated[
        bool,
        typer.Option(help="Also score the sets as one, a topic asked in each counted once"),
    ] = False,
    write: Annotated[bool, typer.Option(help="Write evals/results/<pack>.json")] = False,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print one run as JSON: the sets together, or the first"),
    ] = False,
) -> None:
    """Score retrieval over one question set or several."""
    sets = question_sets or ["tuning"]
    configurations = [configuration, *BASELINES] if baselines else [configuration]
    for config in configurations:
        try:
            check_configuration(config)
        except ValueError as problem:
            raise typer.BadParameter(str(problem), param_hint="--config") from problem
    if together and len(sets) < 2:
        raise typer.BadParameter("name at least two sets to score together", param_hint="--set")
    refused = [name for name in sets if not _published(name)]
    if write and refused:
        raise typer.BadParameter(
            f"--write is for held-out sets, not {', '.join(map(repr, refused))}. "
            "evals/results is committed and is the baseline CI compares against, "
            "so a number measured on a set used for tuning does not belong in it.",
            param_hint="--set",
        )
    questions = {name: read_questions(EVALS / pack / f"{name}.yaml") for name in sets}

    with (
        Embedder(get_model(model)) as embedder,
        session_scope(load_settings()) as session,
    ):
        runs = [
            run_set(session, embedder, questions[name], config, pack=pack, question_set=name)
            for name in sets
            for config in configurations
        ]
    combined = (
        [
            run_together([result for result in runs if result.configuration == config])
            for config in configurations
        ]
        if together
        else []
    )
    runs += combined

    if as_json:
        headline = combined[0] if combined else runs[0]
        typer.echo(json.dumps({"pack": pack, **_as_record(headline)}))
        return

    for name in dict.fromkeys(result.question_set for result in runs):
        block = [result for result in runs if result.question_set == name]
        typer.echo(f"{pack} {name}: {block[0].score.questions} questions, model {model}\n")
        for result in block:
            typer.echo(
                f"  {result.configuration:12} recall@5 {result.score.recall_at_5:.2f} "
                f"({result.score.interval})   recall@10 {result.score.recall_at_10:.2f}   "
                f"MRR {result.score.mrr:.2f}"
            )
        if block[0].score.misses:
            typer.echo(f"\n  {block[0].configuration} missed: {', '.join(block[0].score.misses)}")
        typer.echo("")

    if write:
        _write(pack, runs)


def _as_record(result: Run) -> dict[str, Any]:
    return {
        "question_set": result.question_set,
        "configuration": result.configuration,
        "model": result.model,
        "context_recipe": result.recipe,
        "questions": result.score.questions,
        "recall_at_5": round(result.score.recall_at_5, 4),
        "recall_at_10": round(result.score.recall_at_10, 4),
        "mrr": round(result.score.mrr, 4),
        "interval": [
            round(result.score.interval.low, 4),
            round(result.score.interval.high, 4),
        ],
        "misses": list(result.score.misses),
    }


def _write(pack: str, runs: list[Run]) -> None:
    """The whole file, every set of the pack in it, since CI checks each one it finds."""
    path = EVALS / "results" / f"{pack}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pack": pack,
        "measured_at": datetime.now(UTC).date().isoformat(),
        "commit": _commit(),
        "runs": [_as_record(result) for result in runs],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    typer.echo(f"Wrote {path}")
