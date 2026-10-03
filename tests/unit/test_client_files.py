"""The files a developer copies into their editor, and the Compose file.

None of this is code that runs in a test, which is exactly why it needs one: a
port renamed in the Compose file and left alone in a client configuration is a
quickstart that does not work, and nothing else would notice.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from dpolens_mcp.instructions import SENTENCES
from dpolens_mcp.settings import Settings

REPO = Path(__file__).resolve().parents[2]
CLIENTS = REPO / "clients"
COMPOSE = REPO / "compose.yaml"
MARKETPLACE = REPO / ".claude-plugin" / "marketplace.json"
PLUGIN = CLIENTS / "claude-code" / ".claude-plugin" / "plugin.json"

GUIDANCE = (
    CLIENTS / "claude-code" / "skills" / "dpolens" / "SKILL.md",
    CLIENTS / "cursor" / "dpolens.mdc",
)

CONFIGURATIONS = (
    CLIENTS / "cursor" / "mcp.json",
    CLIENTS / "vscode" / "mcp.json",
)

sys.path.insert(0, str(REPO / "scripts"))


def compose() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    return loaded


def ports(service: str) -> tuple[int, int]:
    """The port a service is published on and the port it listens on.

    The published one is written as `${NAME:-8765}`, so the default inside the
    variable is the one a quickstart actually uses.
    """
    mapping = str(compose()["services"][service]["ports"][0])
    outside, _, inside = mapping.rpartition(":")
    named = re.fullmatch(r"\$\{[A-Z_]+:-(\d+)\}", outside) or re.fullmatch(r"(\d+)", outside)
    assert named, f"cannot read the published port from {mapping!r}"
    return int(named.group(1)), int(inside)


class TestTheGuidanceIsTheSameEverywhere:
    def test_no_file_has_fallen_behind_the_instructions(self) -> None:
        """One source for the words, and a command that writes the rest."""
        from client_text import stale

        behind = [path.relative_to(REPO) for path in stale()]
        assert behind == [], (
            "run `uv run python scripts/client_text.py --write` after changing the words"
        )

    @pytest.mark.parametrize("path", GUIDANCE, ids=lambda path: path.parent.name)
    @pytest.mark.parametrize("sentence", SENTENCES, ids=range(len(SENTENCES)))
    def test_every_surface_carries_every_sentence(self, path: Path, sentence: str) -> None:
        """Where the lines break is the file's business, so this ignores it."""
        written = " ".join(path.read_text(encoding="utf-8").split())

        assert " ".join(sentence.split()) in written

    def test_the_cursor_rule_is_always_applied(self) -> None:
        """A rule the agent has to ask for is a rule that does not fire in time."""
        rule = (CLIENTS / "cursor" / "dpolens.mdc").read_text(encoding="utf-8")

        assert rule.startswith("---")
        assert "alwaysApply: true" in rule

    def test_the_skill_says_when_to_use_it(self) -> None:
        """The description is what an assistant reads before deciding to look."""
        skill = (CLIENTS / "claude-code" / "skills" / "dpolens" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        front = skill.split("---")[1]

        assert "name: dpolens" in front
        assert "personal data" in front
        assert "retention" in front


class TestNothingCarriesACredential:
    @pytest.mark.parametrize(
        "path",
        [*CONFIGURATIONS, PLUGIN, MARKETPLACE, COMPOSE],
        ids=lambda path: str(path.name),
    )
    def test_no_file_holds_a_token(self, path: Path) -> None:
        """Every one of these is committed, and a token in a committed file is spent."""
        assert "dpol_" not in path.read_text(encoding="utf-8")

    def test_each_client_takes_the_token_from_somewhere_safe(self) -> None:
        cursor = json.loads((CLIENTS / "cursor" / "mcp.json").read_text(encoding="utf-8"))
        vscode = json.loads((CLIENTS / "vscode" / "mcp.json").read_text(encoding="utf-8"))
        plugin = json.loads(PLUGIN.read_text(encoding="utf-8"))

        assert "${env:DPOLENS_TOKEN}" in cursor["mcpServers"]["dpolens"]["headers"]["Authorization"]
        assert "${input:dpolens-token}" in vscode["servers"]["dpolens"]["headers"]["Authorization"]
        assert plugin["userConfig"]["token"]["sensitive"] is True


class TestEveryClientPointsAtTheSameServer:
    def test_the_url_is_the_one_compose_publishes(self) -> None:
        port, _ = ports("mcp")
        expected = f"http://localhost:{port}/mcp"

        cursor = json.loads((CLIENTS / "cursor" / "mcp.json").read_text(encoding="utf-8"))
        vscode = json.loads((CLIENTS / "vscode" / "mcp.json").read_text(encoding="utf-8"))
        plugin = json.loads(PLUGIN.read_text(encoding="utf-8"))

        assert cursor["mcpServers"]["dpolens"]["url"] == expected
        assert vscode["servers"]["dpolens"]["url"] == expected
        assert plugin["userConfig"]["url"]["default"] == expected

    def test_the_port_compose_publishes_is_the_one_the_server_listens_on(self) -> None:
        """Nothing maps one port to another, so the two cannot drift apart."""
        outside, inside = ports("mcp")

        assert inside == Settings.model_fields["port"].default
        assert outside == inside

    def test_the_documentation_names_the_same_url(self) -> None:
        port, _ = ports("mcp")

        for document in (REPO / "docs" / "mcp.md", CLIENTS / "README.md", REPO / "README.md"):
            text = document.read_text(encoding="utf-8")
            if "localhost" in text and "/mcp" in text:
                assert f"http://localhost:{port}/mcp" in text, document.name


class TestThePluginAndItsMarketplace:
    def test_the_marketplace_points_at_the_plugin_in_this_repository(self) -> None:
        marketplace = json.loads(MARKETPLACE.read_text(encoding="utf-8"))

        assert marketplace["name"] == "dpolens"
        assert marketplace["owner"]["name"]
        entry = marketplace["plugins"][0]
        assert entry["name"] == "dpolens"
        assert (REPO / entry["source"].removeprefix("./")).is_dir()

    def test_the_plugin_brings_the_server_the_skill_and_both_commands(self) -> None:
        plugin = json.loads(PLUGIN.read_text(encoding="utf-8"))

        assert plugin["name"] == "dpolens"
        assert plugin["mcpServers"]["dpolens"]["type"] == "http"
        assert (CLIENTS / "claude-code" / "skills" / "dpolens" / "SKILL.md").is_file()
        for command in ("policy-check", "policy-tour"):
            assert (CLIENTS / "claude-code" / "commands" / f"{command}.md").is_file()

    def test_the_plugin_asks_for_what_it_cannot_guess(self) -> None:
        """The URL and the token are the only two things it needs from a person."""
        plugin = json.loads(PLUGIN.read_text(encoding="utf-8"))

        assert set(plugin["userConfig"]) == {"url", "token"}
        assert plugin["mcpServers"]["dpolens"]["url"] == "${user_config.url}"
        assert "${user_config.token}" in plugin["mcpServers"]["dpolens"]["headers"]["Authorization"]


class TestTheComposeFile:
    def test_it_starts_the_four_things_an_instance_is(self) -> None:
        assert set(compose()["services"]) == {"db", "setup", "api", "mcp"}

    def test_the_api_waits_for_the_setup_to_finish(self) -> None:
        """Migrations, the packs and the index all have to exist before a request."""
        api = compose()["services"]["api"]

        assert api["depends_on"]["setup"]["condition"] == "service_completed_successfully"
        assert api["depends_on"]["db"]["condition"] == "service_healthy"

    def test_the_credential_is_shared_by_a_volume_and_not_by_the_environment(self) -> None:
        """A variable is visible to every process in a container and to anything that looks."""
        services = compose()["services"]

        assert "surface:/run/dpolens" in services["api"]["volumes"]
        assert "surface:/run/dpolens:ro" in services["mcp"]["volumes"]
        for service in services.values():
            for value in (service.get("environment") or {}).values():
                assert "dpol_" not in str(value)

    def test_the_two_database_roles_are_not_the_same_role(self) -> None:
        """The whole of the governance log's tamper evidence rests on this."""
        environment = compose()["services"]["api"]["environment"]

        assert "dpolens_app:" in environment["DPOLENS_DATABASE_URL"]
        assert "dpolens_owner:" in environment["DPOLENS_MIGRATION_DATABASE_URL"]

    def test_the_passwords_have_to_be_given(self) -> None:
        """No default, so a published file never ships a working secret."""
        raw = COMPOSE.read_text(encoding="utf-8")

        assert "${DPOLENS_APP_PASSWORD:?" in raw
        assert "${DPOLENS_OWNER_PASSWORD:?" in raw
