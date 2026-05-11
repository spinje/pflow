#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"
uv run pflow analyze-cache "$BASELINE_DIR/_shared/workflows/lyrics-generator/song-creator/song-creator.pflow.md" --no-trace-autoload
