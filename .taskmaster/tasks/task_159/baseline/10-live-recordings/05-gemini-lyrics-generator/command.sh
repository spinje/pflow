#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"
SOURCE=$(head -c 3000 "$BASELINE_DIR/_shared/long-stable-text.txt")
uv run pflow analyze-cache \
  "$BASELINE_DIR/_shared/workflows/lyrics-generator/lyrics-generator.pflow.md" \
  --from-trace "$BASELINE_DIR/_shared/fixtures/live-gemini-lyrics-generator.trace.json" \
  sources="[\"$SOURCE\"]"
