#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"

uv run pflow "$BASELINE_CASE_DIR/workflow.pflow.md" \
  --dry-run \
  context="$(cat "$BASELINE_DIR/_shared/long-stable-text.txt")" \
  'items=[{"text":"alpha"},{"text":"beta"},{"text":"gamma"}]'
