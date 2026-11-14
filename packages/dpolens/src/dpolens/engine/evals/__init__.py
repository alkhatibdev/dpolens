"""Measuring whether retrieval finds the right clause."""

from dpolens.engine.evals.gate import Verdict, compare
from dpolens.engine.evals.judge import (
    Judgement,
    Placed,
    SetChange,
    Unpaired,
    judge,
    placed_in,
    topic_of,
)
from dpolens.engine.evals.run import (
    EvalSetError,
    Question,
    Run,
    check_configuration,
    read_questions,
    run_set,
    run_together,
    sets_named,
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
    "Judgement",
    "Outcome",
    "Placed",
    "Question",
    "Run",
    "Score",
    "SetChange",
    "Unpaired",
    "Verdict",
    "bootstrap_interval",
    "check_configuration",
    "compare",
    "grouped_interval",
    "judge",
    "placed_in",
    "read_questions",
    "recall_at",
    "run_set",
    "run_together",
    "sets_named",
    "topic_of",
]
