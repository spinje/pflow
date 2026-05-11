#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"
uv run pflow analyze-cache \
  "$BASELINE_DIR/_shared/workflows/smoke-with-cache.pflow.md" \
  --from-trace "$BASELINE_DIR/_shared/fixtures/sample-2.1.0-trace.json" \
  context="ignored-by-trace-mode"
