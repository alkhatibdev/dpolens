"""Recording what was asked, in a transaction of its own.

Of its own because the request may fail. A question the corpus could not answer,
or one that hit an error, is exactly the row worth keeping, and a row written
inside a failing request rolls back with it. This is the same lesson as recording
a refused token: the log of what happened has to outlive the thing that happened.

Telemetry never sees the question. It carries the operation, the outcome, counts
and durations, and the request id that ties them together.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field

from fastapi import Request

from dpolens.engine.auth.tokens import Authenticated
from dpolens.engine.logs.queries import Returned, record_query
from dpolens.engine.session import session_from
from dpolens.settings import Settings
from dpolens.telemetry import get_logger

telemetry = get_logger(__name__)


@dataclass
class Asked:
    """What the handler learned, filled in as it goes."""

    status: str = "ok"
    results: Sequence[Returned] = field(default_factory=tuple)

    def found(self, results: Sequence[Returned]) -> None:
        self.results = results
        self.status = "ok" if results else "no_match"


@contextmanager
def logged(
    request: Request,
    who: Authenticated,
    settings: Settings,
    *,
    operation: str,
    surface: str,
    query: str = "",
    target: str | None = None,
) -> Iterator[Asked]:
    """Write one query log row for this call, whatever happens to the call."""
    asked = Asked()
    try:
        yield asked
    except Exception:
        # Only when the handler had not already decided. A clause that is not
        # there is a miss, not an error, even though saying so raises.
        if asked.status == "ok":
            asked.status = "error"
        _write(request, who, settings, operation, surface, query, target, asked)
        raise
    _write(request, who, settings, operation, surface, query, target, asked)


def _write(
    request: Request,
    who: Authenticated,
    settings: Settings,
    operation: str,
    surface: str,
    query: str,
    target: str | None,
    asked: Asked,
) -> None:
    with session_from(request.app.state.engine) as own:
        entry_id = record_query(
            own,
            user_id=who.user.id,
            pat_id=who.token.id,
            surface=surface,
            operation=operation,
            status=asked.status,
            retention_days=settings.query_log_retention_days,
            query=query,
            target=target,
            results=asked.results,
            redaction_patterns=settings.redaction_patterns,
        )
    telemetry.info(
        "corpus.asked",
        operation=operation,
        surface=surface,
        outcome=asked.status,
        results=len(asked.results),
        entry=str(entry_id),
        user=str(who.user.id),
    )


def surface_of(delegated: bool) -> str:
    """Which surface a call came through.

    A delegated call is the MCP server, because in this release that is the only
    thing a trusted surface credential is issued for. When a second surface
    exists it will have to say which it is rather than being inferred.
    """
    return "mcp" if delegated else "api"


def uuid_or_none(value: str | None) -> uuid.UUID | None:
    return uuid.UUID(value) if value else None
