"""When a changed contract needs a line in the API's changelog.

Every contract change does, because the people building against the API have no
other way to find out. A release writing its version into the specification is
not one: it changes nothing a client can call.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from api_contract import contract_differs  # noqa: E402


def written(version: str, paths: dict[str, Any] | None = None) -> str:
    return json.dumps({"info": {"title": "DPOLens", "version": version}, "paths": paths or {}})


def test_a_release_writing_its_version_is_not_a_contract_change() -> None:
    assert not contract_differs(written("0.0.0"), written("0.1.0rc1"))


def test_a_new_route_is_a_contract_change_whatever_the_version() -> None:
    assert contract_differs(written("0.1.0"), written("0.1.0", {"/v1/new": {}}))
    assert contract_differs(written("0.1.0"), written("0.2.0", {"/v1/new": {}}))


def test_a_first_specification_is_a_change() -> None:
    assert contract_differs(None, written("0.1.0"))
