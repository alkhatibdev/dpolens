#!/usr/bin/env bash
# Install DPOLens into an empty Claude Code profile, the way a user does.
#
#   prepare-profile.sh plugin     the plugin from the marketplace at /marketplace
#   prepare-profile.sh mcp-only   the MCP server on its own, with no skill
#
# The settings arrive on stdin as JSON, so the token is in no argument list.
set -euo pipefail

setup="${1:?which setup: plugin or mcp-only}"
values="$(cat)"

case "$setup" in
  plugin)
    claude plugin marketplace add /marketplace
    claude plugin install dpolens@dpolens
    printf '%s' "$values" | claude plugin configure dpolens@dpolens --values-stdin
    ;;
  mcp-only)
    claude mcp add-json --scope user dpolens "$values"
    ;;
  *)
    echo "unknown setup: $setup" >&2
    exit 2
    ;;
esac

cp -a "$CLAUDE_CONFIG_DIR"/. /home/node/profile/
