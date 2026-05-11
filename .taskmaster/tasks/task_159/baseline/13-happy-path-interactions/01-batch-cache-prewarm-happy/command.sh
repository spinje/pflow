#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"
LONG=$(cat "$BASELINE_DIR/_shared/long-stable-text.txt")
uv run pflow analyze-cache "$BASELINE_CASE_DIR/workflow.pflow.md" --no-trace-autoload --format=json \
  context="$LONG" \
  'items=[{"text":"a"},{"text":"b"},{"text":"c"},{"text":"d"},{"text":"e"},{"text":"f"},{"text":"g"},{"text":"h"}]'
