#!/usr/bin/env bash
# Write Qwen Code's settings into an empty profile: the model server it talks
# to, and DPOLens as an MCP server on its own, the entry `qwen mcp add` writes.
#
#   prepare-profile.sh mcp-only
#
# The settings arrive on stdin as JSON, so the token is in no argument list.
set -euo pipefail

setup="${1:?which setup: mcp-only}"
if [[ "$setup" != mcp-only ]]; then
  echo "Qwen Code has no DPOLens plugin; the setup is mcp-only" >&2
  exit 2
fi

mkdir -p "$HOME/.qwen"
cat > "$HOME/.qwen/settings.json"

cp -a "$HOME/.qwen"/. /home/node/profile/
