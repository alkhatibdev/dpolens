# The MCP server, which is a client of the HTTP API and nothing else.
#
# No engine, no database driver and no model: this image holds the protocol and
# an HTTP client, which is also why a surface can be written in any language.

FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    # The build runs as a user with no home directory, so there is nowhere for a
    # download cache to live, and nothing after the build would read it anyway.
    UV_NO_CACHE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/dpolens/.venv \
    PATH=/opt/dpolens/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1

# The same id as the API image, because the credential that image writes is
# readable by its owner alone and this is the process that has to read it.
RUN groupadd --gid 10001 dpolens \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin dpolens \
    && mkdir -p /opt/dpolens \
    && chown dpolens:dpolens /opt/dpolens

WORKDIR /opt/dpolens
USER dpolens

COPY --chown=dpolens:dpolens pyproject.toml uv.lock ./
COPY --chown=dpolens:dpolens packages/dpolens/pyproject.toml packages/dpolens/
COPY --chown=dpolens:dpolens packages/dpolens-mcp/pyproject.toml packages/dpolens-mcp/
RUN uv sync --frozen --no-dev --package dpolens-mcp --no-install-workspace

COPY --chown=dpolens:dpolens packages/dpolens-mcp/ packages/dpolens-mcp/
RUN uv sync --frozen --no-dev --package dpolens-mcp

EXPOSE 8765
CMD ["dpolens-mcp"]
