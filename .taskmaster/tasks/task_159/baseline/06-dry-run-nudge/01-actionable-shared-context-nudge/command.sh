#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"

uv run pflow "$BASELINE_CASE_DIR/workflow.pflow.md" \
  --dry-run \
  article="$(cat "$BASELINE_DIR/_shared/long-stable-text.txt")"
