"""One version across the repository, and the notes a release is published with.

    python scripts/release.py check [TAG]     every version against each other, and the tag
    python scripts/release.py notes VERSION   the changelog's section for a version
    python scripts/release.py bump VERSION    write a new version everywhere one is kept

The version is kept in the two packages, the lock file, `compose.yaml` and the
published API contract. It is spelled two ways. Tags, images and Compose use
semantic versioning (0.1.0-rc.1); the Python packages use the spelling Python
normalises it to (0.1.0rc1). They are the same version, and `check` compares
them as one.

The release workflow runs `check` with the tag it was started by. Outside GitHub
Actions it prints what it would have handed the workflow.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SEMVER = re.compile(r"(?P<core>\d+\.\d+\.\d+)(?:-(?P<stage>alpha|beta|rc)\.(?P<number>\d+))?")
PYTHON = re.compile(r"(?P<core>\d+\.\d+\.\d+)(?:(?P<stage>a|b|rc)(?P<number>\d+))?")
STAGES = {"alpha": "a", "beta": "b", "rc": "rc"}


class ReleaseError(Exception):
    """A version or a tag the release cannot go ahead with, said in a sentence."""


@dataclass(frozen=True)
class Place:
    """A file that keeps the version, and how to find it there."""

    path: str
    pattern: re.Pattern[str]
    python: bool

    def read(self, root: Path) -> list[str]:
        found = self.pattern.findall((root / self.path).read_text(encoding="utf-8"))
        if not found:
            raise ReleaseError(f"{self.path} names no version")
        return [to_semver(value) if self.python else value for value in found]

    def write(self, root: Path, version: str) -> None:
        file = root / self.path
        spelled = to_python(version) if self.python else version
        text = self.pattern.sub(
            lambda match: _replace(match, spelled), file.read_text(encoding="utf-8")
        )
        file.write_text(text, encoding="utf-8")


def _replace(match: re.Match[str], version: str) -> str:
    start, end = match.span(1)
    whole = match.group(0)
    offset = match.start(0)
    return whole[: start - offset] + version + whole[end - offset :]


PLACES = (
    Place(
        "packages/dpolens/pyproject.toml", re.compile(r'^version = "([^"]+)"$', re.M), python=True
    ),
    Place(
        "packages/dpolens-mcp/pyproject.toml",
        re.compile(r'^version = "([^"]+)"$', re.M),
        python=True,
    ),
    Place(
        "packages/dpolens/src/dpolens/__init__.py",
        re.compile(r'^__version__ = "([^"]+)"$', re.M),
        python=True,
    ),
    Place(
        "packages/dpolens-mcp/src/dpolens_mcp/__init__.py",
        re.compile(r'^__version__ = "([^"]+)"$', re.M),
        python=True,
    ),
    # The two workspace packages in the lock file, which records their versions too.
    Place(
        "uv.lock",
        re.compile(
            r'^name = "dpolens(?:-mcp)?"\nversion = "([^"]+)"\nsource = \{ editable = ', re.M
        ),
        python=True,
    ),
    # Every image Compose names, which is the version the checkout runs.
    Place("compose.yaml", re.compile(r"\$\{DPOLENS_VERSION:-([^}]+)\}"), python=False),
    # The published contract names the release that serves it, in its `info`.
    Place("docs/openapi.json", re.compile(r'^    "version": "([^"]+)"$', re.M), python=True),
)


def to_python(version: str) -> str:
    """0.1.0-rc.1 as Python spells it: 0.1.0rc1."""
    match = SEMVER.fullmatch(version)
    if not match:
        raise ReleaseError(
            f"{version!r} is not a version: write it as 0.1.0, or 0.1.0-rc.1 before a release"
        )
    if not match["stage"]:
        return match["core"]
    return f"{match['core']}{STAGES[match['stage']]}{match['number']}"


def to_semver(version: str) -> str:
    """0.1.0rc1 as a tag spells it: 0.1.0-rc.1."""
    match = PYTHON.fullmatch(version)
    if not match:
        raise ReleaseError(f"{version!r} is not a version this release process knows how to spell")
    if not match["stage"]:
        return match["core"]
    stage = {short: long for long, short in STAGES.items()}[match["stage"]]
    return f"{match['core']}-{stage}.{match['number']}"


def current(root: Path = REPO) -> str:
    """The one version every place agrees on, or the places that disagree."""
    found = {place.path: place.read(root) for place in PLACES}
    versions = {version for values in found.values() for version in values}
    if len(versions) != 1:
        listed = "; ".join(f"{path} has {', '.join(values)}" for path, values in found.items())
        raise ReleaseError(f"the versions disagree: {listed}")
    return versions.pop()


def check(tag: str | None, root: Path = REPO) -> dict[str, str]:
    """What the release workflow needs to know, after checking the tag against the versions.

    Without a tag, nothing is published: the workflow builds and pushes nothing.
    """
    version = current(root)
    if tag:
        if not tag.startswith("v") or not SEMVER.fullmatch(tag[1:]):
            raise ReleaseError(
                f"{tag!r} is not a release tag: a release is tagged v0.1.0, or v0.1.0-rc.1"
            )
        if tag[1:] != version:
            raise ReleaseError(f"the tag says {tag[1:]} and the repository says {version}")
    match = SEMVER.fullmatch(version)
    if not match:
        raise ReleaseError(f"{version!r} is not a version")
    return {
        "version": version,
        "prerelease": "true" if match["stage"] else "false",
        "publish": "true" if tag else "false",
    }


def notes(version: str, root: Path = REPO) -> str:
    """The changelog's section for a version, which becomes the release's notes."""
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    heading = re.search(rf"^## {re.escape(version)}\s*$", text, re.M)
    if not heading:
        raise ReleaseError(f"CHANGELOG.md has no section for {version}: write one before tagging")
    following = re.search(r"^## ", text[heading.end() :], re.M)
    body = text[heading.end() : heading.end() + following.start() if following else None].strip()
    if not body:
        raise ReleaseError(f"the section for {version} in CHANGELOG.md is empty")
    return body + "\n"


def bump(version: str, root: Path = REPO) -> None:
    """Write a version everywhere one is kept."""
    to_python(version)
    for place in PLACES:
        place.write(root, version)


def main(arguments: list[str]) -> int:
    command, *rest = arguments or ["help"]
    try:
        if command == "check" and len(rest) <= 1:
            facts = check(rest[0] if rest else None)
            output = os.environ.get("GITHUB_OUTPUT")
            lines = "".join(f"{key}={value}\n" for key, value in facts.items())
            if output:
                with open(output, "a", encoding="utf-8") as handle:
                    handle.write(lines)
            print(lines, end="")
        elif command == "notes" and len(rest) == 1:
            print(notes(rest[0]), end="")
        elif command == "bump" and len(rest) == 1:
            bump(rest[0])
            print(f"Every version now says {rest[0]}. Add its section to CHANGELOG.md.")
        else:
            print(__doc__)
            return 2
    except ReleaseError as error:
        print(f"release: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
