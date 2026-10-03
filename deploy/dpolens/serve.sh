#!/bin/sh
# Serving the API, after making sure a surface has a credential to use.
#
# `ensure-surface` writes the credential to a file the MCP server reads, and
# never prints it. Running it again leaves a working credential alone.
set -eu

dpolens token ensure-surface --out "${DPOLENS_SURFACE_TOKEN_FILE:-/run/dpolens/surface-token}"

exec uvicorn --factory dpolens.api.app:create_app \
    --host "${DPOLENS_API_HOST:-0.0.0.0}" \
    --port "${DPOLENS_API_PORT:-8000}" \
    --workers "${DPOLENS_API_WORKERS:-1}"
