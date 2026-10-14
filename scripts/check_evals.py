"""Run the held-out evals and fail if retrieval got worse.

The pack, the questions and the model are all fixed, so a drop in recall can
only come from a change to retrieval itself. That is what makes this gate worth
having: a regression has exactly one possible cause, and it is in the diff.

Every published set is checked against its own interval, the same set asked in
another language included, and sets published as one score are checked as one.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parents[1] / "packages" / "dpolens" / "src"))

from dpolens.engine.evals.gate import compare

REPO = Path(__file__).parents[1]
RESULTS = REPO / "evals" / "results"
PACKS = ("gdpr", "uae-pdpl")


def published(pack: str) -> list[dict[str, Any]] | None:
    """The pack's published runs in its published configuration, one for each set."""
    path = RESULTS / f"{pack}.json"
    if not path.is_file():
        return None
    runs: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8")).get("runs", [])
    if not runs:
        return None
    # The first run is the published configuration; the rest of its kind are its
    # other sets, and the baselines beside them are reported, not gated.
    configuration = runs[0]["configuration"]
    return [run for run in runs if run["configuration"] == configuration]


def measure(pack: str, baseline: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    sets = baseline["question_set"].split("+")
    return subprocess.run(
        [
            "uv",
            "run",
            "dpolens",
            "evals",
            "run",
            "--pack",
            pack,
            *[part for name in sets for part in ("--set", name)],
            *(["--together"] if len(sets) > 1 else []),
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


def main() -> int:
    failures = []
    for pack in PACKS:
        baselines = published(pack)
        if baselines is None:
            # A missing baseline used to pass, which made this gate report
            # success on every change without measuring one of them.
            print(
                f"{pack}: no published held-out score in {RESULTS / f'{pack}.json'}. "
                f"Produce one with: dpolens evals run --pack {pack} --set held_out --write"
            )
            failures.append(pack)
            continue

        for baseline in baselines:
            label = f"{pack} {baseline['question_set']}"
            completed = measure(pack, baseline)
            if completed.returncode != 0:
                print(f"{label}: the eval run itself failed\n{completed.stderr.strip()}")
                failures.append(label)
                continue

            measured = json.loads(completed.stdout)
            verdict = compare(label, measured["recall_at_5"], baseline)
            print(verdict)
            if verdict.is_regression:
                failures.append(label)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
