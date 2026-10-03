"""Running the MCP server.

Streamable HTTP is the only transport, and every surface authenticates the one
way the API already understands.

Each request is answered on its own, with no session to keep and no stream to
hold open: this server has nothing to push, and a search takes a tenth of a
second.
"""

from __future__ import annotations

import logging

import uvicorn
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

from dpolens_mcp.api import Api
from dpolens_mcp.credential import Credential
from dpolens_mcp.server import build
from dpolens_mcp.settings import Settings

PATH = "/mcp"
"""Where clients connect. The whole URL is http://host:port/mcp."""


def guarded(settings: Settings) -> TransportSecuritySettings:
    """Which Host and Origin headers this server answers.

    Checked on purpose, and not only when the server listens on loopback. A
    server bound to every interface is exactly the one a page in a browser can
    be pointed at, so the names it answers to are named rather than assumed.
    """
    hosts = settings.hosts
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=[f"{scheme}://{host}" for host in hosts for scheme in ("http", "https")],
    )


def asgi(settings: Settings, api: Api) -> Starlette:
    """The application a container serves, which is also the one the tests drive."""
    return build(settings, api).streamable_http_app(
        streamable_http_path=PATH,
        stateless_http=True,
        json_response=True,
        transport_security=guarded(settings),
    )


def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    api = Api(
        base_url=settings.api,
        credential=Credential(settings.surface_token_file),
        timeout=settings.request_timeout_seconds,
    )
    uvicorn.run(
        asgi(settings, api),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
