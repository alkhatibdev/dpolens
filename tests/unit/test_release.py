"""The version a release is made from, which lives in six places.

A tag that does not match the repository, or two files that disagree, would
publish images that say one version and run another. The release workflow stops
on either before it builds anything.
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import release  # noqa: E402
from release import ReleaseError  # noqa: E402

CHANGELOG = """# Changelog

## 0.1.0

The first release.

- Search over GDPR and the UAE's law.

## 0.1.0-rc.1

A rehearsal.
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """The files that keep the version, copied, so a test can change them."""
    for place in release.PLACES:
        target = tmp_path / place.path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / place.path, target)
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    return tmp_path


def test_every_place_in_this_repository_names_the_same_version() -> None:
    assert release.current() == release.check(None)["version"]


def test_a_matching_tag_is_published() -> None:
    version = release.current()

    facts = release.check(f"v{version}")

    assert facts == {"version": version, "prerelease": "false", "publish": "true"}


def test_without_a_tag_nothing_is_published() -> None:
    assert release.check(None)["publish"] == "false"


def test_a_candidate_is_a_prerelease_in_both_spellings(repo: Path) -> None:
    release.bump("0.1.0-rc.1", repo)

    facts = release.check("v0.1.0-rc.1", repo)

    assert facts["prerelease"] == "true"
    pyproject = (repo / "packages/dpolens/pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "0.1.0rc1"' in pyproject
    assert "${DPOLENS_VERSION:-0.1.0-rc.1}" in (repo / "compose.yaml").read_text(encoding="utf-8")


def test_bump_writes_every_place_and_nothing_else(repo: Path) -> None:
    lock_before = (repo / "uv.lock").read_text(encoding="utf-8")

    release.bump("0.2.0", repo)

    assert release.current(repo) == "0.2.0"
    lock_after = (repo / "uv.lock").read_text(encoding="utf-8")
    changed = [
        (old, new)
        for old, new in zip(lock_before.splitlines(), lock_after.splitlines(), strict=True)
        if old != new
    ]
    assert changed == [('version = "0.0.0"', 'version = "0.2.0"')] * 2


def test_a_tag_for_another_version_is_refused(repo: Path) -> None:
    with pytest.raises(ReleaseError, match=re.escape("the tag says 9.9.9 and the repository says")):
        release.check("v9.9.9", repo)


@pytest.mark.parametrize("tag", ["0.1.0", "v0.1", "v0.1.0-preview", "pack/gdpr/2026.1"])
def test_a_tag_of_another_shape_is_refused(repo: Path, tag: str) -> None:
    with pytest.raises(ReleaseError, match="is not a release tag"):
        release.check(tag, repo)


def test_files_that_disagree_are_named(repo: Path) -> None:
    init = repo / "packages/dpolens-mcp/src/dpolens_mcp/__init__.py"
    init.write_text(
        init.read_text(encoding="utf-8").replace('"0.0.0"', '"0.0.1"'), encoding="utf-8"
    )

    with pytest.raises(ReleaseError, match=re.escape("dpolens_mcp/__init__.py has 0.0.1")):
        release.current(repo)


def test_the_notes_are_the_versions_own_section(repo: Path) -> None:
    assert (
        release.notes("0.1.0", repo)
        == "The first release.\n\n- Search over GDPR and the UAE's law.\n"
    )
    assert release.notes("0.1.0-rc.1", repo) == "A rehearsal.\n"


def test_a_version_without_notes_is_refused(repo: Path) -> None:
    with pytest.raises(ReleaseError, match=re.escape("no section for 0.3.0")):
        release.notes("0.3.0", repo)


@pytest.mark.parametrize(
    ("tag_spelling", "python_spelling"),
    [
        ("0.1.0", "0.1.0"),
        ("0.1.0-rc.1", "0.1.0rc1"),
        ("1.2.3-beta.4", "1.2.3b4"),
        ("2.0.0-alpha.1", "2.0.0a1"),
    ],
)
def test_the_two_spellings_are_one_version(tag_spelling: str, python_spelling: str) -> None:
    assert release.to_python(tag_spelling) == python_spelling
    assert release.to_semver(python_spelling) == tag_spelling
