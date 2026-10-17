"""Newer versions of a law pack, from the releases of the repository that publishes them.

A pack is released under a tag of its own, `pack/<slug>/<version>`, with two files:
its archive and the archive's checksum (see `archive`). They are read only when
somebody asks for an update: nothing about the instance is sent, and an HTTPS
proxy set in the environment is used.
"""

from __future__ import annotations

import json
import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from dpolens import __version__
from dpolens.engine.packs.archive import CHECKSUM_SUFFIX, archive_name
from dpolens.engine.packs.load import version_key

API = "https://api.github.com"
PAGE_SIZE = 100
MOST_PAGES = 10
TAG = re.compile(r"pack/(?P<slug>[a-z0-9-]+)/(?P<version>\d+(?:\.\d+)*)")

Fetch = Callable[[str], bytes]


class ReleaseError(Exception):
    """Releases that cannot be read, or a release without its files, said in a sentence."""


@dataclass(frozen=True)
class PackRelease:
    slug: str
    version: str
    page: str
    archive_url: str
    checksum_url: str


def fetch(url: str) -> bytes:
    """GET a URL the way GitHub asks API clients to, following its redirects to the files."""
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"dpolens/{__version__}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body: bytes = response.read()
            return body
    except OSError as error:
        raise ReleaseError(f"could not read {url}: {error}") from error


def pack_releases(repository: str, get: Fetch = fetch) -> list[PackRelease]:
    """Every published pack release in a repository, newest first per pack.

    Drafts are not published, and a pre-release is not offered as an update.
    """
    found: list[PackRelease] = []
    for page in range(1, MOST_PAGES + 1):
        url = f"{API}/repos/{repository}/releases?per_page={PAGE_SIZE}&page={page}"
        try:
            listed: Any = json.loads(get(url))
        except ValueError as error:
            raise ReleaseError(f"{url} did not answer with a list of releases") from error
        if not isinstance(listed, list):
            raise ReleaseError(f"{url} did not answer with a list of releases")
        found.extend(release for item in listed if (release := _pack_release(item)) is not None)
        if len(listed) < PAGE_SIZE:
            break
    return sorted(
        found, key=lambda release: (release.slug, version_key(release.version)), reverse=True
    )


def _pack_release(item: dict[str, Any]) -> PackRelease | None:
    tag = TAG.fullmatch(str(item.get("tag_name", "")))
    if tag is None or item.get("draft") or item.get("prerelease"):
        return None
    slug, version = tag["slug"], tag["version"]
    assets = {
        asset.get("name"): asset.get("browser_download_url") for asset in item.get("assets", [])
    }
    name = archive_name(slug, version)
    if not assets.get(name) or not assets.get(f"{name}{CHECKSUM_SUFFIX}"):
        raise ReleaseError(f"the release {tag.string} does not carry {name} and its checksum")
    return PackRelease(
        slug=slug,
        version=version,
        page=str(item.get("html_url", "")),
        archive_url=str(assets[name]),
        checksum_url=str(assets[f"{name}{CHECKSUM_SUFFIX}"]),
    )


def newest(releases: list[PackRelease], slug: str, after: str | None) -> PackRelease | None:
    """The newest release of a pack, if it is newer than the version loaded."""
    candidates = [release for release in releases if release.slug == slug]
    if not candidates:
        return None
    best = max(candidates, key=lambda release: version_key(release.version))
    if after is not None and version_key(best.version) <= version_key(after):
        return None
    return best
