#!/usr/bin/env bash
# One trigger run in Qwen Code: a fresh copy of the prepared profile, then one prompt.
#
# The prompt and the turn limit arrive as TASK_* variables, and the model is
# named in the settings. The stream of events Qwen Code prints is the whole
# record of the run.
set -euo pipefail

cp -a /home/node/profile/. "$HOME/.qwen"/

exec qwen "${TASK_PROMPT:?}" \
  --output-format stream-json \
  --approval-mode yolo \
  --max-session-turns "${TASK_MAX_TURNS:-25}"
