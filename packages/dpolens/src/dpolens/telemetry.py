"""Application telemetry: JSON lines on stdout.

This is not one of the two logs. The governance log and the query log are
product features stored in Postgres, permissioned and retained. Telemetry is
operational output, so it carries identifiers, counts and durations, and never
the text of a question, a clause or a document.
"""

from __future__ import annotations

import logging
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import structlog

FORBIDDEN_KEYS = frozenset(
    {
        "query",
        "query_text",
        "question",
        "text",
        "body_text",
        "clause_text",
        "answer",
        "token",
        "password",
        "api_key",
    }
)


class ForbiddenTelemetryField(Exception):
    """Raised when telemetry is given a field that could carry personal data."""


def _reject_forbidden_fields(
    _logger: Any, _method: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    found = FORBIDDEN_KEYS.intersection(event_dict)
    if found:
        raise ForbiddenTelemetryField(
            f"telemetry may not carry {sorted(found)}: question and clause text belong in "
            "the query log, which is redacted and expires"
        )
    return event_dict


def configure(level: int = logging.INFO) -> None:
    """Configure structlog once, at startup."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _reject_forbidden_fields,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger


@contextmanager
def request_context(request_id: str | None = None) -> Iterator[str]:
    """Bind one request id to everything emitted inside this block.

    Generated where a request enters and carried through the engine and into
    worker jobs, so one request can be followed end to end by id alone.
    """
    request_id = request_id or str(uuid.uuid4())
    structlog.contextvars.bind_contextvars(request_id=request_id)
    try:
        yield request_id
    finally:
        structlog.contextvars.unbind_contextvars("request_id")
