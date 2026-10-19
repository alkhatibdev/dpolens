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

exec uvicorn --factory dpolens.api.app:create_app \
    --host "${DPOLENS_API_HOST:-0.0.0.0}" \
    --port "${DPOLENS_API_PORT:-8000}" \
    --workers "${DPOLENS_API_WORKERS:-1}"
