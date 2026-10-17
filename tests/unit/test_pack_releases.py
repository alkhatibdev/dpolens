"""Newer versions of a law pack, read from the repository's releases.

Nothing here touches the network: the releases come from canned pages, as GitHub
would send them.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from dpolens.engine.packs.releases import (
    API,
    PAGE_SIZE,
    PackRelease,
    ReleaseError,
    newest,
    pack_releases,
)

FILES = "https://github.com/alkhatibdev/dpolens/releases/download"


def release(
    tag: str, *, prerelease: bool = False, draft: bool = False, files: bool = True
) -> dict[str, Any]:
    name = ""
    if tag.startswith("pack/"):
        _, slug, version = tag.split("/")
        name = f"dpolens-pack-{slug}-{version}.tar.gz"
    assets = [
        {"name": name, "browser_download_url": f"{FILES}/{tag}/{name}"},
        {"name": f"{name}.sha256", "browser_download_url": f"{FILES}/{tag}/{name}.sha256"},
    ]
    return {
        "tag_name": tag,
        "draft": draft,
        "prerelease": prerelease,
        "html_url": f"https://github.com/alkhatibdev/dpolens/releases/tag/{tag}",
        "assets": assets if files and name else [],
    }


def pages(*listed: list[dict[str, Any]]) -> dict[str, bytes]:
    return {
        f"{API}/repos/alkhatibdev/dpolens/releases?per_page={PAGE_SIZE}&page={number}": json.dumps(
            items
        ).encode()
        for number, items in enumerate(listed, start=1)
    }


def read(served: dict[str, bytes]) -> list[PackRelease]:
    return pack_releases("alkhatibdev/dpolens", get=served.__getitem__)


def test_a_pack_release_is_found_with_its_file_and_checksum() -> None:
    (found,) = read(pages([release("pack/gdpr/2026.2")]))

    assert (found.slug, found.version) == ("gdpr", "2026.2")
    assert found.archive_url.endswith("/pack/gdpr/2026.2/dpolens-pack-gdpr-2026.2.tar.gz")
    assert found.checksum_url.endswith("dpolens-pack-gdpr-2026.2.tar.gz.sha256")


def test_app_releases_drafts_and_pre_releases_are_not_offered() -> None:
    found = read(
        pages(
            [
                release("v0.1.0"),
                release("pack/gdpr/2026.3", prerelease=True),
                release("pack/gdpr/2026.4", draft=True),
                release("pack/gdpr/2026.2"),
            ]
        )
    )

    assert [(item.slug, item.version) for item in found] == [("gdpr", "2026.2")]


def test_every_page_is_read_until_a_short_one() -> None:
    first = [release(f"v0.{number}.0") for number in range(PAGE_SIZE)]

    found = read(pages(first, [release("pack/uae-pdpl/2026.2")]))

    assert [item.slug for item in found] == ["uae-pdpl"]


def test_a_pack_release_without_its_files_is_reported() -> None:
    with pytest.raises(
        ReleaseError, match=re.escape("does not carry dpolens-pack-gdpr-2026.2.tar.gz")
    ):
        read(pages([release("pack/gdpr/2026.2", files=False)]))


def test_the_newest_is_offered_only_when_it_is_newer_than_the_loaded_one() -> None:
    found = read(
        pages([release("pack/gdpr/2026.9"), release("pack/gdpr/2026.10"), release("pack/x/1.0")])
    )

    best = newest(found, "gdpr", after="2026.2")
    assert best is not None
    assert best.version == "2026.10"
    assert newest(found, "gdpr", after="2026.10") is None
    assert newest(found, "uae-pdpl", after="2026.1") is None
