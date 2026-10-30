#!/bin/sh
# Serving the API, after making sure a surface has a credential to use.
#
# `ensure-surface` writes the credential to a file the MCP server reads, and
# never prints it. Running it again leaves a working credential alone.
set -eu

dpolens token ensure-surface --out "${DPOLENS_SURFACE_TOKEN_FILE:-/run/dpolens/surface-token}"

# A community version answers everyone as one Community account. The file names the
# account and its token for the MCP server, and holds no secret.
case "${DPOLENS_COMMUNITY:-false}" in
    true | 1 | yes)
        dpolens token ensure-community --out "${DPOLENS_COMMUNITY_FILE:-/run/dpolens/community}"
        ;;
esac

# No access log: it writes each address whole, and an address can carry what somebody asked.
# The API writes its own line for each request instead, naming the route.
exec uvicorn --factory dpolens.api.app:create_app \
    --host "${DPOLENS_API_HOST:-0.0.0.0}" \
    --port "${DPOLENS_API_PORT:-8000}" \
    --workers "${DPOLENS_API_WORKERS:-1}" \
    --no-access-log
