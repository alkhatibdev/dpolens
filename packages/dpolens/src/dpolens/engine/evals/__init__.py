"""Measuring whether retrieval finds the right clause."""

from dpolens.engine.evals.gate import Verdict, compare
from dpolens.engine.evals.run import (
    EvalSetError,
    Question,
    Run,
    check_configuration,
    read_questions,
    run_set,
)
from dpolens.engine.evals.score import (
    Interval,
    Outcome,
    Score,
    bootstrap_interval,
    grouped_interval,
    recall_at,
)

__all__ = [
    "EvalSetError",
    "Interval",
    "Outcome",
    "Question",
    "Run",
    "Score",
    "Verdict",
    "bootstrap_interval",
    "check_configuration",
    "compare",
    "grouped_interval",
    "read_questions",
    "recall_at",
    "run_set",
]
