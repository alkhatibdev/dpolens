"""Running the eval sets and publishing what they say."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from dpolens.engine.embedding import DEFAULT_MODEL, Embedder, get_model
from dpolens.engine.evals import Run, read_questions, run_set
from dpolens.engine.session import session_scope
from dpolens.settings import load_settings

app = typer.Typer(
    name="evals", help="Measure whether search finds the right clause.", no_args_is_help=True
)

EVALS = Path("evals")
PUBLISHED_SET = "held_out"
"""The only set whose numbers are written to the committed results file."""
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


@app.command()
def run(
    pack: Annotated[str, typer.Option(help="Pack slug, for example gdpr")],
    question_set: Annotated[str, typer.Option("--set", help="tuning or held_out")] = "tuning",
    configuration: Annotated[
        str, typer.Option("--config", help="rrf:10, convex:0.5, keyword or meaning")
    ] = "rrf:10",
    model: Annotated[str, typer.Option(help="Embedding model")] = DEFAULT_MODEL,
    baselines: Annotated[bool, typer.Option(help="Also score each retriever alone")] = False,
    write: Annotated[bool, typer.Option(help="Write evals/results/<pack>.json")] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Print one run as JSON")] = False,
) -> None:
    """Score retrieval over a question set."""
    questions = read_questions(EVALS / pack / f"{question_set}.yaml")
    configurations = [configuration, *BASELINES] if baselines else [configuration]

    with (
        Embedder(get_model(model)) as embedder,
        session_scope(load_settings()) as session,
    ):
        runs = [
            run_set(session, embedder, questions, config, pack=pack, question_set=question_set)
            for config in configurations
        ]

    if as_json:
        first = runs[0]
        typer.echo(
            json.dumps(
                {
                    "pack": pack,
                    "question_set": question_set,
                    "configuration": first.configuration,
                    "model": first.model,
                    "questions": first.score.questions,
                    "recall_at_5": round(first.score.recall_at_5, 4),
                    "recall_at_10": round(first.score.recall_at_10, 4),
                    "mrr": round(first.score.mrr, 4),
                    "interval": [
                        round(first.score.interval.low, 4),
                        round(first.score.interval.high, 4),
                    ],
                    "misses": list(first.score.misses),
                }
            )
        )
        return

    typer.echo(f"{pack} {question_set}: {len(questions)} questions, model {model}\n")
    for result in runs:
        typer.echo(
            f"  {result.configuration:12} recall@5 {result.score.recall_at_5:.2f} "
            f"({result.score.interval})   recall@10 {result.score.recall_at_10:.2f}   "
            f"MRR {result.score.mrr:.2f}"
        )
    if runs[0].score.misses:
        typer.echo(f"\n  {runs[0].configuration} missed: {', '.join(runs[0].score.misses)}")

    if write:
        if question_set != "held_out":
            raise typer.BadParameter(
                f"--write is for the held-out set, not {question_set!r}. "
                "evals/results is committed and is the baseline CI compares against, "
                "so a number measured on the set used for tuning does not belong in it."
            )
        _write(pack, runs)


def _write(pack: str, runs: list[Run]) -> None:
    path = EVALS / "results" / f"{pack}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pack": pack,
        "measured_at": datetime.now(UTC).date().isoformat(),
        "commit": _commit(),
        "runs": [
            {
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
            for result in runs
        ],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    typer.echo(f"\nWrote {path}")
