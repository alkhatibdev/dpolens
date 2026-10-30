"""The application, and what it refuses to start without.

Everything expensive is built once, at startup: the database engine and its pool
belong to the process, and a session belongs to one request. Two conditions are
checked before the first request rather than reported forever by a probe: the
database has to be migrated with the retrieval extensions, and this connection
must not be able to rewrite the governance log. An instance that can edit its own
audit trail has nothing to offer an auditor, so it declines to serve.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError

from dpolens import __version__
from dpolens.api import (
    corpus,
    health,
    instance,
    laws,
    logs,
    overview,
    people,
    policies,
    problems,
    roles,
    sessions,
    tokens,
)
from dpolens.api.dependencies import ON_BEHALF_OF_TOKEN, ON_BEHALF_OF_USER
from dpolens.api.limits import (
    CONNECTIONS_PER_REQUEST,
    BodyLimit,
    InFlight,
    RateLimiter,
    SignInThrottle,
)
from dpolens.engine.auth.catalog import bootstrap
from dpolens.engine.embedding import DEFAULT_MODEL, get_model
from dpolens.engine.embedding.encode import Embedder, ensure_cached
from dpolens.engine.logs.governance import Actor
from dpolens.engine.policies.store import MAX_UPLOAD_BYTES
from dpolens.engine.session import (
    POOL_OVERFLOW,
    POOL_SIZE,
    check_governance_privileges,
    create_db_engine,
    session_from,
)
from dpolens.settings import Settings, load_settings
from dpolens.telemetry import configure, get_logger, request_context

REQUEST_ID_HEADER = "X-Request-Id"
"""Kept with its prefix, unlike the headers this project invents, because proxies
and clients already emit this one and interoperability beats tidiness here."""

telemetry = get_logger(__name__)

DESCRIPTION = """
The only way into DPOLens. Every surface, including the MCP server and the
dashboard, is a client of this API.

Interfaces change without notice until 1.0. Errors are
[RFC 9457](https://www.rfc-editor.org/info/rfc9457/) problem details, and `type`
is the field to branch on.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    configure()

    engine = create_db_engine(settings)
    check_governance_privileges(engine)
    with session_from(engine) as opened:
        seeded = bootstrap(opened, actor=Actor(via="api"))

    # Refused here rather than on the first search: a server that reaches for the
    # network mid-request breaks the promise that the container runs offline.
    model = get_model(DEFAULT_MODEL)
    ensure_cached(model)
    embedder = Embedder(model, intra_op_num_threads=settings.intra_op_num_threads)

    app.state.engine = engine
    app.state.embedder = embedder
    app.state.limiter = RateLimiter(settings.rate_limit_per_minute)
    app.state.sign_in_throttle = SignInThrottle()
    telemetry.info(
        "api.started",
        version=__version__,
        seeded_roles=seeded,
        limit=settings.rate_limit_per_minute,
        model=model.name,
    )
    try:
        yield
    finally:
        # Closing the session while Python is still running is what keeps ONNX
        # Runtime from printing an alarming teardown message at interpreter exit.
        embedder.close()
        engine.dispose()
        telemetry.info("api.stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(
        title="DPOLens",
        version=__version__,
        description=DESCRIPTION,
        summary="Policies and law, with citations a client can check",
        lifespan=lifespan,
        # FastAPI's own pages, /docs and /redoc, load their scripts and fonts from other sites,
        # and nothing an instance serves reaches outside it. The reference is on dpolens.com,
        # and /openapi.json describes the API to any tool.
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    app.state.settings = settings or load_settings()

    app.add_exception_handler(problems.Problem, _problem_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    # Innermost, so a body that is too large is refused without waiting for a turn.
    app.add_middleware(InFlight, limit=(POOL_SIZE + POOL_OVERFLOW) // CONNECTIONS_PER_REQUEST)
    # The largest body any route takes is a policy file. Added before the request id, so that a
    # refusal carries one too.
    app.add_middleware(BodyLimit, limit=MAX_UPLOAD_BYTES)
    app.middleware("http")(_refuse_nul)
    app.middleware("http")(_request_line)
    app.middleware("http")(_request_id)

    app.include_router(health.router)
    app.include_router(sessions.router)
    app.include_router(tokens.router)
    app.include_router(corpus.router)
    app.include_router(people.router)
    app.include_router(roles.router)
    app.include_router(instance.router)
    app.include_router(sessions.links)
    app.include_router(logs.router)
    app.include_router(overview.router)
    app.include_router(laws.router)
    app.include_router(policies.router)
    return app


async def _problem_handler(request: Request, raised: Exception) -> Response:
    problem = raised if isinstance(raised, problems.Problem) else problems.not_found(str(raised))
    telemetry.info("api.refused", problem=problem.kind, status=problem.status)
    return problems.render(request, problem)


async def _validation_handler(request: Request, raised: Exception) -> Response:
    """A malformed request, reported in the same shape as every other failure.

    The field errors are included because they name the field, never its value:
    a rejected query must not travel back out through the error body.
    """
    errors = raised.errors() if isinstance(raised, RequestValidationError) else []
    where = [
        {"field": ".".join(str(part) for part in error.get("loc", ())), "problem": error.get("msg")}
        for error in errors
    ]
    return problems.render(
        request,
        problems.Problem(
            kind="invalid-request",
            title="Invalid request",
            status=422,
            detail="the request body or parameters are not valid",
            errors=where,
        ),
    )


async def _request_id(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """One id for one question, from the client when it sends a usable one.

    The MCP server makes two calls for one developer's question, introspection
    and then the request itself, so accepting an inbound id is what lets those be
    followed end to end. It has to be a uuid, which is also what stops a caller
    writing newlines into telemetry.
    """
    given = request.headers.get(REQUEST_ID_HEADER)
    with request_context(given if given and _is_uuid(given) else None) as request_id:
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


async def _request_line(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """One line for each request, in place of the server's access log.

    An access log writes the whole address, and an address carries what somebody sent: the
    words of a filter on the questions log, or a key as an AI assistant typed it. This line
    names the route the request matched, such as /v1/clauses/{key}, and never its values.
    """
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        telemetry.info(
            "api.request",
            method=request.method,
            route=getattr(route, "path", None),
            status=status,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )


async def _refuse_nul(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Refuse an address carrying the NUL character, which Postgres cannot hold.

    A key, a slug or a filter carrying one could be neither looked up nor kept in the query
    log, and would fail deep in a route as a server error.
    """
    if "\x00" in request.scope["path"] or b"%00" in request.scope["query_string"]:
        return problems.render(
            request,
            problems.Problem(
                kind="invalid-request",
                title="Invalid request",
                status=422,
                detail="the address cannot contain the NUL character",
                errors=[],
            ),
        )
    return await call_next(request)


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


__all__ = ["ON_BEHALF_OF_TOKEN", "ON_BEHALF_OF_USER", "REQUEST_ID_HEADER", "create_app"]
