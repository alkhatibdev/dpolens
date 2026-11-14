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
    EvalSetError,
    Judgement,
    Placed,
    Run,
    Unpaired,
    check_configuration,
    judge,
    placed_in,
    queries_answered,
    read_questions,
    run_set,
    run_together,
    sets_named,
    topic_of,
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
    """The held-out set, in any language it is asked in, such as held_out.ar."""
    return question_set == PUBLISHED_SET or question_set.startswith(f"{PUBLISHED_SET}.")


@app.command(cls=Asking)
def run(
    pack: Annotated[str, typer.Option(help="Pack slug, for example gdpr")],
    question_sets: Annotated[
        list[str] | None,
        typer.Option(
            "--set",
            help=(
                "A set's name, such as tuning, held_out or assistant, for every language it "
                "is asked in, or one language of it, such as held_out.ar. Repeatable"
            ),
        ),
    ] = None,
    configuration: Annotated[
        str,
        typer.Option(
            "--config",
            help=(
                "rrf:10, convex:0.5, keyword or meaning, optionally with +normative, "
                "+questions, +light, +snowball or +folded-snowball"
            ),
        ),
    ] = "convex:0.5+normative+questions",
    model: Annotated[str, typer.Option(help="Embedding model")] = DEFAULT_MODEL,
    baselines: Annotated[bool, typer.Option(help="Also score each retriever alone")] = False,
    together: Annotated[
        bool,
        typer.Option(help="Also score the sets as one, a topic asked in each counted once"),
    ] = False,
    write: Annotated[bool, typer.Option(help="Write evals/results/<pack>.json")] = False,
    outcomes: Annotated[
        Path | None,
        typer.Option(
            help=(
                "Write where each question's right clause came to this file, for "
                "`dpolens evals compare`"
            )
        ),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print one run as JSON: the sets together, or the first"),
    ] = False,
) -> None:
    """Score retrieval over one question set or several."""
    try:
        named = [sets_named(EVALS / pack, name) for name in question_sets or ["tuning"]]
    except EvalSetError as problem:
        raise typer.BadParameter(str(problem), param_hint="--set") from problem
    sets = list(dict.fromkeys(found for each in named for found in each))
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
    if outcomes is not None:
        _keep(pack, [result for result in runs if result.configuration == configuration], outcomes)
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
        asked = questions.get(name, [])
        if len({question.question for question in asked}) < len(asked):
            at_five, queries = queries_answered(asked, block[0].outcomes, 5)
            at_ten, _ = queries_answered(asked, block[0].outcomes, 10)
            typer.echo(
                f"\n  {block[0].configuration} answered every part of {at_five} of {queries} "
                f"queries in the top five, and of {at_ten} in the top ten"
            )
        typer.echo("")

    if write:
        _write(pack, runs)


@app.command()
def compare(
    before: Annotated[
        Path,
        typer.Argument(help="An outcomes file from before a change, or a folder of them"),
    ],
    after: Annotated[Path, typer.Argument(help="The same, from after it")],
) -> None:
    """Judge a change to search from two runs over the same questions."""
    try:
        judgement = judge(_placed(before), _placed(after))
    except Unpaired as problem:
        raise typer.BadParameter(str(problem)) from problem

    for change in judgement.sets:
        typer.echo(
            f"{change.pack} {change.question_set}: {change.questions} questions   "
            f"hits at five {change.hits_before} to {change.hits_after}   "
            f"place score {change.score_before:.3f} to {change.score_after:.3f}"
        )
    typer.echo(
        f"\nAll: {judgement.questions} questions on {judgement.topics} topics   "
        f"hits at five {judgement.hits_before} to {judgement.hits_after}   "
        f"place score {judgement.score_before:.3f} to {judgement.score_after:.3f}"
    )
    typer.echo(f"By topic at five: {judgement.topics_found} found, {judgement.topics_lost} lost\n")
    typer.echo(_verdict(judgement))


def _verdict(judgement: Judgement) -> str:
    said = []
    if judgement.score_after <= judgement.score_before:
        said.append("No gain: the right clauses sit no higher than before.")
    else:
        said.append(
            f"Chance alone gives a gain this large {_share(judgement.chance)} of the time, "
            "and a change is kept under 5%."
        )
    for change in judgement.sets:
        if change.worse:
            said.append(
                f"{change.pack} {change.question_set} is worse: chance alone gives it a loss "
                f"this large {_share(change.chance_of_loss)} of the time."
            )
    said.append("Kept." if judgement.kept else "Not kept.")
    return "\n".join(said)


def _share(chance: float) -> str:
    return f"{100 * chance:.2f}%"


def _placed(path: Path) -> list[Placed]:
    """Every question in an outcomes file, or in each file of a folder."""
    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    if not files:
        raise typer.BadParameter(f"{path} holds no outcomes file")
    placed: list[Placed] = []
    for file in files:
        try:
            placed += placed_in(json.loads(file.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError, TypeError) as problem:
            raise typer.BadParameter(
                f"{file} is not an outcomes file, as `dpolens evals run --outcomes` writes one"
            ) from problem
    return placed


def _keep(pack: str, runs: list[Run], path: Path) -> None:
    """The configuration scored, with where each question's right clause came."""
    payload = {
        "pack": pack,
        "measured_at": datetime.now(UTC).date().isoformat(),
        "commit": _commit(),
        "configuration": runs[0].configuration,
        "model": runs[0].model,
        "context_recipe": runs[0].recipe,
        "sets": [
            {
                "question_set": result.question_set,
                "questions": [
                    {
                        "id": outcome.question_id,
                        "topic": topic_of(outcome.question_id, outcome.topic),
                        "expected": list(outcome.expected),
                        "returned": list(outcome.returned),
                        "place": outcome.first_hit,
                    }
                    for outcome in result.outcomes
                ],
            }
            for result in runs
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # Not to standard output, which `--json` keeps to the one record a script reads.
    typer.echo(f"Wrote {path}", err=True)


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
