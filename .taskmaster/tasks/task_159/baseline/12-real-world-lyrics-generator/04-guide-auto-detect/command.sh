#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"
uv run pflow guide "$BASELINE_DIR/_shared/workflows/lyrics-generator/lyrics-generator.pflow.md"
