"""Keep the published API contract honest.

`docs/openapi.json` is committed rather than only generated, so a change to the
contract is a diff a reviewer sees next to the code that caused it. This script
writes that file, checks it still matches the code, and in CI insists that a
changed contract carries a line in `docs/api-changelog.md`.

    uv run python scripts/api_contract.py            # check, which is what CI runs
    uv run python scripts/api_contract.py --write     # after changing a route
    uv run python scripts/api_contract.py --base origin/main

Breaking changes are a separate question, answered by oasdiff in CI, which can
tell a removed field from an added one and says so on the pull request.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from dpolens.api.app import create_app
from dpolens.settings import Settings

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "docs" / "openapi.json"
CHANGELOG = REPO / "docs" / "api-changelog.md"

# Generating the specification needs an application, and an application needs a
# database URL. Nothing connects: the schema comes from the routes.
UNUSED = "postgresql://unused:unused@localhost:5432/unused"


def generated() -> str:
    app = create_app(Settings.model_validate({"database_url": UNUSED}))
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"


def without_version(text: str) -> dict[str, Any]:
    """A specification without the release that serves it, which is not part of the contract."""
    loaded: dict[str, Any] = json.loads(text)
    loaded.get("info", {}).pop("version", None)
    return loaded


def contract_differs(before: str | None, after: str) -> bool:
    """Whether the contract changed, apart from the version a release writes into it.

    A release changes `info.version` and nothing else, and that alone is no news
    to the people building against the API.
    """
    return before is None or without_version(before) != without_version(after)


def merge_base_with(base: str) -> str:
    return subprocess.run(
        ["git", "merge-base", base, "HEAD"],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=True,
    ).stdout.strip()


def spec_at(commit: str) -> str | None:
    shown = subprocess.run(
        ["git", "show", f"{commit}:{SPEC.relative_to(REPO)}"],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    return shown.stdout if shown.returncode == 0 else None


def changed_files(base: str) -> list[str]:
    merge_base = merge_base_with(base)
    listed = subprocess.run(
        ["git", "diff", "--name-only", f"{merge_base}..HEAD"],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=True,
    ).stdout
    return [line.strip() for line in listed.splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Write the specification file")
    parser.add_argument("--base", help="Branch to compare against, for the changelog rule in CI")
    arguments = parser.parse_args()

    spec = generated()

    if arguments.write:
        SPEC.parent.mkdir(parents=True, exist_ok=True)
        SPEC.write_text(spec, encoding="utf-8")
        print(f"wrote {SPEC.relative_to(REPO)}")
        return 0

    if not SPEC.is_file():
        print(f"{SPEC.relative_to(REPO)} is missing. Run this with --write.", file=sys.stderr)
        return 1

    committed = SPEC.read_text(encoding="utf-8")
    if committed != spec:
        print(
            f"{SPEC.relative_to(REPO)} does not match the routes. The contract changed, so "
            "run `uv run python scripts/api_contract.py --write`, read the diff, and record "
            f"what changed in {CHANGELOG.relative_to(REPO)}.",
            file=sys.stderr,
        )
        return 1

    if arguments.base:
        changed = changed_files(arguments.base)
        spec_path = str(SPEC.relative_to(REPO))
        log_path = str(CHANGELOG.relative_to(REPO))
        if (
            spec_path in changed
            and log_path not in changed
            and contract_differs(spec_at(merge_base_with(arguments.base)), committed)
        ):
            print(
                f"{spec_path} changed and {log_path} did not. Every contract change gets a "
                "line, because the people building against this API have no other way to "
                "find out.",
                file=sys.stderr,
            )
            return 1

    print(f"{SPEC.relative_to(REPO)} matches the routes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
