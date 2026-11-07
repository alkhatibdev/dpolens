"""Score every embedding model against every retrieval configuration.

This is how the default model and the fusion rule get chosen: by measurement,
published as a table, rather than by argument. It indexes the corpus once per
model, which is the slow part, then scores each configuration over the same
questions.

    uv run python scripts/run_matrix.py --set tuning > matrix.txt
    uv run python scripts/run_matrix.py --set held_out --models e5-small,e5-base

A set named without its language, such as tuning, is scored in every language it is
asked in, each on its own row.

The table goes to stdout, so redirect it where you want it. matrix*.txt is
ignored, and the conclusions belong in evals/retrieval.md rather than in a file.

The first run of a model downloads it. Everything after that is offline.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO = Path(__file__).parents[1]
sys.path.insert(0, str(REPO / "packages" / "dpolens" / "src"))

from dpolens.engine.embedding import MODELS, Embedder, get_model  # noqa: E402
from dpolens.engine.embedding.index import build_index  # noqa: E402
from dpolens.engine.evals import read_questions, run_set, sets_named  # noqa: E402
from dpolens.engine.session import session_scope  # noqa: E402
from dpolens.settings import load_settings  # noqa: E402

CONFIGS = (
    "keyword",
    "meaning",
    "meaning+normative",
    "rrf:10",
    "rrf:10+normative",
    "rrf:60+normative",
    "convex:0.5+normative",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", default="gdpr")
    parser.add_argument("--set", dest="question_set", default="tuning")
    parser.add_argument("--models", default=",".join(MODELS))
    parser.add_argument("--configs", default=",".join(CONFIGS))
    args = parser.parse_args()

    directory = REPO / "evals" / args.pack
    questions = {
        set_name: read_questions(directory / f"{set_name}.yaml")
        for set_name in sets_named(directory, args.question_set)
    }
    models = [name.strip() for name in args.models.split(",") if name.strip()]
    configs = [name.strip() for name in args.configs.split(",") if name.strip()]

    for set_name, asked in questions.items():
        print(f"{args.pack} {set_name}: {len(asked)} questions", flush=True)
    print(
        f"\n| {'model':18} | {'set':12} | {'configuration':22} "
        "| recall@5 | interval     | recall@10 | MRR  |",
        flush=True,
    )
    print(
        f"| {'-' * 18} | {'-' * 12} | {'-' * 22} | -------- | ------------ | --------- | ---- |",
        flush=True,
    )

    for name in models:
        try:
            started = time.time()
            with (
                Embedder(get_model(name)) as embedder,
                session_scope(load_settings()) as session,
            ):
                build_index(session, embedder)
                session.commit()
                indexed = time.time() - started

                for configuration in configs:
                    for set_name, asked in questions.items():
                        found = run_set(
                            session,
                            embedder,
                            asked,
                            configuration,
                            pack=args.pack,
                            question_set=set_name,
                        ).score
                        print(
                            f"| {name:18} | {set_name:12} | {configuration:22} "
                            f"| {found.recall_at_5:8.2f} | {found.interval!s:12} "
                            f"| {found.recall_at_10:9.2f} | {found.mrr:4.2f} |",
                            flush=True,
                        )
            print(
                f"| {name:18} | {'':12} | {'(index built)':22} | {indexed:7.0f}s | | | |",
                flush=True,
            )
        except Exception as problem:
            print(f"| {name:18} | FAILED: {type(problem).__name__}: {problem}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
