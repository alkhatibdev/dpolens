"""Telemetry never carries question or clause text.

The rule is easiest to break exactly when it matters: the moment someone wants
to print a query is the moment retrieval is misbehaving.
"""

from __future__ import annotations

import pytest

from dpolens import telemetry


@pytest.fixture(autouse=True)
def configured() -> None:
    telemetry.configure()


def test_identifiers_and_counts_are_fine() -> None:
    log = telemetry.get_logger(__name__)

    log.info("pack.loaded", pack_slug="gdpr", clauses=272, duration_ms=1843)


@pytest.mark.parametrize("field", ["query", "question", "body_text", "answer", "token"])
def test_forbidden_fields_raise(field: str) -> None:
    log = telemetry.get_logger(__name__)

    with pytest.raises(telemetry.ForbiddenTelemetryField):
        log.info("search.completed", **{field: "how long do we keep deleted accounts"})


def test_request_id_is_bound_for_the_block() -> None:
    with telemetry.request_context() as request_id:
        assert len(request_id) == 36
