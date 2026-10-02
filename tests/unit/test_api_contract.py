"""The committed specification has to match the routes.

CI enforces this too, but a contributor who changes a route should see it fail in
the test run rather than ten minutes later on a pull request.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dpolens.api.app import create_app
from dpolens.api.problems import MEDIA_TYPE
from dpolens.settings import Settings

SPEC = Path(__file__).parents[2] / "docs" / "openapi.json"
UNUSED = "postgresql://unused:unused@localhost:5432/unused"


def spec() -> dict[str, Any]:
    """The specification as the routes describe it. Nothing connects."""
    app = create_app(Settings.model_validate({"database_url": UNUSED}))
    return dict(app.openapi())


def test_the_committed_specification_matches_the_routes() -> None:
    generated = json.dumps(spec(), indent=2, ensure_ascii=False) + "\n"

    assert SPEC.read_text(encoding="utf-8") == generated, (
        "the API contract changed. Run `uv run python scripts/api_contract.py --write`, "
        "read the diff, and record what changed in docs/api-changelog.md"
    )


def test_every_route_is_under_v1_or_is_a_probe() -> None:
    """Routes live under /v1/ so the contract can be versioned. Probes are not
    part of the contract an orchestrator versions."""
    paths = set(spec()["paths"])

    assert paths == {
        "/live",
        "/ready",
        "/v1/search",
        "/v1/clauses/{key}",
        "/v1/clauses/{key}/subtree",
        "/v1/documents",
        "/v1/documents/{slug}",
        "/v1/tokens/introspect",
    }


def test_the_error_shape_is_in_the_specification() -> None:
    """A generated client should know what a failure looks like."""
    document = spec()
    schemas = document["components"]["schemas"]
    assert "ProblemDocument" in schemas
    assert set(schemas["ProblemDocument"]["required"]) == {
        "type",
        "title",
        "status",
        "detail",
        "instance",
    }

    search = document["paths"]["/v1/search"]["post"]
    for status in ("401", "403", "429"):
        assert MEDIA_TYPE in search["responses"][status]["content"]


def test_the_search_request_caps_the_question() -> None:
    """The cap is part of the contract, not an implementation detail."""
    document = spec()
    schema = document["components"]["schemas"]["SearchRequest"]

    assert schema["properties"]["query"]["maxLength"] == 1000
    assert schema["properties"]["limit"]["maximum"] == 50
    assert schema["properties"]["include_explanatory"]["default"] is False


def test_the_fusion_rule_is_not_a_parameter() -> None:
    """It is chosen by measurement. A client that could pick one would produce
    results nobody can reproduce."""
    schema = spec()["components"]["schemas"]["SearchRequest"]

    assert "fusion" not in schema["properties"]
    assert "rerank" not in schema["properties"]


def test_the_outline_carries_no_text() -> None:
    schema = spec()["components"]["schemas"]["OutlineEntry"]

    assert "text" not in schema["properties"]
    assert "children" in schema["properties"]
