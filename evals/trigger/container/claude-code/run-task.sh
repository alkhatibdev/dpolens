#!/usr/bin/env bash
# One trigger run: a fresh copy of the prepared profile, then one prompt.
#
# The prompt and the limits arrive as TASK_* variables. The stream of events
# Claude Code prints is the whole record of the run.
set -euo pipefail

cp -a /home/node/profile/. "$CLAUDE_CONFIG_DIR"/

args=(
  -p "${TASK_PROMPT:?}"
  --output-format stream-json
  --verbose
  --max-turns "${TASK_MAX_TURNS:-25}"
  --dangerously-skip-permissions
)
if [[ -n "${TASK_MODEL:-}" ]]; then
  args+=(--model "$TASK_MODEL")
fi
if [[ -n "${TASK_MAX_BUDGET_USD:-}" ]]; then
  args+=(--max-budget-usd "$TASK_MAX_BUDGET_USD")
fi

exec claude "${args[@]}"
