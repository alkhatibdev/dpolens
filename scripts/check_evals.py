"""Run the held-out evals and fail if retrieval got worse.

The pack, the questions and the model are all fixed, so a drop in recall can
only come from a change to retrieval itself. That is what makes this gate worth
having: a regression has exactly one possible cause, and it is in the diff.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "packages" / "dpolens" / "src"))

from dpolens.engine.evals.gate import compare

REPO = Path(__file__).parents[1]
RESULTS = REPO / "evals" / "results"
PACKS = ("gdpr",)
SET = "held_out"


def published(pack: str) -> dict | None:
    path = RESULTS / f"{pack}.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    for run in payload.get("runs", []):
        if run.get("question_set") == SET:
            return run
    return None


def main() -> int:
    failures = []
    for pack in PACKS:
        baseline = published(pack)
        if baseline is None:
            # A missing baseline used to pass, which made this gate report
            # success on every change without measuring one of them.
            print(
                f"{pack}: no published {SET} score in {RESULTS / f'{pack}.json'}. "
                f"Produce one with: dpolens evals run --pack {pack} --set {SET} --write"
            )
            failures.append(pack)
            continue

        completed = subprocess.run(
            [
                "uv",
                "run",
                "dpolens",
                "evals",
                "run",
                "--pack",
                pack,
                "--set",
                SET,
                "--config",
                baseline["configuration"],
                "--model",
                baseline["model"],
                "--json",
            ],
            capture_output=True,
            text=True,
            cwd=REPO,
        )
        if completed.returncode != 0:
            print(f"{pack}: the eval run itself failed\n{completed.stderr.strip()}")
            failures.append(pack)
            continue

        measured = json.loads(completed.stdout)
        verdict = compare(pack, measured["recall_at_5"], baseline)
        print(verdict)
        if verdict.is_regression:
            failures.append(pack)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
