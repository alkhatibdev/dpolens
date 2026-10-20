"""Compose hands each service the settings its own code reads.

A setting missing from a service's environment fails nowhere: the service runs on
its default and says nothing. The daily purge runs in the worker, so a retention
the API showed would never delete a question.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

COMPOSE = Path(__file__).resolve().parents[2] / "compose.yaml"


def environment(service: str) -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    given: dict[str, Any] = loaded["services"][service]["environment"]
    return given


@pytest.mark.parametrize(
    "name",
    [
        "DPOLENS_QUERY_LOG_RETENTION_DAYS",
        "DPOLENS_SESSION_IDLE_MINUTES",
        "DPOLENS_SESSION_LIFETIME_HOURS",
    ],
)
def test_the_worker_reads_what_the_daily_purge_deletes_by_as_the_api_does(name: str) -> None:
    assert name in environment("api")
    assert name in environment("worker")
