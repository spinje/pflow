#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"
uv run pflow analyze-cache \
  "$BASELINE_CASE_DIR/workflow.pflow.md" \
  --from-trace "$BASELINE_DIR/_shared/fixtures/live-gemini-translation.trace.json" \
  context="ignored-by-trace-mode"
