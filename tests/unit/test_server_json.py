"""The MCP Registry's entry for DPOLens, which the registry checks only when it is published.

The registry refuses a name outside the domain its DNS record proves, a description over 100
characters, and a version it has seen before; a wrong URL would send people to nothing. These
are checked here so a mistake shows in the pull request that makes it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENTRY = json.loads((REPO / "server.json").read_text(encoding="utf-8"))


def test_the_entry_names_the_schema_and_the_domain_it_is_proven_by() -> None:
    assert ENTRY["$schema"].startswith("https://static.modelcontextprotocol.io/schemas/")
    assert re.fullmatch(r"com\.dpolens/[a-z0-9._-]+", ENTRY["name"])


def test_the_description_fits_the_registry() -> None:
    assert 0 < len(ENTRY["description"]) <= 100


def test_the_community_version_is_its_one_remote() -> None:
    assert ENTRY["remotes"] == [{"type": "streamable-http", "url": "https://mcp.dpolens.com/"}]
    assert "packages" not in ENTRY, "the MCP server's image does not run on its own"


def test_every_link_is_https() -> None:
    links = [ENTRY["websiteUrl"], ENTRY["repository"]["url"]]
    links += [icon["src"] for icon in ENTRY["icons"]]
    assert all(link.startswith("https://") for link in links)
